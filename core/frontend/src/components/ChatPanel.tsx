import { memo, useState, useRef, useEffect, useMemo } from "react";
import { Link } from "react-router-dom";
import {
  Send,
  Square,
  Crown,
  Cpu,
  Check,
  Loader2,
  Paperclip,
  X,
} from "lucide-react";
import WorkerRunBubble from "@/components/WorkerRunBubble";
import type { WorkerRunGroup } from "@/components/WorkerRunBubble";

export interface ImageContent {
  type: "image_url";
  image_url: { url: string };
}

export interface ContextUsageEntry {
  usagePct: number;
  messageCount: number;
  estimatedTokens: number;
  maxTokens: number;
}
import MarkdownContent from "@/components/MarkdownContent";
import QuestionWidget from "@/components/QuestionWidget";
import MultiQuestionWidget from "@/components/MultiQuestionWidget";
import { useQueenProfile } from "@/context/QueenProfileContext";
import { useColonyWorkers } from "@/context/ColonyWorkersContext";
import ParallelSubagentBubble, {
  type SubagentGroup,
} from "@/components/ParallelSubagentBubble";
import {
  formatMessageTime,
  formatDayDividerLabel,
  workerIdFromStreamId,
} from "@/lib/chat-helpers";

export interface ChatMessage {
  id: string;
  agent: string;
  agentColor: string;
  content: string;
  timestamp: string;
  type?:
    | "system"
    | "agent"
    | "user"
    | "tool_status"
    | "worker_input_request"
    | "run_divider"
    | "colony_link";
  role?: "queen" | "worker";
  /** Which worker thread this message belongs to (worker agent name) */
  thread?: string;
  /** Epoch ms when this message was first created — used for ordering queen/worker interleaving */
  createdAt?: number;
  /** Queen phase active when this message was created */
  phase?: "independent" | "working" | "reviewing";
  /** Images attached to a user message */
  images?: ImageContent[];
  /** Backend node_id that produced this message — used for subagent grouping */
  nodeId?: string;
  /** Backend execution_id for this message */
  executionId?: string;
  /** Backend stream_id — the per-worker identity used for grouping
   *  parallel-spawn workers into their own stacked WorkerRunBubble.
   *  "queen" for queen messages, "worker" for the single loaded
   *  worker (run_agent_with_input), or "worker:{uuid}" for each
   *  parallel worker spawned via run_parallel_workers. */
  streamId?: string;
  /** True when the message was sent while the queen was still processing */
  queued?: boolean;
}

interface ChatPanelProps {
  messages: ChatMessage[];
  onSend: (message: string, thread: string, images?: ImageContent[]) => void;
  isWaiting?: boolean;
  /** When true a worker is thinking (not yet streaming) */
  isWorkerWaiting?: boolean;
  /** When true the queen is busy (typing or streaming) — shows the stop button */
  isBusy?: boolean;
  activeThread: string;
  /** When true, the input is disabled (e.g. during loading) */
  disabled?: boolean;
  /** When false, the image attach button is hidden (model lacks vision support) */
  supportsImages?: boolean;
  /** Called when user clicks the stop button to cancel the queen's current turn */
  onCancel?: () => void;
  /** Pending question from ask_user — replaces textarea when present */
  pendingQuestion?: string | null;
  /** Options for the pending question */
  pendingOptions?: string[] | null;
  /** Multiple questions from ask_user_multiple */
  pendingQuestions?:
    | { id: string; prompt: string; options?: string[] }[]
    | null;
  /** Called when user submits an answer to the pending question */
  onQuestionSubmit?: (answer: string, isOther: boolean) => void;
  /** Called when user submits answers to multiple questions */
  onMultiQuestionSubmit?: (answers: Record<string, string>) => void;
  /** Called when user dismisses the pending question without answering */
  onQuestionDismiss?: () => void;
  /** Queen operating phase — shown as a tag on queen messages */
  queenPhase?: "independent" | "working" | "reviewing";
  /** When false, queen messages omit the phase badge */
  showQueenPhaseBadge?: boolean;
  /** Context window usage for queen and workers */
  contextUsage?: Record<string, ContextUsageEntry>;
  /** One-shot composer prefill. Applied to the textarea whenever the value changes. */
  initialDraft?: string | null;
  /** Queen profile this panel is attached to. When provided, clicking a
   *  queen avatar/name opens that queen's profile panel directly —
   *  no fragile name-based lookup against ``queenProfiles``. Nullable
   *  to tolerate pages that render the panel before the queen is
   *  resolved (e.g. new-chat bootstrap). */
  queenProfileId?: string | null;
  /** Queen ID — used to display the queen's avatar photo in messages */
  queenId?: string;
  /** Called when the user clicks a `colony_link` system message. Receives
   *  the colony name. The parent should call markColonySpawned + flip
   *  ``colonySpawned`` to lock the input. The Link still navigates. */
  onColonyLinkClick?: (colonyName: string) => void;
  /** When true, the composer is replaced with a "compact + new session"
   *  button — set by the parent after the user opens a spawned colony. */
  colonySpawned?: boolean;
  /** Name of the colony that locked this DM (shown on the locked button). */
  spawnedColonyName?: string | null;
  /** Display label for the queen on the locked button (e.g. "Charlotte"). */
  queenDisplayName?: string;
  /** Called when the user clicks the locked-state button. Should compact
   *  the current session and navigate to the new one. */
  onCompactAndFork?: () => void;
  /** When true, disable the compact-and-fork button (request in flight). */
  compactingAndForking?: boolean;
}

const queenColor = "hsl(45,95%,58%)";
const workerColor = "hsl(220,60%,55%)";

function getColor(_agent: string, role?: "queen" | "worker"): string {
  if (role === "queen") return queenColor;
  return workerColor;
}

// Honey-drizzle palette — based on color-hex.com/color-palette/80116
// #8e4200 · #db6f02 · #ff9624 · #ffb825 · #ffd69c + adjacent warm tones
const TOOL_HEX = [
  "#db6f02", // rich orange
  "#ffb825", // golden yellow
  "#ff9624", // bright orange
  "#c48820", // warm bronze
  "#e89530", // honey
  "#d4a040", // goldenrod
  "#cc7a10", // caramel
  "#e5a820", // sunflower
];

export function toolHex(name: string): string {
  let hash = 0;
  for (let i = 0; i < name.length; i++)
    hash = (hash * 31 + name.charCodeAt(i)) | 0;
  return TOOL_HEX[Math.abs(hash) % TOOL_HEX.length];
}

