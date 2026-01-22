import fs from "fs";
import path from "path";
import crypto from "crypto";
import { Pool, PoolClient } from "pg";
import pricingService from "./pricing_service";

let _tsdbPool: Pool | undefined;
let _schemaReadyPromise: Promise<void> | null;
const _schemaReadyByName = new Map<string, Promise<void>>(); // Per-schema initialization tracking
const SCHEMA_SQL = fs.readFileSync(path.join(__dirname, "schema.sql"), "utf8");

const safeParseJson = (val: unknown): unknown => {
  if (val === null || val === undefined) return null;
  if (typeof val === "object") return val;
  if (typeof val === "string") {
    try {
      return JSON.parse(val);
    } catch (_e) {
      return null;
    }
  }
  return null;
};

const asObject = (val: unknown, fallback: Record<string, unknown> = {}): Record<string, unknown> => {
  const parsed = safeParseJson(val);
  if (parsed && !Array.isArray(parsed) && typeof parsed === "object") return parsed as Record<string, unknown>;
  if (val && typeof val === "object" && !Array.isArray(val)) return val as Record<string, unknown>;
  return fallback;
};

const asArray = (val: unknown, fallback: unknown[] = []): unknown[] => {
  if (Array.isArray(val)) return val;
  const parsed = safeParseJson(val);
  if (Array.isArray(parsed)) return parsed;
  if (typeof val === "string") {
    const trimmed = val.trim();
    if (trimmed.startsWith("{") && trimmed.endsWith("}")) {
      const inner = trimmed.slice(1, -1).trim();
      if (!inner) return [];
      return inner
        .split(",")
        .map((s) => s.trim().replace(/^"+|"+$/g, ""))
        .filter(Boolean);
    }
    return [val];
  }
  if (val !== null && val !== undefined && typeof val !== "object" && typeof val !== "function") {
    return [val];
  }
  return fallback;
};

const buildMetadata = (raw: Record<string, unknown>): Record<string, unknown> | null => {
  const base = asObject(raw.metadata ?? raw.meta ?? raw.properties ?? raw.extra, {});
  const tags = asArray(raw.tags ?? raw.labels, []) as string[];
  if (tags && tags.length) {
    base.tags = tags;
  }
  const sessionId = raw.session_id ?? raw.sessionId;
  if (sessionId !== undefined && sessionId !== null && base.session_id === undefined) {
    base.session_id = sessionId;
  }
  const environment = raw.environment ?? raw.env;
  if (environment && base.environment === undefined) {
    base.environment = environment;
  }
  return Object.keys(base).length ? base : null;
};

interface UsageData {
  input_tokens?: number;
  output_tokens?: number;
  total_tokens?: number;
  cached_tokens?: number;
  reasoning_tokens?: number;
  accepted_prediction_tokens?: number;
  rejected_prediction_tokens?: number;
}

const calcCost = (model: string, usage: UsageData = {}): number => {
  const inputTokens = Number.isFinite(Number(usage.input_tokens)) ? Number(usage.input_tokens) : 0;
  const outputTokens = Number.isFinite(Number(usage.output_tokens)) ? Number(usage.output_tokens) : 0;
  const cachedTokens = Number.isFinite(Number(usage.cached_tokens)) ? Number(usage.cached_tokens) : 0;

  const result = pricingService.calculateCostSync({
    model: model || "",
    input_tokens: inputTokens,
    output_tokens: outputTokens,
    cached_tokens: cachedTokens,
  });

  return result.total;
};

// =============================================================================
// Content Storage Types and Utilities
// =============================================================================

interface ContentCapture {
  system_prompt?: string;
  messages?: unknown[];
  tools?: unknown[];
  params?: Record<string, unknown>;
  response_content?: string;
  finish_reason?: string;
  choice_count?: number;
  has_images?: boolean;
  image_urls?: string[];
}

interface ContentReference {
  content_type: string;
  content_hash: string;
  byte_size: number;
  message_count?: number;
  truncated_preview?: string;
}

interface ContentToStore {
  content_hash: string;
  content: string;
  byte_size: number;
}

/**
 * Generate SHA-256 hash of content for content-addressable storage
 */
const hashContent = (content: string): string => {
  return crypto.createHash("sha256").update(content, "utf8").digest("hex");
};

