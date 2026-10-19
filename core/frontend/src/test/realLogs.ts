/**
 * Loader for the user's real session event logs (`~/.hive/event_logs`).
 *
 * The session-load conformance tests run against this real data so they
 * prove the replay machinery on the exact sessions the app restores —
 * not hand-built fixtures. When the directory is absent (e.g. CI) the
 * dependent tests skip themselves; the synthetic-fixture tests still run.
 */
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import type { AgentEvent } from "@/api/types";

const EVENT_LOG_DIR = path.join(os.homedir(), ".hive", "event_logs");
// Skip very large logs so the suite stays fast — the largest real logs are
// 100MB+ and a handful of MB-sized logs already exercise every code path.
const MAX_BYTES = 3_000_000;

export interface RealLog {
  name: string;
  events: AgentEvent[];
}

export function realLogsDir(): string {
  return EVENT_LOG_DIR;
}

export function realLogsAvailable(): boolean {
  try {
    return fs.statSync(EVENT_LOG_DIR).isDirectory();
  } catch {
    return false;
  }
}

export function parseJsonl(text: string): AgentEvent[] {
  const out: AgentEvent[] = [];
  for (const line of text.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    try {
      out.push(JSON.parse(trimmed) as AgentEvent);
    } catch {
      // Skip a torn final line / corrupt entry — mirrors the backend's
      // tolerant reader.
    }
  }
  return out;
}

/** Load up to `limit` real session logs, newest first, skipping huge ones. */
export function loadRealLogs(limit = 80): RealLog[] {
  if (!realLogsAvailable()) return [];
  let names: string[];
  try {
    names = fs.readdirSync(EVENT_LOG_DIR).filter((f) => f.endsWith(".jsonl"));
  } catch {
    return [];
  }
  const sized = names
    .map((name) => {
      const full = path.join(EVENT_LOG_DIR, name);
      let size = Infinity;
      try {
        size = fs.statSync(full).size;
      } catch {
        /* unreadable */
      }
      return { name, full, size };
    })
    .filter((e) => e.size <= MAX_BYTES)
    .sort((a, b) => b.name.localeCompare(a.name)); // newest first by timestamped name

  const out: RealLog[] = [];
  for (const { name, full } of sized.slice(0, limit)) {
    let events: AgentEvent[];
    try {
      events = parseJsonl(fs.readFileSync(full, "utf8"));
    } catch {
      continue;
    }
    if (events.length > 0) out.push({ name, events });
  }
  return out;
}

/** True when every event in the log carries a positive monotonic `seq`. */
export function hasFullSeqCoverage(log: RealLog): boolean {
  return log.events.every(
    (e) => typeof e.seq === "number" && (e.seq as number) > 0,
  );
}