export function ToolActivityRow({ content }: { content: string }) {
  let tools: { name: string; done: boolean }[] = [];
  try {
    const parsed = JSON.parse(content);
    tools = parsed.tools || [];
  } catch {
    // Legacy plain-text fallback
    return (
      <div className="flex gap-3 pl-10">
        <span className="text-[11px] text-muted-foreground bg-muted/40 px-3 py-1 rounded-full border border-border/40">
          {content}
        </span>
      </div>
    );
  }

  if (tools.length === 0) return null;

  // Group by tool name → count done vs running
  const grouped = new Map<string, { done: number; running: number }>();
  for (const t of tools) {
    const entry = grouped.get(t.name) || { done: 0, running: 0 };
    if (t.done) entry.done++;
    else entry.running++;
    grouped.set(t.name, entry);
  }

  // Build pill list: running first, then done
  const runningPills: { name: string; count: number }[] = [];
  const donePills: { name: string; count: number }[] = [];
  for (const [name, counts] of grouped) {
    if (counts.running > 0) runningPills.push({ name, count: counts.running });
    if (counts.done > 0) donePills.push({ name, count: counts.done });
  }

  return (
    <div className="flex gap-3 pl-10">
      <div className="flex flex-wrap items-center gap-1.5">
        {runningPills.map((p) => {
          const hex = toolHex(p.name);
          return (
            <span
              key={`run-${p.name}`}
              className="inline-flex items-center gap-1 text-[11px] px-2.5 py-0.5 rounded-full"
              style={{
                color: hex,
                backgroundColor: `${hex}18`,
                border: `1px solid ${hex}35`,
              }}
            >
              <Loader2 className="w-2.5 h-2.5 animate-spin" />
              {p.name}
              {p.count > 1 && (
                <span className="text-[10px] font-medium opacity-70">
                  ×{p.count}
                </span>
              )}
            </span>
          );
        })}
        {donePills.map((p) => {
          const hex = toolHex(p.name);
          return (
            <span
              key={`done-${p.name}`}
              className="inline-flex items-center gap-1 text-[11px] px-2.5 py-0.5 rounded-full"
              style={{
                color: hex,
                backgroundColor: `${hex}18`,
                border: `1px solid ${hex}35`,
              }}
            >
              <Check className="w-2.5 h-2.5" />
              {p.name}
              {p.count > 1 && (
                <span className="text-[10px] opacity-80">×{p.count}</span>
              )}
            </span>
          );
        })}
      </div>
    </div>
  );
}

// --- Inline ask_user fallback ---------------------------------------------
// Sometimes the model prints the ask_user / ask_user_multiple payload as
// regular assistant text instead of invoking the tool. We detect that
// payload here and render a QuestionWidget / MultiQuestionWidget inline so
// the user still gets the nice button UI. Submissions are sent back as a
// regular user message via onSend (there is no pending backend state to
// fulfill, so we treat it like the user answering in chat).

type AskUserInlinePayload =
  | { kind: "single"; question: string; options: string[] }
  | {
      kind: "multi";
      questions: { id: string; prompt: string; options?: string[] }[];
    };

function detectAskUserPayload(content: string): AskUserInlinePayload | null {
  if (!content) return null;
  let text = content.trim();
  if (!text) return null;
  // Strip an optional ```json ... ``` / ``` ... ``` code fence
  const fence = text.match(/^```(?:json|JSON)?\s*([\s\S]*?)\s*```$/);
  if (fence) text = fence[1].trim();
  // Strip surrounding double quotes that fully wrap a JSON object
  if (text.length >= 2 && text.startsWith('"') && text.endsWith('"')) {
    const inner = text.slice(1, -1).trim();
    if (inner.startsWith("{") && inner.endsWith("}")) text = inner;
  }
  if (!text.startsWith("{") || !text.endsWith("}")) return null;
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    return null;
  }
  if (!parsed || typeof parsed !== "object") return null;
  const obj = parsed as Record<string, unknown>;

  // ask_user_multiple: { questions: [{ id, prompt, options? }, ...] }
  if (Array.isArray(obj.questions)) {
    const raw = obj.questions as unknown[];
    if (raw.length < 1 || raw.length > 8) return null;
    const questions: { id: string; prompt: string; options?: string[] }[] = [];
    for (let i = 0; i < raw.length; i++) {
      const q = raw[i];
      if (!q || typeof q !== "object") return null;
      const qo = q as Record<string, unknown>;
      const prompt =
        typeof qo.prompt === "string"
          ? qo.prompt
          : typeof qo.question === "string"
            ? qo.question
            : null;
      if (!prompt) return null;
      const id = typeof qo.id === "string" && qo.id ? qo.id : `q${i}`;
      let options: string[] | undefined;
      if (
        Array.isArray(qo.options) &&
        qo.options.every((o) => typeof o === "string")
      ) {
        options = qo.options as string[];
      }
      questions.push({ id, prompt, options });
    }
    return { kind: "multi", questions };
  }

  // ask_user: { question: string, options: string[] }
  const question = typeof obj.question === "string" ? obj.question : null;
  const options =
    Array.isArray(obj.options) &&
    obj.options.every((o) => typeof o === "string")
      ? (obj.options as string[])
      : null;
  if (!question || !options || options.length < 2) return null;
  return { kind: "single", question, options };
}