/**
 * Create a truncated preview of content (first 200 chars)
 */
const createPreview = (content: string, maxLength: number = 200): string => {
  if (!content || content.length <= maxLength) return content || "";
  return content.slice(0, maxLength) + "...";
};

/**
 * Extract content from ContentCapture and prepare for storage
 * Returns content references for warm table and content items for cold table
 */
const extractContent = (
  contentCapture: ContentCapture | null | undefined
): { refs: ContentReference[]; items: ContentToStore[] } => {
  if (!contentCapture) {
    return { refs: [], items: [] };
  }

  const refs: ContentReference[] = [];
  const items: ContentToStore[] = [];
  const seenHashes = new Set<string>();

  // Helper to process a content field
  const processContent = (
    type: string,
    value: unknown,
    messageCount?: number
  ): void => {
    if (value === null || value === undefined) return;

    const contentStr = typeof value === "string" ? value : JSON.stringify(value);
    if (!contentStr || contentStr === "null" || contentStr === "{}") return;

    const hash = hashContent(contentStr);
    const byteSize = Buffer.byteLength(contentStr, "utf8");

    refs.push({
      content_type: type,
      content_hash: hash,
      byte_size: byteSize,
      message_count: messageCount,
      truncated_preview: createPreview(contentStr),
    });

    // Only store content once per hash (deduplication within batch)
    if (!seenHashes.has(hash)) {
      seenHashes.add(hash);
      items.push({
        content_hash: hash,
        content: contentStr,
        byte_size: byteSize,
      });
    }
  };

  // Extract each content type
  if (contentCapture.system_prompt) {
    processContent("system_prompt", contentCapture.system_prompt);
  }

  if (contentCapture.messages && Array.isArray(contentCapture.messages) && contentCapture.messages.length > 0) {
    processContent("messages", contentCapture.messages, contentCapture.messages.length);
  }

  if (contentCapture.response_content) {
    processContent("response", contentCapture.response_content);
  }

  if (contentCapture.tools && Array.isArray(contentCapture.tools) && contentCapture.tools.length > 0) {
    processContent("tools", contentCapture.tools);
  }

  // Only store params if they have meaningful values (not all nulls)
  if (contentCapture.params) {
    const hasValues = Object.values(contentCapture.params).some(
      (v) => v !== null && v !== undefined
    );
    if (hasValues) {
      processContent("params", contentCapture.params);
    }
  }

  return { refs, items };
};

const parseDate = (val: unknown): Date | null => {
  if (!val) return null;
  const d = new Date(val as string | number | Date);
  return Number.isNaN(d.getTime()) ? null : d;
};

const numberOrNull = (val: unknown): number | null => {
  const n = Number(val);
  return Number.isFinite(n) ? n : null;
};

interface RawEvent {
  timestamp?: unknown;
  team_id?: unknown;
  traceId?: string;
  trace_id?: string;
  spanId?: string;
  span_id?: string;
  parent_span_id?: string;
  callSequence?: number;
  call_sequence?: number;
  requestId?: string;
  request_id?: string;
  provider?: string;
  model?: string;
  stream?: boolean;
  agent?: string;
  agent_name?: string;
  user_id?: string;
  latency_ms?: number;
  usage?: UsageData;
  input_tokens?: number;
  output_tokens?: number;
  total_tokens?: number;
  cached_tokens?: number;
  reasoning_tokens?: number;
  accepted_prediction_tokens?: number;
  rejected_prediction_tokens?: number;
  metadata?: Record<string, unknown>;
  meta?: Record<string, unknown>;
  properties?: Record<string, unknown>;
  extra?: Record<string, unknown>;
  tags?: string[];
  labels?: string[];
  session_id?: string;
  sessionId?: string;
  environment?: string;
  env?: string;
  agentStack?: string[];
  agent_stack?: string[];
  callSite?: Record<string, unknown>;
  call_site?: Record<string, unknown>;
  call_site_file?: string;
  call_site_line?: number;
  call_site_column?: number;
  call_site_function?: string;
  call_stack?: string[];
  content_capture?: Record<string, unknown>;
}

interface NormalizedEvent {
  timestamp: Date;
  ingest_date: string;
  team_id: string;
  trace_id: string;
  span_id: string | null;
  parent_span_id: string | null;
  request_id: string | null;
  provider: string | null;
  call_sequence: number;
  model: string;
  stream: boolean;
  agent: string | null;
  agent_name: string | null;
  user_id: string | null;
  latency_ms: number | null;
  usage_input_tokens: number | null;
  usage_output_tokens: number | null;
  usage_total_tokens: number | null;
  usage_cached_tokens: number | null;
  usage_reasoning_tokens: number | null;
  usage_accepted_prediction_tokens: number | null;
  usage_rejected_prediction_tokens: number | null;
  metadata: Record<string, unknown> | null;
  call_site: Record<string, unknown>;
  agent_stack: string[];
  cost_total: number;
  // Hot table fields (lightweight content indicators)
  has_content: boolean;
  finish_reason: string | null;
  tool_call_count: number;
  // Content data for warm/cold storage (extracted separately)
  content_refs: ContentReference[];
  content_items: ContentToStore[];
  // Deprecated: kept for backward compatibility during migration
  content_capture: Record<string, unknown> | null;
}

const normalizeEvent = (raw: RawEvent): NormalizedEvent | null => {
  const ts = raw.timestamp;
  const teamId = raw.team_id;
  const parsedTs = parseDate(ts);
  if (!parsedTs) return null;

  const traceId = raw.traceId || raw.trace_id;
  const spanId = raw.spanId || raw.span_id;
  const parentSpanId = raw.parent_span_id || null;
  const callSeqRaw = raw.callSequence ?? raw.call_sequence;
  if (
    traceId === undefined ||
    callSeqRaw === undefined ||
    callSeqRaw === null ||
    teamId === undefined ||
    teamId === null
  ) {
    return null;
  }
  const callSeq = Number(callSeqRaw);
  if (!Number.isInteger(callSeq)) return null;

  const usage: UsageData = raw.usage || {
    input_tokens: raw.input_tokens,
    output_tokens: raw.output_tokens,
    total_tokens: raw.total_tokens,
    cached_tokens: raw.cached_tokens,
    reasoning_tokens: raw.reasoning_tokens,
    accepted_prediction_tokens: raw.accepted_prediction_tokens,
    rejected_prediction_tokens: raw.rejected_prediction_tokens,
  };
  // Extract agent - metadata.agent takes precedence over top-level agent
  const metadata = asObject(raw.metadata, {});
  const effectiveAgent = (metadata.agent as string) || raw.agent || null;

  let agentStack = asArray(raw.agentStack ?? raw.agent_stack, []) as string[];
  if (effectiveAgent) {
    const agentVal = String(effectiveAgent);
    if (!agentStack.includes(agentVal)) {
      agentStack = [agentVal, ...agentStack];
    }
  }
  const callSite =
    raw.callSite ||
    asObject(raw.call_site, {
      file: raw.call_site_file,
      line: raw.call_site_line,
      column: raw.call_site_column,
      function: raw.call_site_function,
      stack: asArray(raw.call_stack, []),
    });

  // Extract content for warm/cold storage
  const contentCapture = raw.content_capture as ContentCapture | undefined;
  const { refs: contentRefs, items: contentItems } = extractContent(contentCapture);

  // Extract lightweight content indicators for hot table
  const hasContent = contentRefs.length > 0;
  const finishReason = contentCapture?.finish_reason || null;

  // Count tool calls from messages or tool_calls field
  let toolCallCount = 0;
  if (contentCapture?.messages && Array.isArray(contentCapture.messages)) {
    for (const msg of contentCapture.messages) {
      const msgObj = msg as Record<string, unknown>;
      if (msgObj.tool_calls && Array.isArray(msgObj.tool_calls)) {
        toolCallCount += msgObj.tool_calls.length;
      }
    }
  }

  return {
    timestamp: parsedTs,
    ingest_date: parsedTs.toISOString().slice(0, 10),
    team_id: String(teamId),
    trace_id: String(traceId),
    span_id: spanId || null,
    parent_span_id: parentSpanId,
    request_id: raw.requestId || raw.request_id || null,
    provider: raw.provider || null,
    call_sequence: callSeq,
    model: raw.model || "",
    stream: Boolean(raw.stream),
    agent: agentStack[0] || null,
    agent_name: raw.agent_name || null,
    user_id: raw.user_id || null,
    latency_ms: numberOrNull(raw.latency_ms),
    usage_input_tokens: numberOrNull(usage.input_tokens),
    usage_output_tokens: numberOrNull(usage.output_tokens),
    usage_total_tokens: numberOrNull(usage.total_tokens),
    usage_cached_tokens: numberOrNull(usage.cached_tokens),
    usage_reasoning_tokens: numberOrNull(usage.reasoning_tokens),
    usage_accepted_prediction_tokens: numberOrNull(usage.accepted_prediction_tokens),
    usage_rejected_prediction_tokens: numberOrNull(usage.rejected_prediction_tokens),
    metadata: buildMetadata(raw as Record<string, unknown>),
    call_site: callSite as Record<string, unknown>,
    agent_stack: agentStack,
    cost_total: calcCost(raw.model || "", usage),
    // Hot table content indicators
    has_content: hasContent,
    finish_reason: finishReason,
    tool_call_count: toolCallCount,
    // Content for warm/cold storage
    content_refs: contentRefs,
    content_items: contentItems,
    // Deprecated: kept for backward compatibility
    content_capture: raw.content_capture || null,
  };
};