function InlineAskUserBubble({
  msg,
  payload,
  activeThread,
  onSend,
  queenPhase,
  showQueenPhaseBadge = true,
  queenProfileId,
  queenAvatarUrl,
}: {
  msg: ChatMessage;
  payload: AskUserInlinePayload;
  activeThread: string;
  queenAvatarUrl?: string | null;
  onSend: (
    message: string,
    thread: string,
    images?: ImageContent[],
  ) => void;
  queenPhase?: "independent" | "working" | "reviewing";
  showQueenPhaseBadge?: boolean;
  queenProfileId?: string | null;
}) {
  const [state, setState] = useState<"pending" | "submitted" | "dismissed">(
    "pending",
  );

  // Once the user submits an answer via the inline widget, hide the whole
  // bubble — their reply appears right after as a normal user message.
  if (state === "submitted") return null;

  // If the user dismissed without answering, fall back to the regular
  // MarkdownContent rendering so they can still see what the model said.
  if (state === "dismissed") {
    return (
      <MessageBubble
        msg={msg}
        queenPhase={queenPhase}
        showQueenPhaseBadge={showQueenPhaseBadge}
        queenProfileId={queenProfileId}
        queenAvatarUrl={queenAvatarUrl}
      />
    );
  }

  const isQueen = msg.role === "queen";
  const color = getColor(msg.agent, msg.role);
  const thread = msg.thread || activeThread;

  const { openQueenProfile } = useQueenProfile();
  const { openColonyWorkers } = useColonyWorkers();
  const resolvedQueenProfileId = isQueen ? queenProfileId ?? null : null;
  const handleQueenClick = resolvedQueenProfileId
    ? () => openQueenProfile(resolvedQueenProfileId)
    : undefined;
  const workerId =
    !isQueen && msg.role === "worker"
      ? workerIdFromStreamId(msg.streamId)
      : null;
  const handleWorkerClick =
    msg.role === "worker"
      ? () => openColonyWorkers(workerId ?? undefined)
      : undefined;
  const handleAvatarClick = handleQueenClick ?? handleWorkerClick;
  const avatarTitle = handleQueenClick
    ? `View ${msg.agent}'s profile`
    : handleWorkerClick
      ? "Open worker in colony sidebar"
      : undefined;

  const handleSingle = (answer: string) => {
    setState("submitted");
    onSend(answer, thread);
  };

  const handleMulti = (answers: Record<string, string>) => {
    setState("submitted");
    if (payload.kind !== "multi") return;
    // Format answers as a readable, numbered list for the outgoing message.
    const lines = payload.questions.map((q, i) => {
      const a = answers[q.id] ?? "";
      return `${i + 1}. ${q.prompt}\n   ${a}`;
    });
    onSend(lines.join("\n"), thread);
  };

  return (
    <div className="flex gap-3">
      <div
        className={`flex-shrink-0 ${isQueen ? "w-9 h-9" : "w-7 h-7"} rounded-xl flex items-center justify-center overflow-hidden${handleAvatarClick ? " cursor-pointer hover:opacity-80 transition-opacity" : ""}`}
        style={isQueen && queenAvatarUrl ? undefined : {
          backgroundColor: `${color}18`,
          border: `1.5px solid ${color}35`,
          boxShadow: isQueen ? `0 0 12px ${color}20` : undefined,
        }}
        onClick={handleAvatarClick}
        title={avatarTitle}
      >
        {isQueen ? (
          <QueenAvatarIcon url={queenAvatarUrl ?? null} size={9} />
        ) : (
          <Cpu className="w-3.5 h-3.5" style={{ color }} />
        )}
      </div>
      <div
        className={`flex-1 min-w-0 ${isQueen ? "max-w-[85%]" : "max-w-[75%]"}`}
      >
        <div className="flex items-center gap-2 mb-1">
          <span
            className={`font-medium ${isQueen ? "text-sm" : "text-xs"}${handleQueenClick ? " cursor-pointer hover:underline" : ""}`}
            style={{ color }}
            onClick={handleQueenClick}
          >
            {msg.agent}
          </span>
          {(!isQueen || showQueenPhaseBadge) && (
            <span
              className={`text-[10px] font-medium px-1.5 py-0.5 rounded-md ${
                isQueen
                  ? "bg-primary/15 text-primary"
                  : "bg-muted text-muted-foreground"
              }`}
            >
              {isQueen
                ? (msg.phase ?? queenPhase) === "working"
                  ? "working"
                  : (msg.phase ?? queenPhase) === "reviewing"
                    ? "reviewing"
                    : "independent"
                : "Worker"}
            </span>
          )}
        </div>
        {payload.kind === "single" ? (
          <QuestionWidget
            inline
            question={payload.question}
            options={payload.options}
            onSubmit={handleSingle}
            onDismiss={() => setState("dismissed")}
          />
        ) : (
          <MultiQuestionWidget
            inline
            questions={payload.questions}
            onSubmit={handleMulti}
            onDismiss={() => setState("dismissed")}
          />
        )}
      </div>
    </div>
  );
}

function QueenAvatarIcon({ url, size }: { url: string | null; size: number }) {
  const [ok, setOk] = useState(!!url);
  const dim = size === 9 ? "w-9 h-9" : "w-7 h-7";
  if (ok && url) {
    return <img src={url} alt="" className={`${dim} rounded-xl object-cover`} onError={() => setOk(false)} />;
  }
  return <Crown className={size === 9 ? "w-4 h-4" : "w-3.5 h-3.5"} style={{ color: queenColor }} />;
}

const MessageBubble = memo(
  function MessageBubble({
    msg,
    queenPhase,
    showQueenPhaseBadge = true,
    queenProfileId,
    queenAvatarUrl,
    onColonyLinkClick,
  }: {
    msg: ChatMessage;
    queenPhase?: "independent" | "working" | "reviewing";
    showQueenPhaseBadge?: boolean;
    queenProfileId?: string | null;
    queenAvatarUrl?: string | null;
    onColonyLinkClick?: (colonyName: string) => void;
  }) {
    const isUser = msg.type === "user";
    const isQueen = msg.role === "queen";
    const color = getColor(msg.agent, msg.role);

    // Clicking a queen avatar/name opens the queen profile panel. The
    // owning page passes its queenProfileId down — we don't fall back
    // to a name-match against ``queenProfiles`` because display names
    // aren't unique or stable (colony chat uses static QUEEN_REGISTRY
    // labels, queen-dm uses user-editable profile names; matching by
    // name silently breaks when the profile is renamed or not listed).
    const { openQueenProfile } = useQueenProfile();
    const { openColonyWorkers } = useColonyWorkers();
    const resolvedQueenProfileId = isQueen ? queenProfileId ?? null : null;
    // Worker messages: clicking the avatar opens the Colony Workers
    // sidebar, pre-selecting this worker when its uuid is embedded in
    // the streamId (parallel fan-out case).
    const workerId =
      !isQueen && msg.role === "worker"
        ? workerIdFromStreamId(msg.streamId)
        : null;

    if (msg.type === "run_divider") {
      return (
        <div className="flex items-center gap-3 py-2 my-1">
          <div className="flex-1 h-px bg-border/60" />
          <span className="text-[10px] text-muted-foreground font-medium uppercase tracking-wider">
            {msg.content}
          </span>
          <div className="flex-1 h-px bg-border/60" />
        </div>
      );
    }

    if (msg.type === "system") {
      return (
        <div className="flex justify-center py-1">
          <span className="text-[11px] text-muted-foreground bg-muted/60 px-3 py-1.5 rounded-full">
            {msg.content}
          </span>
        </div>
      );
    }

    if (msg.type === "colony_link") {
      // Rendered when the queen calls create_colony() and the backend
      // emits a COLONY_CREATED event. Gives the user a clickable card
      // that navigates to the new colony page. Clicking also locks the
      // queen DM (mark-colony-spawned) so the user must compact + fork
      // before continuing this conversation.
      let parsed: {
        colony_name?: string;
        is_new?: boolean;
        skill_name?: string;
        href?: string;
      } = {};
      try {
        parsed = JSON.parse(msg.content);
      } catch {
        // ignore — fall through to a plain text render
      }
      const colonyName = parsed.colony_name || "";
      const href = parsed.href || (colonyName ? `/colony/${colonyName}` : "");
      const skillLabel = parsed.skill_name
        ? ` · skill: ${parsed.skill_name}`
        : "";
      const isNewLabel = parsed.is_new === false ? " (updated)" : " (new)";
      return (
        <div className="flex justify-center py-2">
          <Link
            to={href}
            onClick={() => {
              if (colonyName && onColonyLinkClick) {
                onColonyLinkClick(colonyName);
              }
            }}
            className="inline-flex items-center gap-2 text-xs font-medium text-primary bg-primary/10 hover:bg-primary/20 px-4 py-2 rounded-full border border-primary/20 transition-colors"
          >
            <span>🏛️</span>
            <span>
              Colony <strong>{colonyName}</strong>{isNewLabel} ready{skillLabel} — open
            </span>
          </Link>
        </div>
      );
    }

    if (msg.type === "tool_status") {
      return <ToolActivityRow content={msg.content} />;
    }

    if (isUser) {
      return (
        <div className="flex justify-end">
          <div
            className={`max-w-[75%] bg-primary text-primary-foreground text-sm leading-relaxed rounded-2xl rounded-br-md px-4 py-3${msg.queued ? " animate-pulse opacity-80" : ""}`}
          >
            {msg.images && msg.images.length > 0 && (
              <div className="flex flex-wrap gap-2 mb-2">
                {msg.images.map((img, i) => (
                  <img
                    key={i}
                    src={img.image_url.url}
                    alt={`attachment ${i + 1}`}
                    className="max-h-48 max-w-full rounded-lg object-contain"
                  />
                ))}
              </div>
            )}
            {msg.content && (
              <p className="whitespace-pre-wrap break-words">{msg.content}</p>
            )}
            {(msg.queued || msg.createdAt) && (
              <div className="flex justify-end items-center gap-1.5 mt-1 text-[10px] opacity-60">
                {msg.queued && <span>queued</span>}
                {msg.createdAt && <span>{formatMessageTime(msg.createdAt)}</span>}
              </div>
            )}
          </div>
        </div>
      );
    }

    const handleQueenClick = resolvedQueenProfileId
      ? () => openQueenProfile(resolvedQueenProfileId)
      : undefined;
    const handleWorkerClick =
      msg.role === "worker"
        ? () => openColonyWorkers(workerId ?? undefined)
        : undefined;
    const handleAvatarClick = handleQueenClick ?? handleWorkerClick;
    const avatarTitle = handleQueenClick
      ? `View ${msg.agent}'s profile`
      : handleWorkerClick
        ? "Open worker in colony sidebar"
        : undefined;

    return (
      <div className="flex gap-3">
        <div
          className={`flex-shrink-0 ${isQueen ? "w-9 h-9" : "w-7 h-7"} rounded-xl flex items-center justify-center overflow-hidden${handleAvatarClick ? " cursor-pointer hover:opacity-80 transition-opacity" : ""}`}
          style={isQueen && queenAvatarUrl ? undefined : {
            backgroundColor: `${color}18`,
            border: `1.5px solid ${color}35`,
            boxShadow: isQueen ? `0 0 12px ${color}20` : undefined,
          }}
          onClick={handleAvatarClick}
          title={avatarTitle}
        >
          {isQueen ? (
            <QueenAvatarIcon url={queenAvatarUrl ?? null} size={9} />
          ) : (
            <Cpu className="w-3.5 h-3.5" style={{ color }} />
          )}
        </div>
        <div
          className={`flex-1 min-w-0 ${isQueen ? "max-w-[85%]" : "max-w-[75%]"}`}
        >
          <div className="flex items-center gap-2 mb-1">
            <span
              className={`font-medium ${isQueen ? "text-sm" : "text-xs"}${handleQueenClick ? " cursor-pointer hover:underline" : ""}`}
              style={{ color }}
              onClick={handleQueenClick}
            >
              {msg.agent}
            </span>
            {(!isQueen || showQueenPhaseBadge) && (
              <span
                className={`text-[10px] font-medium px-1.5 py-0.5 rounded-md ${
                  isQueen
                    ? "bg-primary/15 text-primary"
                    : "bg-muted text-muted-foreground"
                }`}
              >
                {isQueen
                  ? (msg.phase ?? queenPhase) === "working"
                    ? "working"
                    : (msg.phase ?? queenPhase) === "reviewing"
                      ? "reviewing"
                      : "independent"
                  : "Worker"}
              </span>
            )}
            {msg.createdAt && (
              <span className="text-[10px] text-muted-foreground">
                {formatMessageTime(msg.createdAt)}
              </span>
            )}
          </div>
          <div
            className={`text-sm leading-relaxed rounded-2xl rounded-tl-md px-4 py-3 ${
              isQueen ? "border border-primary/20 bg-primary/5" : "bg-muted/60"
            }`}
          >
            <MarkdownContent content={msg.content} />
          </div>
        </div>
      </div>
    );
  },
  (prev, next) =>
    prev.msg.id === next.msg.id &&
    prev.msg.content === next.msg.content &&
    prev.msg.phase === next.msg.phase &&
    prev.queenPhase === next.queenPhase &&
    prev.showQueenPhaseBadge === next.showQueenPhaseBadge,
);