const dedupeEvents = (events: NormalizedEvent[]): NormalizedEvent[] => {
  const deduped = new Map<string, NormalizedEvent>();
  events.forEach((ev) => {
    const key = `${ev.trace_id}||${ev.call_sequence}`;
    const existing = deduped.get(key);
    if (!existing) {
      deduped.set(key, ev);
      return;
    }
    if (existing.timestamp && ev.timestamp && ev.timestamp > existing.timestamp) {
      deduped.set(key, ev);
    }
  });
  return Array.from(deduped.values());
};

const normalizeEvents = (rawEvents: RawEvent[] = []): NormalizedEvent[] => {
  const normalized: NormalizedEvent[] = [];
  rawEvents.forEach((ev) => {
    const n = normalizeEvent(ev);
    if (n) normalized.push(n);
  });
  return dedupeEvents(normalized);
};

const getTsdbPool = (): Pool => {
  if (_tsdbPool) return _tsdbPool;
  const connStr = (process.env.TSDB_PG_URL || "").replace(/\s+/g, "");
  if (connStr) {
    _tsdbPool = new Pool({
      connectionString: connStr,
      ssl: { rejectUnauthorized: false },
    });
    return _tsdbPool;
  }
  if ((global as unknown as Record<string, unknown>)._ACHO_PG_POOL) {
    _tsdbPool = (global as unknown as Record<string, unknown>)._ACHO_PG_POOL as Pool;
    return _tsdbPool;
  }
  throw new Error("TSDB pool not available. Set TSDB_PG_URL or initialize _ACHO_PG_POOL.");
};

const ensureSchema = async (client?: PoolClient): Promise<void> => {
  if (client) {
    // Get current schema name for per-schema caching
    const schemaResult = await client.query("SELECT current_schema()");
    const schemaName = schemaResult.rows[0]?.current_schema || "public";

    // Check if this schema is already initialized
    if (_schemaReadyByName.has(schemaName)) {
      return _schemaReadyByName.get(schemaName);
    }

    // Create and cache the initialization promise
    const initPromise = (async () => {
      try {
        await client.query(SCHEMA_SQL);
      } catch (err: unknown) {
        // Handle race condition - if object already exists, it's fine
        const pgError = err as { code?: string };
        if (pgError.code === "23505" || pgError.code === "42P07") {
          // 23505 = unique_violation, 42P07 = duplicate_table
          console.log(`[tsdb] Schema ${schemaName} already initialized (concurrent request)`);
          return;
        }
        throw err;
      }
    })();

    _schemaReadyByName.set(schemaName, initPromise);

    try {
      await initPromise;
    } catch (err: unknown) {
      _schemaReadyByName.delete(schemaName);
      throw err;
    }
    return;
  }

  if (_schemaReadyPromise) return _schemaReadyPromise;

  const pool = getTsdbPool();
  _schemaReadyPromise = (async () => {
    const executor = await pool.connect();
    try {
      await executor.query(SCHEMA_SQL);
    } finally {
      executor.release();
    }
  })();

  try {
    await _schemaReadyPromise;
  } catch (err: unknown) {
    _schemaReadyPromise = null;
    throw err;
  }
};

interface UpsertResult {
  rowsWritten: number;
  normalized: number;
  received?: number;
  contentStored?: number;
  contentDeduplicated?: number;
}

/**
 * Store content in cold storage (llm_content_store) with deduplication
 * Uses ON CONFLICT to increment ref_count for existing content
 */
const storeContentCold = async (
  executor: PoolClient,
  teamId: string,
  items: ContentToStore[]
): Promise<{ stored: number; deduplicated: number }> => {
  if (!items.length) return { stored: 0, deduplicated: 0 };

  // Batch upsert content items
  const cols = ["content_hash", "team_id", "content", "byte_size", "ref_count", "first_seen_at", "last_seen_at"];
  const values: unknown[] = [];
  const placeholders: string[] = [];
  const now = new Date();

  items.forEach((item, idx) => {
    const base = idx * cols.length;
    placeholders.push(`(${cols.map((__, i) => `$${base + i + 1}`).join(", ")})`);
    values.push(item.content_hash, teamId, item.content, item.byte_size, 1, now, now);
  });

  const sql = `
    INSERT INTO llm_content_store (${cols.join(", ")})
    VALUES ${placeholders.join(", ")}
    ON CONFLICT (content_hash, team_id)
    DO UPDATE SET
      ref_count = llm_content_store.ref_count + 1,
      last_seen_at = EXCLUDED.last_seen_at
    RETURNING (xmax = 0) AS inserted
  `;

  const result = await executor.query(sql, values);
  const inserted = result.rows.filter((r: { inserted: boolean }) => r.inserted).length;
  const deduplicated = items.length - inserted;

  return { stored: inserted, deduplicated };
};

/**
 * Store content references in warm storage (llm_event_content)
 */
const storeContentWarm = async (
  executor: PoolClient,
  events: NormalizedEvent[]
): Promise<number> => {
  // Collect all content references from all events
  const allRefs: Array<{
    timestamp: Date;
    trace_id: string;
    call_sequence: number;
    team_id: string;
    ref: ContentReference;
  }> = [];

  for (const ev of events) {
    for (const ref of ev.content_refs) {
      allRefs.push({
        timestamp: ev.timestamp,
        trace_id: ev.trace_id,
        call_sequence: ev.call_sequence,
        team_id: ev.team_id,
        ref,
      });
    }
  }

  if (!allRefs.length) return 0;

  const cols = [
    '"timestamp"',
    "trace_id",
    "call_sequence",
    "team_id",
    "content_type",
    "content_hash",
    "byte_size",
    "message_count",
    "truncated_preview",
  ];
  const values: unknown[] = [];
  const placeholders: string[] = [];

  allRefs.forEach((item, idx) => {
    const base = idx * cols.length;
    placeholders.push(`(${cols.map((__, i) => `$${base + i + 1}`).join(", ")})`);
    values.push(
      item.timestamp,
      item.trace_id,
      item.call_sequence,
      item.team_id,
      item.ref.content_type,
      item.ref.content_hash,
      item.ref.byte_size,
      item.ref.message_count || null,
      item.ref.truncated_preview || null
    );
  });

  const sql = `
    INSERT INTO llm_event_content (${cols.join(", ")})
    VALUES ${placeholders.join(", ")}
  `;

  await executor.query(sql, values);
  return allRefs.length;
};