export default function ChatPanel({
  messages,
  onSend,
  isWaiting,
  isWorkerWaiting,
  isBusy,
  activeThread,
  disabled,
  onCancel,
  pendingQuestion,
  pendingOptions,
  pendingQuestions,
  onQuestionSubmit,
  onMultiQuestionSubmit,
  onQuestionDismiss,
  queenPhase,
  showQueenPhaseBadge = true,
  contextUsage,
  supportsImages = true,
  initialDraft,
  queenProfileId,
  queenId,
  onColonyLinkClick,
  colonySpawned,
  spawnedColonyName,
  queenDisplayName,
  onCompactAndFork,
  compactingAndForking,
}: ChatPanelProps) {
  const [input, setInput] = useState("");
  const [pendingImages, setPendingImages] = useState<ImageContent[]>([]);
  const [readMap, setReadMap] = useState<Record<string, number>>({});
  const bottomRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const stickToBottom = useRef(true);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const lastAppliedDraftRef = useRef<string | null | undefined>(undefined);
  const queenAvatarUrl = queenId ? `/api/queen/${queenId}/avatar` : null;

  useEffect(() => {
    if (!initialDraft || initialDraft === lastAppliedDraftRef.current) return;
    lastAppliedDraftRef.current = initialDraft;
    setInput(initialDraft);
    setTimeout(() => {
      const ta = textareaRef.current;
      if (!ta) return;
      ta.focus();
      ta.style.height = "auto";
      ta.style.height = `${Math.min(ta.scrollHeight, 160)}px`;
      ta.selectionStart = ta.selectionEnd = ta.value.length;
    }, 0);
  }, [initialDraft]);

  const threadMessages = messages.filter((m) => {
    if (m.type === "system" && !m.thread) return false;
    if (m.thread !== activeThread) return false;
    // Hide queen messages whose content is whitespace-only — these are
    // tool-use-only turns that have no visible text.  During live operation
    // tool pills provide context, but on resume the pills are gone so
    // the empty bubble is meaningless.
    if (m.role === "queen" && !m.type && (!m.content || !m.content.trim()))
      return false;
    return true;
  });

  // Group subagent messages into parallel bubbles.
  // A subagent message has nodeId containing ":subagent:".
  // The run only ends on hard boundaries (user messages, run_dividers)
  // so interleaved queen/tool/system messages don't fragment the bubble.
  type RenderItem =
    | { kind: "message"; msg: ChatMessage }
    | { kind: "parallel"; groupId: string; groups: SubagentGroup[] }
    | {
        kind: "worker_run";
        runId: string;
        group: WorkerRunGroup;
        /** Optional short label shown next to the "Worker" badge.
         *  Only set when there are multiple parallel workers in the
         *  same run span (so users can tell them apart). */
        label?: string;
      }
    | { kind: "day_divider"; key: string; createdAt: number };

  /** Derive a short label from a parallel-worker stream id.
   *  `worker:abcdef12-3456-...` → `abcdef12` (first 8 chars of the
   *  uuid after the `worker:` prefix). Falls back to the first
   *  message's nodeId when the streamId isn't the expected shape. */
  function deriveWorkerLabel(
    streamKey: string,
    msgs: ChatMessage[],
  ): string {
    if (streamKey.startsWith("worker:")) {
      const suffix = streamKey.slice("worker:".length);
      // sessions are `session_YYYYMMDD_HHMMSS_<8-hex>` — show the
      // trailing hex if present, else first 8 chars of the suffix.
      const tail = suffix.match(/_[0-9a-f]{6,}$/i)?.[0]?.slice(1);
      return tail ? tail.slice(0, 8) : suffix.slice(0, 8);
    }
    const nid = msgs.find((m) => m.nodeId)?.nodeId;
    return nid || streamKey;
  }

  const renderItems = useMemo<RenderItem[]>(() => {
    const items: RenderItem[] = [];
    let i = 0;
    while (i < threadMessages.length) {
      const msg = threadMessages[i];
      const isSubagent = msg.nodeId?.includes(":subagent:");

      // Worker run grouping: collect consecutive WORKER-role
      // messages (and worker tool_status pills) into a collapsible
      // card. Queen tool_status pills (``role === "queen"``) are
      // deliberately excluded — the queen's own tool calls are part
      // of the queen↔user conversation and should render inline as
      // ToolActivityRows, not fold into a "Worker" bubble. Without
      // this guard, every queen run_command / read_file / etc. shows
      // up under a misleading "Worker" label in the DM.
      const isWorkerCandidate =
        msg.role === "worker" ||
        (msg.type === "tool_status" && msg.role !== "queen");
      if (
        !isSubagent &&
        isWorkerCandidate &&
        msg.type !== "user" &&
        msg.type !== "run_divider"
      ) {
        const workerMsgs: ChatMessage[] = [];
        const firstWorkerMsg = msg;

        while (i < threadMessages.length) {
          const m = threadMessages[i];

          // Hard boundary — stop the worker run group
          if (m.type === "user" || m.type === "run_divider") break;
          // Queen message with real text — boundary (queen is talking
          // to the user, not just emitting a tool)
          if (m.role === "queen" && m.content?.trim() && !m.type) break;
          // Queen tool_status — NOT a worker activity, don't bucket
          // it. Break so the grouping stops and the queen pill
          // renders inline.
          if (m.type === "tool_status" && m.role === "queen") break;
          // Subagent message — different group type, stop here
          if (m.nodeId?.includes(":subagent:")) break;

          // Worker text messages and worker tool_status belong to the run
          if (
            m.role === "worker" ||
            (m.type === "tool_status" && m.role !== "queen")
          ) {
            workerMsgs.push(m);
            i++;
            continue;
          }

          // System message or other — include in the worker run
          // group to preserve ordering (they'll render inside the
          // expanded view)
          workerMsgs.push(m);
          i++;
        }

        if (workerMsgs.length > 0) {
          // Parallel fan-out detection: if any message in this span
          // is tagged with a parallel-worker streamId (``worker:{uuid}``),
          // split the span by streamId and emit one ``worker_run``
          // per worker — they render as stacked independent
          // ``WorkerRunBubble``s. Un-tagged legacy messages and the
          // single-worker ``streamId="worker"`` case fall through to
          // the existing single-bubble behavior.
          const hasParallel = workerMsgs.some(
            (m) => !!m.streamId && /^worker:./.test(m.streamId),
          );

          if (hasParallel) {
            const buckets = new Map<
              string,
              { messages: ChatMessage[]; firstAt: number }
            >();
            // Messages with no streamId (system notes, orphans from
            // old restore) attach to the most-recent keyed message's
            // bucket so chronology is preserved.
            let currentKey: string | null = null;
            for (const m of workerMsgs) {
              const key =
                m.streamId && m.streamId.length > 0
                  ? m.streamId
                  : currentKey;
              if (!key) continue;
              if (m.streamId && m.streamId.length > 0) currentKey = m.streamId;
              let bucket = buckets.get(key);
              if (!bucket) {
                bucket = { messages: [], firstAt: m.createdAt ?? 0 };
                buckets.set(key, bucket);
              }
              bucket.messages.push(m);
              bucket.firstAt = Math.min(
                bucket.firstAt,
                m.createdAt ?? Number.POSITIVE_INFINITY,
              );
            }

            const sorted = Array.from(buckets.entries()).sort(
              ([, a], [, b]) => a.firstAt - b.firstAt,
            );
            for (const [streamKey, { messages: bucketMsgs }] of sorted) {
              items.push({
                kind: "worker_run",
                runId: `wrun-${firstWorkerMsg.id}-${streamKey}`,
                group: { messages: bucketMsgs },
                label: deriveWorkerLabel(streamKey, bucketMsgs),
              });
            }
          } else {
            items.push({
              kind: "worker_run",
              runId: `wrun-${firstWorkerMsg.id}`,
              group: { messages: workerMsgs },
            });
          }
        }
        continue;
      }

      if (!isSubagent) {
        items.push({ kind: "message", msg });
        i++;
        continue;
      }

      // Start a subagent run. Collect all subagent messages, allowing
      // non-subagent messages in between (they render as normal items
      // before the bubble). Only break on hard boundaries.
      const subagentMsgs: ChatMessage[] = [];
      const interleaved: { idx: number; msg: ChatMessage }[] = [];
      const firstId = msg.id;

      while (i < threadMessages.length) {
        const m = threadMessages[i];
        const isSa = m.nodeId?.includes(":subagent:");

        if (isSa) {
          subagentMsgs.push(m);
          i++;
          continue;
        }

        // Hard boundary — stop the run
        if (m.type === "user" || m.type === "run_divider") break;

        // Worker message from a non-subagent node means the graph has
        // moved on to the next stage.  Close the bubble even if some
        // subagents are still streaming in the background.
        if (m.role === "worker" && m.nodeId && !m.nodeId.includes(":subagent:"))
          break;

        // Soft interruption (queen output, system, tool_status without
        // nodeId) — render it normally but keep the subagent run going
        interleaved.push({ idx: items.length + interleaved.length, msg: m });
        i++;
      }

      // Emit interleaved messages first (before the bubble)
      for (const { msg: im } of interleaved) {
        items.push({ kind: "message", msg: im });
      }

      // Build the single parallel bubble from all collected subagent msgs
      if (subagentMsgs.length > 0) {
        const byNode = new Map<string, ChatMessage[]>();
        for (const m of subagentMsgs) {
          const nid = m.nodeId!;
          if (!byNode.has(nid)) byNode.set(nid, []);
          byNode.get(nid)!.push(m);
        }
        const groups: SubagentGroup[] = [];
        for (const [nodeId, msgs] of byNode) {
          groups.push({
            nodeId,
            messages: msgs,
            contextUsage: contextUsage?.[nodeId],
          });
        }
        items.push({ kind: "parallel", groupId: `par-${firstId}`, groups });
      }
    }
    return items;
  }, [threadMessages, contextUsage]);

  // Inject day-separator dividers between items that cross a calendar-day
  // boundary, and one before the very first item. Helps the user see when
  // activity resumed after a gap — important since some answers take hours.
  const itemsWithDividers = useMemo<RenderItem[]>(() => {
    const getTime = (item: RenderItem): number | undefined => {
      if (item.kind === "message") return item.msg.createdAt;
      if (item.kind === "parallel") {
        for (const g of item.groups) {
          for (const m of g.messages) {
            if (m.createdAt) return m.createdAt;
          }
        }
      }
      return undefined;
    };
    const dayKey = (ts: number) => {
      const d = new Date(ts);
      return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
    };
    const out: RenderItem[] = [];
    let lastDay: string | null = null;
    for (const item of renderItems) {
      const ts = getTime(item);
      if (ts) {
        const key = dayKey(ts);
        if (key !== lastDay) {
          out.push({ kind: "day_divider", key: `day-${ts}`, createdAt: ts });
          lastDay = key;
        }
      }
      out.push(item);
    }
    return out;
  }, [renderItems]);

  // Mark current thread as read
  useEffect(() => {
    const count = messages.filter((m) => m.thread === activeThread).length;
    setReadMap((prev) => ({ ...prev, [activeThread]: count }));
  }, [activeThread, messages]);

  // Suppress unused var
  void readMap;

  // Autoscroll: only when user is already near the bottom
  const handleScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    const distFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    stickToBottom.current = distFromBottom < 80;
  };

  useEffect(() => {
    if (stickToBottom.current) {
      bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [threadMessages, pendingQuestion, isWaiting, isWorkerWaiting]);

  // Always start pinned to bottom when switching threads
  useEffect(() => {
    stickToBottom.current = true;
  }, [activeThread]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() && pendingImages.length === 0) return;
    onSend(
      input.trim(),
      activeThread,
      pendingImages.length > 0 ? pendingImages : undefined,
    );
    setInput("");
    setPendingImages([]);
    if (textareaRef.current) textareaRef.current.style.height = "auto";
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? []);
    if (files.length === 0) return;
    files.forEach((file) => {
      const reader = new FileReader();
      reader.onload = (ev) => {
        const url = ev.target?.result as string;
        setPendingImages((prev) => [
          ...prev,
          { type: "image_url", image_url: { url } },
        ]);
      };
      reader.readAsDataURL(file);
    });
    // Reset so the same file can be re-selected
    e.target.value = "";
  };

  return (
    <div className="flex flex-col h-full min-w-0">
      {/* Compact sub-header */}
      <div className="px-5 pt-4 pb-2 flex items-center gap-2">
        <p className="text-[11px] text-muted-foreground font-medium uppercase tracking-wider">
          Conversation
        </p>
      </div>

      {/* Messages */}
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className="flex-1 overflow-auto px-5 py-4 space-y-3"
      >
        {itemsWithDividers.map((item) => {
          if (item.kind === "day_divider") {
            return (
              <div
                key={item.key}
                className="flex items-center gap-3 py-2 my-1"
              >
                <div className="flex-1 h-px bg-border/60" />
                <span className="text-[10px] text-muted-foreground font-medium uppercase tracking-wider">
                  {formatDayDividerLabel(item.createdAt)}
                </span>
                <div className="flex-1 h-px bg-border/60" />
              </div>
            );
          }
          if (item.kind === "parallel") {
            return (
              <div key={item.groupId}>
                <ParallelSubagentBubble
                  groupId={item.groupId}
                  groups={item.groups}
                />
              </div>
            );
          }
          if (item.kind === "worker_run") {
            return (
              <div key={item.runId}>
                <WorkerRunBubble
                  runId={item.runId}
                  group={item.group}
                  label={item.label}
                />
              </div>
            );
          }
          const msg = item.msg;
          // Detect misformatted ask_user payloads emitted as plain text and
          // substitute the nicer widget-based bubble.  Only inspect regular
          // agent messages — skip system rows, tool status, dividers, etc.
          const askPayload =
            (msg.role === "queen" || msg.role === "worker") &&
            !msg.type &&
            msg.content
              ? detectAskUserPayload(msg.content)
              : null;
          if (askPayload) {
            return (
              <div key={msg.id}>
                <InlineAskUserBubble
                  msg={msg}
                  payload={askPayload}
                  activeThread={activeThread}
                  onSend={onSend}
                  queenPhase={queenPhase}
                  showQueenPhaseBadge={showQueenPhaseBadge}
                  queenProfileId={queenProfileId}
                  queenAvatarUrl={queenAvatarUrl}
                />
              </div>
            );
          }
          return (
            <div key={msg.id}>
              <MessageBubble
                msg={msg}
                queenPhase={queenPhase}
                showQueenPhaseBadge={showQueenPhaseBadge}
                queenProfileId={queenProfileId}
                queenAvatarUrl={queenAvatarUrl}
                onColonyLinkClick={onColonyLinkClick}
              />
            </div>
          );
        })}

        {/* Show typing indicator while waiting for first queen response (disabled + empty chat) */}
        {(isWaiting || (disabled && threadMessages.length === 0)) && (
          <div className="flex gap-3">
            <div
              className="flex-shrink-0 w-9 h-9 rounded-xl flex items-center justify-center overflow-hidden"
              style={queenAvatarUrl ? undefined : {
                backgroundColor: `${queenColor}18`,
                border: `1.5px solid ${queenColor}35`,
                boxShadow: `0 0 12px ${queenColor}20`,
              }}
            >
              <QueenAvatarIcon url={queenAvatarUrl} size={9} />
            </div>
            <div className="border border-primary/20 bg-primary/5 rounded-2xl rounded-tl-md px-4 py-3">
              <div className="flex gap-1.5">
                <span
                  className="w-1.5 h-1.5 rounded-full bg-muted-foreground animate-bounce"
                  style={{ animationDelay: "0ms" }}
                />
                <span
                  className="w-1.5 h-1.5 rounded-full bg-muted-foreground animate-bounce"
                  style={{ animationDelay: "150ms" }}
                />
                <span
                  className="w-1.5 h-1.5 rounded-full bg-muted-foreground animate-bounce"
                  style={{ animationDelay: "300ms" }}
                />
              </div>
            </div>
          </div>
        )}
        {isWorkerWaiting && !isWaiting && (
          <div className="flex gap-3">
            <div
              className="flex-shrink-0 w-7 h-7 rounded-xl flex items-center justify-center"
              style={{
                backgroundColor: `${workerColor}18`,
                border: `1.5px solid ${workerColor}35`,
              }}
            >
              <Cpu className="w-3.5 h-3.5" style={{ color: workerColor }} />
            </div>
            <div className="bg-muted/60 rounded-2xl rounded-tl-md px-4 py-3">
              <div className="flex gap-1.5">
                <span
                  className="w-1.5 h-1.5 rounded-full bg-muted-foreground animate-bounce"
                  style={{ animationDelay: "0ms" }}
                />
                <span
                  className="w-1.5 h-1.5 rounded-full bg-muted-foreground animate-bounce"
                  style={{ animationDelay: "150ms" }}
                />
                <span
                  className="w-1.5 h-1.5 rounded-full bg-muted-foreground animate-bounce"
                  style={{ animationDelay: "300ms" }}
                />
              </div>
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Context window usage bar — sits between messages and input */}
      {(() => {
        if (!contextUsage) return null;
        const queenUsage = contextUsage["__queen__"];
        const workerEntries = Object.entries(contextUsage).filter(
          ([k]) => k !== "__queen__",
        );
        const workerUsage =
          workerEntries.length > 0
            ? workerEntries.reduce(
                (best, [, v]) => (v.usagePct > best.usagePct ? v : best),
                workerEntries[0][1],
              )
            : undefined;
        if (!queenUsage && !workerUsage) return null;
        return (
          <div className="flex items-center gap-3 mx-4 px-3 py-1 rounded-lg bg-muted/30 border border-border/20 group/ctx flex-shrink-0">
            {queenUsage && (
              <div
                className="flex items-center gap-2 flex-1 min-w-0"
                title={`Queen: ${(queenUsage.estimatedTokens / 1000).toFixed(1)}k / ${(queenUsage.maxTokens / 1000).toFixed(0)}k tokens \u00b7 ${queenUsage.messageCount} messages`}
              >
                <Crown
                  className="w-3 h-3 flex-shrink-0"
                  style={{ color: "hsl(45,95%,58%)" }}
                />
                <div className="flex-1 h-1.5 rounded-full bg-muted/50 overflow-hidden min-w-[60px]">
                  <div
                    className="h-full rounded-full transition-all duration-500 ease-out"
                    style={{
                      width: `${Math.min(queenUsage.usagePct, 100)}%`,
                      backgroundColor:
                        queenUsage.usagePct >= 90
                          ? "hsl(0,65%,55%)"
                          : queenUsage.usagePct >= 70
                            ? "hsl(35,90%,55%)"
                            : "hsl(45,95%,58%)",
                    }}
                  />
                </div>
                <span className="text-[10px] text-muted-foreground/70 flex-shrink-0 tabular-nums">
                  <span className="group-hover/ctx:hidden">
                    {queenUsage.usagePct}%
                  </span>
                  <span className="hidden group-hover/ctx:inline">
                    {(queenUsage.estimatedTokens / 1000).toFixed(1)}k /{" "}
                    {(queenUsage.maxTokens / 1000).toFixed(0)}k
                  </span>
                </span>
              </div>
            )}
            {workerUsage && (
              <div
                className="flex items-center gap-2 flex-1 min-w-0"
                title={`Worker: ${(workerUsage.estimatedTokens / 1000).toFixed(1)}k / ${(workerUsage.maxTokens / 1000).toFixed(0)}k tokens \u00b7 ${workerUsage.messageCount} messages`}
              >
                <Cpu
                  className="w-3 h-3 flex-shrink-0"
                  style={{ color: "hsl(220,60%,55%)" }}
                />
                <div className="flex-1 h-1.5 rounded-full bg-muted/50 overflow-hidden min-w-[60px]">
                  <div
                    className="h-full rounded-full transition-all duration-500 ease-out"
                    style={{
                      width: `${Math.min(workerUsage.usagePct, 100)}%`,
                      backgroundColor:
                        workerUsage.usagePct >= 90
                          ? "hsl(0,65%,55%)"
                          : workerUsage.usagePct >= 70
                            ? "hsl(35,90%,55%)"
                            : "hsl(220,60%,55%)",
                    }}
                  />
                </div>
                <span className="text-[10px] text-muted-foreground/70 flex-shrink-0 tabular-nums">
                  <span className="group-hover/ctx:hidden">
                    {workerUsage.usagePct}%
                  </span>
                  <span className="hidden group-hover/ctx:inline">
                    {(workerUsage.estimatedTokens / 1000).toFixed(1)}k /{" "}
                    {(workerUsage.maxTokens / 1000).toFixed(0)}k
                  </span>
                </span>
              </div>
            )}
          </div>
        );
      })()}

      {/* Input area — colony-spawned lock replaces everything; question widget
          replaces textarea when a question is pending */}
      {colonySpawned ? (
        <div className="p-4 border-t border-border/50 bg-muted/20">
          <div className="flex flex-col items-center gap-2 text-center">
            <p className="text-xs text-muted-foreground max-w-md">
              This conversation spawned colony{" "}
              {spawnedColonyName ? (
                <strong className="text-foreground">{spawnedColonyName}</strong>
              ) : (
                "a colony"
              )}
              . To keep chatting with{" "}
              {queenDisplayName || "this queen"}, compact this session and start
              a fresh one.
            </p>
            <button
              type="button"
              onClick={onCompactAndFork}
              disabled={!onCompactAndFork || compactingAndForking}
              className="inline-flex items-center gap-2 text-xs font-medium text-primary-foreground bg-primary hover:opacity-90 disabled:opacity-50 disabled:cursor-not-allowed px-4 py-2 rounded-full transition-opacity"
            >
              {compactingAndForking ? (
                <>
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  <span>Compacting…</span>
                </>
              ) : (
                <span>
                  Compact & start new session
                  {queenDisplayName ? ` with ${queenDisplayName}` : ""}
                </span>
              )}
            </button>
          </div>
        </div>
      ) : pendingQuestions &&
      pendingQuestions.length >= 2 &&
      onMultiQuestionSubmit ? (
        <MultiQuestionWidget
          questions={pendingQuestions}
          onSubmit={onMultiQuestionSubmit}
          onDismiss={onQuestionDismiss}
        />
      ) : pendingQuestion && pendingOptions && onQuestionSubmit ? (
        <QuestionWidget
          question={pendingQuestion}
          options={pendingOptions}
          onSubmit={onQuestionSubmit}
          onDismiss={onQuestionDismiss}
        />
      ) : (
        <form onSubmit={handleSubmit} className="p-4">
          {/* Image preview strip */}
          {pendingImages.length > 0 && (
            <div className="flex flex-wrap gap-2 mb-2 px-1">
              {pendingImages.map((img, i) => (
                <div key={i} className="relative group">
                  <img
                    src={img.image_url.url}
                    alt={`preview ${i + 1}`}
                    className="h-16 w-16 object-cover rounded-lg border border-border"
                  />
                  <button
                    type="button"
                    onClick={() =>
                      setPendingImages((prev) => prev.filter((_, j) => j !== i))
                    }
                    className="absolute -top-1.5 -right-1.5 w-4 h-4 rounded-full bg-destructive text-destructive-foreground flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"
                  >
                    <X className="w-2.5 h-2.5" />
                  </button>
                </div>
              ))}
            </div>
          )}
          <div className="flex items-center gap-3 bg-muted/40 rounded-xl px-4 py-2.5 border border-border focus-within:border-primary/40 transition-colors">
            <input
              ref={fileInputRef}
              type="file"
              accept="image/*"
              multiple
              className="hidden"
              onChange={handleFileChange}
            />
            <button
              type="button"
              disabled={disabled || !supportsImages}
              onClick={() => supportsImages && fileInputRef.current?.click()}
              className="flex-shrink-0 p-1 rounded-md text-muted-foreground hover:text-foreground disabled:opacity-30 transition-colors"
              title={supportsImages ? "Attach image" : "Image not supported by the current model"}
            >
              <Paperclip className="w-4 h-4" />
            </button>
            <textarea
              ref={textareaRef}
              rows={1}
              value={input}
              onChange={(e) => {
                setInput(e.target.value);
                const ta = e.target;
                ta.style.height = "auto";
                ta.style.height = `${Math.min(ta.scrollHeight, 160)}px`;
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  handleSubmit(e);
                }
              }}
              placeholder={
                disabled ? "Connecting to agent..." : "Message Queen Bee..."
              }
              disabled={disabled}
              className="flex-1 bg-transparent text-sm text-foreground outline-none placeholder:text-muted-foreground disabled:opacity-50 disabled:cursor-not-allowed resize-none overflow-y-auto"
            />
            {isBusy && onCancel ? (
              <button
                type="button"
                onClick={onCancel}
                className="p-2 rounded-lg bg-amber-500/15 text-amber-400 border border-amber-500/40 hover:bg-amber-500/25 transition-colors"
              >
                <Square className="w-4 h-4" />
              </button>
            ) : (
              <button
                type="submit"
                disabled={
                  (!input.trim() && pendingImages.length === 0) || disabled
                }
                className="p-2 rounded-lg bg-primary text-primary-foreground disabled:opacity-30 hover:opacity-90 transition-opacity"
              >
                <Send className="w-4 h-4" />
              </button>
            )}
          </div>
        </form>
      )}
    </div>
  );
}