const upsertEvents = async (rawEvents: RawEvent[] = [], client?: PoolClient): Promise<UpsertResult> => {
  const events = normalizeEvents(rawEvents);
  if (!events.length) {
    return { rowsWritten: 0, normalized: 0 };
  }

  // Hot table columns (metrics only, no full content_capture)
  const cols = [
    '"timestamp"',
    "ingest_date",
    "team_id",
    "user_id",
    "trace_id",
    "span_id",
    "parent_span_id",
    "request_id",
    "provider",
    "call_sequence",
    "model",
    "stream",
    "agent",
    "agent_name",
    "latency_ms",
    "usage_input_tokens",
    "usage_output_tokens",
    "usage_total_tokens",
    "usage_cached_tokens",
    "usage_reasoning_tokens",
    "usage_accepted_prediction_tokens",
    "usage_rejected_prediction_tokens",
    "call_site",
    "metadata",
    "agent_stack",
    "cost_total",
    // New lightweight content fields
    "has_content",
    "finish_reason",
    "tool_call_count",
    // Deprecated: kept for backward compatibility during migration
    "content_capture",
  ];

  const values: unknown[] = [];
  const placeholders: string[] = [];
  events.forEach((ev, idx) => {
    const base = idx * cols.length;
    placeholders.push(`(${cols.map((__, i) => `$${base + i + 1}`).join(", ")})`);
    values.push(
      ev.timestamp,
      ev.ingest_date,
      ev.team_id,
      ev.user_id,
      ev.trace_id,
      ev.span_id,
      ev.parent_span_id,
      ev.request_id,
      ev.provider,
      ev.call_sequence,
      ev.model,
      ev.stream,
      ev.agent,
      ev.agent_name,
      ev.latency_ms,
      ev.usage_input_tokens,
      ev.usage_output_tokens,
      ev.usage_total_tokens,
      ev.usage_cached_tokens,
      ev.usage_reasoning_tokens,
      ev.usage_accepted_prediction_tokens,
      ev.usage_rejected_prediction_tokens,
      JSON.stringify(ev.call_site || {}),
      ev.metadata ? JSON.stringify(ev.metadata) : null,
      JSON.stringify(ev.agent_stack || []),
      ev.cost_total,
      // New fields
      ev.has_content,
      ev.finish_reason,
      ev.tool_call_count,
      // Deprecated: store null for new events, keep for backward compat
      null
    );
  });

  const sql = `
    INSERT INTO llm_events (${cols.join(", ")})
    VALUES ${placeholders.join(", ")}
    ON CONFLICT ("timestamp", trace_id, call_sequence)
    DO UPDATE SET
      "timestamp" = EXCLUDED."timestamp",
      ingest_date = EXCLUDED.ingest_date,
      team_id = EXCLUDED.team_id,
      user_id = EXCLUDED.user_id,
      trace_id = EXCLUDED.trace_id,
      span_id = EXCLUDED.span_id,
      parent_span_id = EXCLUDED.parent_span_id,
      request_id = EXCLUDED.request_id,
      provider = EXCLUDED.provider,
      model = EXCLUDED.model,
      stream = EXCLUDED.stream,
      agent = EXCLUDED.agent,
      agent_name = EXCLUDED.agent_name,
      latency_ms = EXCLUDED.latency_ms,
      usage_input_tokens = EXCLUDED.usage_input_tokens,
      usage_output_tokens = EXCLUDED.usage_output_tokens,
      usage_total_tokens = EXCLUDED.usage_total_tokens,
      usage_cached_tokens = EXCLUDED.usage_cached_tokens,
      usage_reasoning_tokens = EXCLUDED.usage_reasoning_tokens,
      usage_accepted_prediction_tokens = EXCLUDED.usage_accepted_prediction_tokens,
      usage_rejected_prediction_tokens = EXCLUDED.usage_rejected_prediction_tokens,
      call_site = EXCLUDED.call_site,
      metadata = EXCLUDED.metadata,
      agent_stack = EXCLUDED.agent_stack,
      cost_total = EXCLUDED.cost_total,
      has_content = EXCLUDED.has_content,
      finish_reason = EXCLUDED.finish_reason,
      tool_call_count = EXCLUDED.tool_call_count
    WHERE EXCLUDED."timestamp" >= llm_events."timestamp"
  `;

  const pool = client ? null : getTsdbPool();
  const executor = client || (await pool!.connect());

  let contentStored = 0;
  let contentDeduplicated = 0;

  try {
    // 1. Insert into hot table (llm_events)
    await executor.query(sql, values);

    // 2. Collect all content items for cold storage (deduplicated across events)
    const allContentItems: ContentToStore[] = [];
    const seenHashes = new Set<string>();
    const teamId = events[0]?.team_id;

    for (const ev of events) {
      for (const item of ev.content_items) {
        if (!seenHashes.has(item.content_hash)) {
          seenHashes.add(item.content_hash);
          allContentItems.push(item);
        }
      }
    }

    // 3. Store content in cold storage (llm_content_store)
    if (allContentItems.length > 0 && teamId) {
      const coldResult = await storeContentCold(executor, teamId, allContentItems);
      contentStored = coldResult.stored;
      contentDeduplicated = coldResult.deduplicated;
    }

    // 4. Store content references in warm storage (llm_event_content)
    await storeContentWarm(executor, events);

  } finally {
    if (!client && executor && 'release' in executor) {
      (executor as PoolClient).release();
    }
  }

  return {
    rowsWritten: events.length,
    normalized: events.length,
    received: rawEvents.length,
    contentStored,
    contentDeduplicated,
  };
};

/**
 * Retrieve content from cold storage by hash
 */
const getContentByHash = async (
  teamId: string,
  contentHash: string,
  client?: PoolClient
): Promise<string | null> => {
  const pool = client ? null : getTsdbPool();
  const executor = client || (await pool!.connect());

  try {
    const result = await executor.query(
      `SELECT content FROM llm_content_store WHERE content_hash = $1 AND team_id = $2`,
      [contentHash, teamId]
    );
    return result.rows[0]?.content || null;
  } finally {
    if (!client && executor && "release" in executor) {
      (executor as PoolClient).release();
    }
  }
};

/**
 * Get all content references for an event
 */
const getEventContent = async (
  teamId: string,
  traceId: string,
  callSequence: number,
  client?: PoolClient
): Promise<Array<ContentReference & { content?: string }>> => {
  const pool = client ? null : getTsdbPool();
  const executor = client || (await pool!.connect());

  try {
    // Get content references from warm storage
    const refsResult = await executor.query(
      `SELECT content_type, content_hash, byte_size, message_count, truncated_preview
       FROM llm_event_content
       WHERE team_id = $1 AND trace_id = $2 AND call_sequence = $3`,
      [teamId, traceId, callSequence]
    );

    const refs = refsResult.rows as ContentReference[];

    // Optionally fetch full content from cold storage
    const results: Array<ContentReference & { content?: string }> = [];
    for (const ref of refs) {
      const content = await getContentByHash(teamId, ref.content_hash, executor);
      results.push({ ...ref, content: content || undefined });
    }

    return results;
  } finally {
    if (!client && executor && "release" in executor) {
      (executor as PoolClient).release();
    }
  }
};

interface DistinctAgentRecord {
  agent: string;
  agent_name: string | null;
  first_seen: Date;
  last_seen: Date;
  total_requests: number;
  total_cost: number;
}

/**
 * Get all distinct agents from events for a team
 * Returns agent identifiers with their first/last seen timestamps and usage stats
 */
const getDistinctAgents = async (
  teamId: string,
  options: {
    since?: Date;
    limit?: number;
  } = {},
  client?: PoolClient
): Promise<DistinctAgentRecord[]> => {
  const pool = client ? null : getTsdbPool();
  const executor = client || (await pool!.connect());

  try {
    const { since, limit = 100 } = options;

    let sql = `
      SELECT
        agent,
        MAX(agent_name) as agent_name,
        MIN("timestamp") as first_seen,
        MAX("timestamp") as last_seen,
        COUNT(*) as total_requests,
        COALESCE(SUM(cost_total), 0) as total_cost
      FROM llm_events
      WHERE team_id = $1
        AND agent IS NOT NULL
        AND agent != ''
    `;

    const params: unknown[] = [teamId];

    if (since) {
      sql += ` AND "timestamp" >= $${params.length + 1}`;
      params.push(since);
    }

    sql += `
      GROUP BY agent
      ORDER BY last_seen DESC
      LIMIT $${params.length + 1}
    `;
    params.push(limit);

    const result = await executor.query(sql, params);

    return result.rows.map((row: Record<string, unknown>) => ({
      agent: row.agent as string,
      agent_name: row.agent_name as string | null,
      first_seen: new Date(row.first_seen as string),
      last_seen: new Date(row.last_seen as string),
      total_requests: Number(row.total_requests),
      total_cost: Number(row.total_cost),
    }));
  } finally {
    if (!client && executor && "release" in executor) {
      (executor as PoolClient).release();
    }
  }
};

export {
  normalizeEvent,
  normalizeEvents,
  ensureSchema,
  upsertEvents,
  getTsdbPool,
  getContentByHash,
  getEventContent,
  getDistinctAgents,
};
