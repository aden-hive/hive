import { memo, useCallback, useState, useRef, useEffect, useLayoutEffect, useMemo } from "react";
import { createPortal } from "react-dom";
import { Link } from "react-router-dom";
import { apiUrl } from "@/api/client";
import { executionApi } from "@/api/execution";
import {
  Send,
  Square,
  Crown,
  Cpu,
  Check,
  Loader2,
  Lock,
  Paperclip,
  X,
  Zap,
  Copy,
  RotateCcw,
  Pencil,
  ThumbsUp,
  ThumbsDown,
  ChevronLeft,
  ChevronRight,
  ArrowDown,
  ZoomIn,
  ZoomOut,
  RotateCw,
  AlertTriangle,
  Ban,
  Download,
  ExternalLink,
  Sparkles,
  Table2,
  Brain,
} from "lucide-react";
import { ReportModal } from "@/components/SessionReportAction";
import {
  printHtmlToPdf,
  openAttachment as openAttachmentInBrowser,
  saveAttachmentAs as saveAttachmentAsDownload,
  copyImageToClipboard as copyImageUrlToClipboard,
} from "@/lib/desktop-shims";

/** Per-message feedback vote. Local-only UI in the OSS web build. */
type Vote = "up" | "down";
import WorkerRunBubble from "@/components/WorkerRunBubble";
import type { WorkerRunGroup } from "@/components/WorkerRunBubble";
import QueenPortraitGlyph from "@/components/QueenPortraitGlyph";
import type { PortraitDescriptor } from "@/api/queens";
import TerminalToolDetail, {
  type TerminalToolEntry,
} from "@/components/TerminalToolDetail";
import ChartToolDetail, {
  type ChartToolEntry,
} from "@/components/charts/ChartToolDetail";
import {
  SkillMarkerText,
} from "@/components/SkillComposer";
import {
  SkillTextEditor,
  type SkillTextEditorHandle,
} from "@/components/SkillTextEditor";

function CopyBtn({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      onClick={() => {
        copyMarkdown(text).catch(() => {});
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      }}
      className="opacity-0 group-hover:opacity-100 p-1 rounded-md text-muted-foreground/50 hover:text-muted-foreground hover:bg-muted/40 transition-all duration-150"
      title="Copy as formatted text (Docs, Slack, email)"
    >
      {copied ? <Check className="w-3 h-3 text-primary" /> : <Copy className="w-3 h-3" />}
    </button>
  );
}

function CopyBtnStatic({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      onClick={() => {
        copyMarkdown(text).catch(() => {});
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      }}
      className="p-1 rounded-md text-muted-foreground/40 hover:text-muted-foreground hover:bg-muted/40 transition-all duration-150"
      title="Copy as formatted text (Docs, Slack, email)"
    >
      {copied ? <Check className="w-3 h-3 text-primary" /> : <Copy className="w-3 h-3" />}
    </button>
  );
}

/**
 * Derive a human-meaningful filename slug from the response itself, so the
 * downloaded PDF is named after what it contains rather than a generic
 * "<queen> response". Prefers the first markdown heading, then the first
 * non-trivial line; strips inline markdown so the slug reads cleanly.
 * Falls back to the queen title and finally "response".
 */
function deriveDownloadSlug(text: string, fallbackTitle: string): string {
  const slugify = (s: string) =>
    s
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 60);

  const lines = text
    .replace(/```[\s\S]*?```/g, "") // drop fenced code blocks
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean);

  // First markdown heading wins; otherwise first line with real words.
  const heading = lines.find((l) => /^#{1,6}\s+/.test(l));
  const candidate = heading ?? lines.find((l) => /[a-z0-9]/i.test(l));

  const cleaned = (candidate ?? "")
    .replace(/^#{1,6}\s+/, "") // strip heading markers
    .replace(/[*_`>~]/g, "") // strip inline markdown emphasis
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1"); // links → label text

  return slugify(cleaned) || slugify(fallbackTitle) || "response";
}

function DownloadPdfBtn({ text, title }: { text: string; title: string }) {
  const [saving, setSaving] = useState(false);
  const handleClick = async () => {
    if (saving || !text.trim()) return;
    setSaving(true);
    try {
      const html = buildPrintableHtml(text, {
        title,
        meta: new Date().toLocaleString(),
      });
      // Suggested filename: derived from the response content, capped to a
      // reasonable length, falling back to the queen title.
      const result = printHtmlToPdf(html);
      if (!result.ok && !result.cancelled) {
        console.error("[savePdf] failed", result.error);
      }
    } catch (err) {
      console.error("[savePdf] threw", err);
    } finally {
      setSaving(false);
    }
  };
  return (
    <button
      onClick={handleClick}
      disabled={saving}
      className="p-1 rounded-md text-muted-foreground/40 hover:text-muted-foreground hover:bg-muted/40 transition-all duration-150 disabled:opacity-50"
      title="Download as PDF"
    >
      <Download className="w-3 h-3" />
    </button>
  );
}

type FeedbackStatus = "idle" | "saved" | "cleared" | "error";

function FeedbackBtns({
  messageId,
  sessionId,
  initialVote,
  onStatusChange,
}: {
  messageId?: string;
  /** Backend session id. When null/undefined the buttons stay
   *  fully functional as local UI but skip the network call —
   *  preserves the warm-up / offline experience. */
  sessionId?: string | null;
  initialVote?: Vote | null;
  /** Notify a parent when a vote round-trip resolves, so the parent
   *  can render the confirmation message wherever it wants in the
   *  action row (e.g. *after* the download button). */
  onStatusChange?: (status: Exclude<FeedbackStatus, "idle">) => void;
}) {
  const [vote, setVote] = useState<Vote | null>(initialVote ?? null);
  // After a down-vote lands, offer to send diagnostics; the modal mounts on confirm.
  const [askDiag, setAskDiag] = useState(false);
  const [diagOpen, setDiagOpen] = useState(false);
  // Hydrate from the parent map when it lands (the bulk list is fetched
  // async on session load).
  useEffect(() => {
    setVote(initialVote ?? null);
  }, [initialVote]);

  const cast = async (next: Vote | null) => {
    setVote(next);
    if (!messageId || !sessionId) return;
    // Feedback votes are local-only UI now (the cloud feedback store was
    // removed). A down-vote still offers diagnostics.
    if (next === "down") {
      setAskDiag(true);
    } else {
      setAskDiag(false);
      onStatusChange?.(next === null ? "cleared" : "saved");
    }
  };

  return (
    <>
      <button
        onClick={() => cast(vote === "up" ? null : "up")}
        className={`p-1 rounded-md transition-all duration-150 ${
          vote === "up"
            ? "text-primary bg-primary/10"
            : "text-muted-foreground/40 hover:text-muted-foreground hover:bg-muted/40"
        }`}
        title="Good response"
      >
        <ThumbsUp className="w-3 h-3" />
      </button>
      <button
        onClick={() => cast(vote === "down" ? null : "down")}
        className={`p-1 rounded-md transition-all duration-150 ${
          vote === "down"
            ? "text-destructive bg-destructive/10"
            : "text-muted-foreground/40 hover:text-muted-foreground hover:bg-muted/40"
        }`}
        title="Poor response"
      >
        <ThumbsDown className="w-3 h-3" />
      </button>
      {askDiag && sessionId && (
        <span className="flex items-center gap-1.5 ml-1.5 text-[11px] text-muted-foreground">
          Send diagnostics to help us fix this?
          <button
            onClick={() => { setAskDiag(false); setDiagOpen(true); }}
            className="text-primary font-medium hover:underline"
          >
            Send
          </button>
          <button onClick={() => setAskDiag(false)} className="hover:underline">
            No thanks
          </button>
        </span>
      )}
      {diagOpen && sessionId && (
        <ReportModal
          sessionId={sessionId}
          title="Send diagnostic data"
          subtitle="Helps us debug this response — sends this session's data."
          initialDescription="Flagged via 👎 on a response."
          onClose={() => setDiagOpen(false)}
        />
      )}
    </>
  );
}

/** Queen-side action row: copy → thumbs → download → confirmation chip.
 *  Owns the feedback round-trip status so the confirmation can sit AFTER
 *  the download button (not wedged between thumbs-down and download). */
function QueenMessageActions({
  content,
  messageId,
  sessionId,
  initialVote,
  queenTitle,
}: {
  content: string;
  messageId?: string;
  sessionId?: string | null;
  initialVote?: Vote | null;
  queenTitle?: string;
}) {
  const [status, setStatus] = useState<FeedbackStatus>("idle");
  return (
    <div className="flex items-center gap-0.5 mt-1">
      <CopyBtnStatic text={content} />
      <FeedbackBtns
        messageId={messageId}
        sessionId={sessionId}
        initialVote={initialVote}
        onStatusChange={setStatus}
      />
      <DownloadPdfBtn
        text={content}
        title={queenTitle ? `${queenTitle} response` : "Queen response"}
      />
      <FeedbackStatusMessage status={status} onClear={() => setStatus("idle")} />
    </div>
  );
}

/** Inline confirmation chip rendered after the Download button, fed by
 *  FeedbackBtns' onStatusChange callback. Auto-dismisses after ~4s. */
function FeedbackStatusMessage({
  status,
  onClear,
}: {
  status: FeedbackStatus;
  onClear: () => void;
}) {
  useEffect(() => {
    if (status === "idle") return;
    const t = setTimeout(onClear, 4000);
    return () => clearTimeout(t);
  }, [status, onClear]);

  if (status === "idle") return null;

  const message =
    status === "saved"
      ? "Thank you, we've logged this for future answer improvement"
      : status === "cleared"
        ? "Feedback cleared."
        : "Couldn't save feedback — please try again.";
  const tone = status === "error" ? "text-destructive" : "text-muted-foreground";

  return (
    <span
      role="status"
      aria-live="polite"
      className={`ml-1.5 text-[10.5px] leading-none ${tone} transition-opacity duration-150`}
    >
      {message}
    </span>
  );
}

export interface ImageContent {
  type: "image_url";
  image_url: { url: string };
  /** Original filename — used for file preview chips. */
  _fileName?: string;
  /** Full-resolution data URL for lightbox display. */
  _originalUrl?: string;
  /** Raw File object for files (PDF/CSV) — uploaded via multipart on submit;
   * the chat call then references the saved file with `hive-attachment://`. */
  _file?: File;
  /** Eagerly-read bytes — avoids macOS revoking file access between pick and submit. */
  _bytes?: ArrayBuffer;
  /** Extracted text content for preview (CSV tables, PDF text). */
  _extractedText?: string;
  /** Original byte size — used to enforce per-message upload caps. */
  _byteSize?: number;
  /** Credits this image cost to generate (set for image_generate output). */
  _credits?: number;
  /** True when this is a queen-generated image (image_generate output) — renders
   * as a confident "Generated image" card instead of a plain attachment chip. */
  _generated?: boolean;
}

export interface ContextUsageEntry {
  usagePct: number;
  messageCount: number;
  estimatedTokens: number;
  maxTokens: number;
}

const MB = 1024 * 1024;
const UPLOAD_LIMITS = {
  // 100 MB across PDF/CSV/text. Context cost is bounded regardless of file
  // size — handle_chat inlines only a bounded excerpt (per-page text for
  // small PDFs, first 200 rows for CSV, head-only for large text) and the
  // agent reads the rest from disk. The runtime streams the parse/preview,
  // so no memory spike either.
  pdfMaxBytes: 100 * MB,
  csvMaxBytes: 100 * MB,
  textMaxBytes: 100 * MB,
  imageMaxBytes: 10 * MB,
  // Any other type (docx, xlsx, archives, ...) uploads as-is; the runtime
  // saves it to the session's attachments dir and tells the agent to read
  // it with terminal tools — nothing is inlined, so context cost is nil.
  fileMaxBytes: 100 * MB,
  maxAttachments: 5,
  // Combined cap must clear a single max-size attachment (PDF or CSV);
  // otherwise the per-file check passes and the batch-total check rejects
  // the same file.
  maxTotalBytes: 120 * MB,
} as const;

// Text-shaped extensions accepted as "text" attachments. Mirrors the
// runtime's shared TEXT_EXT_TO_MIME allowlist (aden_tools.utils.attachments)
// minus `.csv` (its own kind) and `.svg` (rides the image/* path) —
// handle_chat drops attachment refs whose extension it doesn't know, so
// keep the two lists in sync.
const TEXT_FILE_EXTENSIONS = [
  ".txt", ".md", ".tsv", ".json", ".jsonl", ".yaml", ".yml", ".toml",
  ".xml", ".html", ".htm", ".css", ".scss", ".js", ".mjs", ".ts", ".tsx",
  ".jsx", ".py", ".rb", ".go", ".rs", ".java", ".kt", ".swift", ".c",
  ".cpp", ".cc", ".h", ".hpp", ".cs", ".sh", ".bash", ".zsh", ".fish",
  ".sql", ".ini", ".cfg", ".conf", ".log", ".rst", ".tex",
] as const;
const TEXT_FILE_EXT_RE = new RegExp(
  `\\.(${TEXT_FILE_EXTENSIONS.map((e) => e.slice(1)).join("|")})(\\?|$)`,
  "i",
);
const FILE_INPUT_ACCEPT = [
  "image/*",
  "application/pdf",
  ".pdf",
  ".csv",
  "text/csv",
  ...TEXT_FILE_EXTENSIONS,
].join(",");

function formatBytes(n: number): string {
  if (n >= MB) return `${(n / MB).toFixed(1)} MB`;
  if (n >= 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${n} B`;
}

/**
 * Strip <system-reminder>...</system-reminder> blocks from displayed message
 * text. The runtime injects framework-level reminders (e.g. the attachments
 * directory listing for uploaded PDFs) inline in the user message body so
 * the LLM reads them as instructions. The chat UI hides them — the human
 * shouldn't see their own message bloated with framework metadata.
 *
 * `s` flag so the block can span newlines. Multiple blocks per message
 * are stripped greedily; trailing whitespace from removed blocks is
 * collapsed so the bubble doesn't render a dangling blank trail.
 */
function stripSystemReminders(content: string | undefined): string {
  if (!content) return content ?? "";
  return content
    .replace(/<system-reminder>[\s\S]*?<\/system-reminder>/g, "")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

/**
 * Decide whether an image_url URL points at an image (renderable as a
 * thumbnail) vs. a non-image attachment (PDF, CSV, etc). Used by the
 * unified attachment chip so all attachment types share one card shape.
 */
function isImageAttachment(url: string): boolean {
  if (url.startsWith("data:image/")) return true;
  if (url.startsWith("data:application/pdf")) return false;
  if (url.startsWith("hive-attachment://")) {
    return /\.(png|jpe?g|webp|gif|svg)$/i.test(url);
  }
  // attachment-served URLs end with the filename — sniff by extension.
  return /\.(png|jpe?g|webp|gif|svg)(\?|$)/i.test(url);
}

/**
 * Turn an attachment URL into something the browser can fetch.
 *
 * Canonical attachment refs come through as `hive-attachment://<rel_path>`
 * (the runtime's scheme for "file on disk under the session dir"). The
 * route at /api/sessions/{sid}/attachment/{basename} serves the bytes;
 * this resolver maps the canonical ref → fetchable URL. Layer F2 made
 * `hive-attachment://` the single canonical form everywhere — submit,
 * replay, persistence — so the route-URL shape lives only here.
 *
 * Pass-through for everything else: data: URIs, already-resolved API
 * URLs (legacy persisted messages), absolute http(s) URLs.
 */
function resolveAttachmentUrl(url: string, sessionId: string): string {
  if (!url || !url.startsWith("hive-attachment://")) return url;
  const relPath = url.slice("hive-attachment://".length).replace(/^\/+/, "");
  // Route accepts a basename only — its path-traversal guard rejects
  // slashes, and the path-param matcher won't match across slashes
  // anyway. Both `data/attachments/X` (post-D1) and `attachments/X`
  // (legacy) resolve via basename. encodeURIComponent because filenames
  // now preserve the user's original name (e.g. "Calculus Volume 1.pdf"
  // with spaces) instead of being normalized to `{ts}_{idx}.{ext}`.
  const basename = relPath.split("/").pop() ?? relPath;
  return apiUrl(`/sessions/${sessionId}/attachment/${encodeURIComponent(basename)}`);
}

/**
 * Unified attachment chip — one shape for every attachment type.
 * Images get a small thumbnail in the icon slot; PDFs/CSVs get a
 * doc icon. Filename + optional size meta sit alongside.
 *
 * Two visual variants:
 *   - `pending`: muted/border styling for the composer's preview strip
 *   - `history`: high-contrast on the primary bubble background
 */
function AttachmentChip({
  url,
  fileName,
  byteSize,
  isUploading,
  onClick,
  variant,
  sessionId,
  credits,
}: {
  url: string;
  fileName?: string;
  byteSize?: number;
  isUploading?: boolean;
  onClick?: () => void;
  variant: "pending" | "history";
  /** Needed so `hive-attachment://` canonical refs can be resolved to a
   * fetchable /api/sessions/{sid}/attachment/{basename} URL at render time. */
  sessionId?: string;
  /** Per-image credit cost (generated images) — rendered as a small badge. */
  credits?: number;
}) {
  const [openError, setOpenError] = useState<string | null>(null);
  const isImage = isImageAttachment(url) && url !== "file-pending" && url !== "file-uploaded";
  const showThumbPreview = isImage && url.startsWith("data:image/");
  const displayName = fileName || (isImage ? "image" : "document");
  const sizeText = byteSize !== undefined ? formatBytes(byteSize) : undefined;
  const variantClasses =
    variant === "pending"
      ? "border-border bg-muted/40 text-foreground hover:bg-muted/60"
      : "border-black/20 bg-black/10 text-black hover:bg-black/20";
  // Resolve canonical hive-attachment:// refs to fetchable route URLs.
  // For data: URIs and already-resolved API URLs this is a pass-through.
  const fetchableUrl = sessionId ? resolveAttachmentUrl(url, sessionId) : url;
  // A still-unresolved `hive-attachment://` ref can never load in an <img>:
  // the scheme has no protocol handler and CSP refuses it. This happens
  // transiently when sessionId is null mid-reload (loadSession resets it);
  // render the icon fallback until sessionId populates and we re-render.
  const isResolvable = !fetchableUrl.startsWith("hive-attachment://");

  // Click semantics:
  //   - image: defer to the parent's onClick (typically opens the
  //     ImageCarouselModal lightbox).
  //   - non-image (PDF, yaml, zip, docx, mp3, anything): open the runtime
  //     attachment URL in a new browser tab (the shim's openAttachment),
  //     which the runtime serves with the right content type so the browser
  //     previews or downloads it.
  const handleClick = () => {
    if (isImage && onClick) {
      onClick();
      return;
    }
    if (fetchableUrl && !fetchableUrl.startsWith("file-") && !fetchableUrl.startsWith("hive-attachment://")) {
      setOpenError(null);
      const res = openAttachmentInBrowser(fetchableUrl);
      if (res.ok === false) {
        setOpenError(res.error || "Couldn't open file");
        console.error("[openAttachment] failed", res.error, fetchableUrl);
      }
      return;
    }
    // Unresolved `hive-attachment://` (sessionId not yet populated) or a
    // non-image with no other target: surface it rather than silently
    // no-op'ing into the image lightbox.
    if (!isImage && fetchableUrl.startsWith("hive-attachment://")) {
      setOpenError("Still loading — try again in a moment");
      return;
    }
    if (onClick) onClick();
  };

  // Enable the button whenever we have a workable click target —
  // either a parent-supplied onClick, or a fetchable URL we can
  // open in a new tab. Previously only the parent onClick mattered,
  // which left non-image assistant chips inert.
  const hasOpenable = !!fetchableUrl && !fetchableUrl.startsWith("file-");
  return (
    <button
      type="button"
      onClick={handleClick}
      disabled={isUploading || (!onClick && !hasOpenable)}
      className={`flex items-center gap-2 h-14 pl-1.5 pr-3 rounded-lg border text-xs transition-colors disabled:cursor-default ${variantClasses}`}
    >
      <div className="relative w-11 h-11 flex-shrink-0">
        {showThumbPreview ? (
          <img
            src={fetchableUrl}
            alt=""
            className="w-11 h-11 object-cover rounded"
          />
        ) : isImage && isResolvable ? (
          // Image referenced by URL (server-served attachment). Render as
          // a thumbnail too, but fall back to a generic icon if the URL
          // can't be fetched (broken on `<img>` errors).
          <img
            src={fetchableUrl}
            alt=""
            className="w-11 h-11 object-cover rounded"
            onError={(e) => {
              e.currentTarget.style.display = "none";
            }}
          />
        ) : (
          <div className="w-11 h-11 flex items-center justify-center rounded bg-red-500/15">
            <svg
              className="w-5 h-5 text-red-500"
              viewBox="0 0 24 24"
              fill="currentColor"
            >
              <path d="M6 2a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6H6zm7 1.5L18.5 9H13V3.5z" />
            </svg>
          </div>
        )}
        {isUploading && (
          <div className="absolute inset-0 flex items-center justify-center rounded bg-background/70 backdrop-blur-[1px]">
            <Loader2 className="w-3.5 h-3.5 animate-spin text-primary" />
          </div>
        )}
      </div>
      <div className="flex flex-col min-w-0 items-start text-left">
        <span className="truncate max-w-[140px] leading-tight">{displayName}</span>
        {sizeText && (
          <span className="opacity-60 text-[10px] leading-tight">{sizeText}</span>
        )}
        {credits !== undefined && credits > 0 && (
          <span
            className="text-[10px] leading-tight font-medium text-amber-600 dark:text-amber-400"
            title="Credits used to generate this image"
          >
            ≈ {credits >= 1 ? Math.round(credits) : credits.toFixed(2)} credits
          </span>
        )}
        {openError && (
          <span
            className="text-[10px] leading-tight font-medium text-red-600 dark:text-red-400 truncate max-w-[140px]"
            title={openError}
          >
            {openError}
          </span>
        )}
      </div>
    </button>
  );
}

/** Confident presentation for a queen-GENERATED image (image_generate output)
 * — a credit-costing asset, so it gets a real preview card with a "Generated
 * image" label, its credit cost, and inline save/copy/open actions, rather than
 * the small attachment chip used for user-supplied files. */
function GeneratedImageCard({
  url,
  fileName,
  credits,
  sessionId,
  onClick,
}: {
  url: string;
  fileName?: string;
  credits?: number;
  sessionId?: string;
  onClick?: () => void;
}) {
  const [copied, setCopied] = useState(false);
  // Resolve canonical hive-attachment:// refs to fetchable URLs (same as the
  // chip). Until sessionId is known the ref can't load — show a spinner.
  const fetchableUrl = sessionId ? resolveAttachmentUrl(url, sessionId) : url;
  const isResolvable = !fetchableUrl.startsWith("hive-attachment://");
  const stop =
    (fn: () => void) =>
    (e: React.MouseEvent) => {
      e.stopPropagation();
      fn();
    };
  const iconBtn =
    "p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/60 transition-colors";

  return (
    <div className="w-64 max-w-full rounded-xl border border-border/60 bg-card overflow-hidden shadow-sm">
      <button
        type="button"
        onClick={onClick}
        className="block w-full cursor-zoom-in"
        title="View full size"
      >
        {isResolvable ? (
          <img
            src={fetchableUrl}
            alt={fileName || "Generated image"}
            className="w-full max-h-60 object-cover bg-muted"
            onError={(e) => {
              e.currentTarget.style.display = "none";
            }}
          />
        ) : (
          <div className="w-full h-40 flex items-center justify-center bg-muted">
            <Loader2 className="w-5 h-5 animate-spin text-muted-foreground" />
          </div>
        )}
      </button>
      <div className="flex items-center justify-between gap-2 px-2.5 py-2 border-t border-border/40">
        <div className="flex items-center gap-1.5 min-w-0">
          <Sparkles className="w-3.5 h-3.5 text-primary flex-shrink-0" />
          <span className="text-[11px] font-medium text-foreground/90 truncate">
            Generated image
          </span>
          {credits !== undefined && credits > 0 && (
            <span
              className="text-[10px] font-medium text-amber-600 dark:text-amber-400 whitespace-nowrap"
              title="Credits this image cost"
            >
              · {credits >= 1 ? Math.round(credits) : credits.toFixed(2)} credits
            </span>
          )}
        </div>
        <div className="flex items-center gap-0.5 flex-shrink-0">
          <button
            onClick={stop(() => {
              void copyImageUrlToClipboard(fetchableUrl).then((r) => {
                if (r.ok) {
                  setCopied(true);
                  setTimeout(() => setCopied(false), 1500);
                }
              });
            })}
            className={iconBtn}
            title="Copy image to clipboard"
          >
            {copied ? (
              <Check className="w-3.5 h-3.5 text-primary" />
            ) : (
              <Copy className="w-3.5 h-3.5" />
            )}
          </button>
          <button
            onClick={stop(() => {
              saveAttachmentAsDownload(fetchableUrl, fileName);
            })}
            className={iconBtn}
            title="Save as…"
          >
            <Download className="w-3.5 h-3.5" />
          </button>
          <button
            onClick={stop(() => {
              openAttachmentInBrowser(fetchableUrl);
            })}
            className={iconBtn}
            title="Open with default app"
          >
            <ExternalLink className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>
    </div>
  );
}

type AttachmentKind = "pdf" | "csv" | "text" | "image" | "file";

function classifyAttachment(file: File): AttachmentKind {
  const name = file.name.toLowerCase();
  if (file.type === "application/pdf" || name.endsWith(".pdf")) return "pdf";
  if (file.type === "text/csv" || name.endsWith(".csv")) return "csv";
  // image/* before the text list so `.svg` (image/svg+xml) rides the
  // data-URI image path — the runtime's text allowlist excludes it too.
  if (file.type.startsWith("image/")) return "image";
  if (TEXT_FILE_EXT_RE.test(name)) return "text";
  // Everything else (docx, xlsx, archives, ...) uploads as a generic file:
  // saved to the session's attachments dir, referenced by path, read by
  // the agent with terminal tools. No type is rejected.
  return "file";
}

/** Returns null if the file is acceptable, or a human-readable error string. */
function checkAttachmentSize(file: File, kind: AttachmentKind): string | null {
  const cap =
    kind === "pdf"
      ? UPLOAD_LIMITS.pdfMaxBytes
      : kind === "csv"
        ? UPLOAD_LIMITS.csvMaxBytes
        : kind === "text"
          ? UPLOAD_LIMITS.textMaxBytes
          : kind === "image"
            ? UPLOAD_LIMITS.imageMaxBytes
            : UPLOAD_LIMITS.fileMaxBytes;
  if (file.size > cap) {
    return `${file.name} is ${formatBytes(file.size)} — ${kind.toUpperCase()} limit is ${formatBytes(cap)}.`;
  }
  return null;
}
import MarkdownContent from "@/components/MarkdownContent";
import { copyMarkdown } from "@/lib/copy-markdown";
import { resolvePlaceholders, collectPlaceholderValues, cachePlaceholderValues } from "@/lib/placeholders";
import { buildPrintableHtml } from "@/lib/markdown-to-print";
import QuestionWidget from "@/components/QuestionWidget";
import MultiQuestionWidget from "@/components/MultiQuestionWidget";
import { useQueenProfile } from "@/context/QueenProfileContext";
import { useColonyWorkers } from "@/context/ColonyWorkersContext";
import { useColony } from "@/context/ColonyContext";
import ParallelSubagentBubble, {
  type SubagentGroup,
} from "@/components/ParallelSubagentBubble";
import {
  formatMessageTime,
  formatDayDividerLabel,
  workerIdFromStreamId,
} from "@/lib/chat-helpers";
import { useLazyHistoryWindow } from "@/components/useLazyHistoryWindow";
import { msgSummary, trace as traceLoad } from "@/lib/session-load-trace";

type QueenPhase = "independent" | "colony";

export interface ChatMessage {
  id: string;
  agent: string;
  agentColor: string;
  content: string;
  timestamp: string;
  /** Attachment URLs in this message resolve against THIS session id
   * (set on messages restored from a predecessor session after a
   * cold-resume — their files live under the old id's directory, and
   * resolving against the live session id 404s → invisible images). */
  attachmentSessionId?: string;
  type?:
    | "system"
    | "agent"
    | "user"
    | "tool_status"
    | "worker_input_request"
    | "run_divider"
    | "colony_link"
    | "inherited_block"
    | "trigger"
    | "reasoning";
  role?: "queen" | "worker";
  /** Which worker thread this message belongs to (worker agent name) */
  thread?: string;
  /** Epoch ms when this message was first created — used for ordering queen/worker interleaving */
  createdAt?: number;
  /** Queen phase active when this message was created */
  phase?: QueenPhase;
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
  /** For a merged queen bubble that spans multiple inner-turns (separate LLM
   *  calls within one iteration), the individual text spans in order. When
   *  present (2+ entries) the bubble renders each span as its own block with a
   *  1.5x-paragraph gap between them; `content` holds the same spans joined by
   *  blank lines for copy/print/plain-text. */
  innerTurns?: string[];
  /** Parallel to `innerTurns`: epoch-ms when each span's inner turn began.
   *  Used for the hover tooltip on each timeline node. */
  innerTurnTimes?: number[];
  /** Hidden full text for optimistic-user reconciliation. The bubble shows
   *  `content` (short, e.g. "[document.pdf]"), but the server's echoed
   *  user message carries the full prompt the queen received. The reconciler
   *  matches on this field too so the optimistic bubble — including its
   *  PDF/CSV chip — survives the server echo. */
  _reconcileContent?: string;
  /** Correlation id from the backend's client_input_received event. The
   *  later client_input_committed event (emitted when the message is actually
   *  drained into the conversation) carries the same id, letting us re-stamp
   *  this bubble's createdAt to the true injection time — so a steered/queued
   *  message sorts after the in-flight turn that was streaming when it was
   *  sent, instead of at receive time. */
  correlationId?: string;
}

interface ChatPanelProps {
  messages: ChatMessage[];
  onSend: (message: string, thread: string, images?: ImageContent[], displayMessage?: string, displayImages?: ImageContent[]) => void;
  isWaiting?: boolean;
  /** When true the queen is busy (typing or streaming) — shows the stop button */
  isBusy?: boolean;
  /** When true the colony has active work (queen busy OR workers running).
   *  Controls the kill-switch stop button independently of isBusy so it
   *  stays visible even when only workers are running. */
  colonyActive?: boolean;
  activeThread: string;
  /** When true, the input is disabled (e.g. during loading) */
  disabled?: boolean;
  /** When true, only the send button is locked — the textarea stays typable.
   *  Used during new-session bootstrap so the user can compose a follow-up
   *  while the queen finishes warming up / streaming her first reply. */
  sendLocked?: boolean;
  /** When true, the send button is replaced with a lock icon and clicking
   *  it fires `onPaymentLockedSend` (which the parent uses to re-open the
   *  upgrade popup) instead of sending. The textarea stays typable so the
   *  user's prompt is preserved across the popup interaction. */
  paymentLocked?: boolean;
  /** Called when the user clicks the lock-icon send button while
   *  `paymentLocked` is true. Parent should re-open the payment modal. */
  onPaymentLockedSend?: () => void;
  /** When false, the image attach button is hidden (model lacks vision support) */
  supportsImages?: boolean;
  /** Session ID — needed for uploading PDF attachments. */
  sessionId?: string | null;
  /** Grouped history sessions by day — rendered as collapsible rows at the top. */
  historyTimeline?: Array<{ key: string; label: string; sessions: Array<{ session_id: string; created_at: number; last_message?: string | null; live?: boolean }> }>;
  /** Which history days are expanded. */
  expandedHistoryDays?: Set<string>;
  /** Toggle a history day open/closed. */
  onToggleHistoryDay?: (dayKey: string) => void;
  /** Switch the active session to a historical one. Kept for callers that
   *  want a hard "open this session" affordance; the inline-expansion path
   *  uses `onToggleHistorySession` instead. */
  onSelectHistorySession?: (sessionId: string) => void;
  /** Sessions whose content is expanded inline under the history-timeline
   *  row. Lets users peek at an old session without leaving the active one. */
  expandedHistorySessions?: Set<string>;
  /** Toggle a history session's inline content open/closed. */
  onToggleHistorySession?: (sessionId: string) => void;
  /** Cached messages for sessions in `expandedHistorySessions`, keyed by
   *  session id. Owner fetches `eventsHistory(sid)` on first expand and
   *  passes the replayed message list through. */
  historySessionMessages?: Record<string, ChatMessage[]>;
  /** True while the CURRENT session still has older event pages on disk not
   *  yet fetched. Drives the scroll-up infinite-scroll step before the
   *  previous-session cascade. */
  currentSessionHasMoreOlder?: boolean;
  /** Fetch the current session's next older page (prepends to the
   *  transcript). Awaited by the window so it can serialize page loads. */
  onFetchOlderPage?: () => Promise<void> | void;
  /** For an expanded history session, whether it still has older pages on
   *  disk. Lets the cascade page each previous session fully before revealing
   *  the next older one. */
  historySessionHasMoreOlder?: (sessionId: string) => boolean;
  /** Fetch the next older page of an already-expanded history session. */
  onFetchOlderPageForSession?: (sessionId: string) => Promise<void> | void;
  /** Called when user clicks the stop button to cancel the queen's current turn */
  onCancel?: () => void;
  /** Called when the user steers a queued message into the current turn —
   *  the message is sent to the backend immediately so it influences the
   *  agent after the next tool call completes. */
  onSteer?: (messageId: string) => void;
  /** Called when the user cancels a still-queued (not-yet-sent) message. */
  onCancelQueued?: (messageId: string) => void;
  /** Pending questions from ask_user. A single-entry list renders
   *  QuestionWidget; 2+ entries render MultiQuestionWidget; a single
   *  entry with no options falls through to the normal text input so
   *  the user can type a free-form reply. */
  pendingQuestions?:
    | { id: string; prompt: string; options?: string[] }[]
    | null;
  /** Called when the user answers pending questions. Keys are question
   *  ids, values are the chosen/typed answer. Called for both single
   *  and multi-question flows. */
  onQuestionSubmit?: (answers: Record<string, string>) => void;
  /** Called when user dismisses the pending question without answering */
  onQuestionDismiss?: () => void;
  /** Queen operating phase — shown as a tag on queen messages */
  queenPhase?: QueenPhase;
  /** When false, queen messages omit the phase badge */
  showQueenPhaseBadge?: boolean;
  /** Queen's business function title (e.g. "Head of Technology") — shown
   *  as the badge label instead of the raw phase name when provided. */
  queenTitle?: string;
  /** Context window usage for queen and workers */
  contextUsage?: Record<string, ContextUsageEntry>;
  /** One-shot composer prefill. Applied to the textarea whenever the value changes. */
  initialDraft?: string | null;
  /** Files staged on another screen (which had no session to upload into) and
   *  handed over to be attached here. Ingested through the same validation the
   *  picker uses, so a handed-over file is subject to every rule a picked one
   *  is. Applied once per array identity. */
  initialAttachments?: File[] | null;
  /** Send the prefilled draft automatically, without waiting for the user to
   *  press Enter. The value is a one-shot token: a change means "this is a new
   *  handoff, send it once". Null/undefined — every normal chat — never
   *  auto-sends, which is what keeps this from firing messages on its own. */
  autoSendToken?: number | null;
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
  /** Portrait to render for the queen's avatars, overriding the runtime
   *  profile lookup. Set by the DM page to the user's onboarding-chosen lead
   *  persona so the face matches the (preference-sourced) display name even
   *  before the runtime profile patch lands — otherwise a freshly re-led queen
   *  shows the new name over the old persona's portrait. */
  queenPortraitOverride?: PortraitDescriptor | null;
  /** Called when the user clicks the locked-state button. Should compact
   *  the current session and navigate to the new one. */
  onCompactAndFork?: () => void;
  /** When true, disable the compact-and-fork button (request in flight). */
  compactingAndForking?: boolean;
  /** Called when the user clicks "Start new session" on the locked view.
   *  Should create a fresh session for the same queen without compacting. */
  onStartNewSession?: () => void;
  /** When true, disable the start-new-session button (request in flight). */
  startingNewSession?: boolean;
  /** Cumulative LLM usage for this session.
   *  `cached` (cache reads) and `cacheCreated` (cache writes) are subsets of
   *  `input` — providers count both inside prompt_tokens. Display them
   *  separately; do not add to a total.
   *  `credits` is the Hive credit cost summed across requests. ``null`` means
   *  no request in this session reported credits (pre-hive-aliased turns or
   *  direct provider models) — distinguished from zero on purpose.
   *  `requests` counts how many `llm_turn_complete` events have been merged. */
  tokenUsage?: {
    input: number;
    output: number;
    cached?: number;
    cacheCreated?: number;
    costUsd?: number;
    credits?: number | null;
    requests?: number;
  };
  /** Optional action element rendered on the right side of the "Conversation" header */
  headerAction?: React.ReactNode;
  /** SSE connection state surfaced from the parent. ``"reconnecting"``
   * shows an inline pill so the user knows the silence is the network,
   * not the queen. ``"closed"`` is terminal and rare. */
  sseState?: "live" | "reconnecting" | "closed";
  /** Wall-clock millis of the most recent SSE event arrival. The header
   * shows "last activity Xs ago" derived from this; combined with
   * ``isBusy`` it surfaces "queen claims to be running but hasn't said
   * anything in 30 s" — the soft signal for stuck/unresponsive queens
   * the rehydration plan calls H3/U3. */
  lastEventAt?: number;
}

const queenColor = "hsl(30,73%,47%)";
const workerColor = "hsl(220,60%,55%)";

function queenPhaseLabel(phase?: QueenPhase, title?: string): string {
  return title || phase || "independent";
}

function queenPhaseBadgeClass(_phase?: QueenPhase): string {
  return "bg-primary/15 text-primary";
}

function getColor(_agent: string, role?: "queen" | "worker"): string {
  if (role === "queen") return queenColor;
  return workerColor;
}

// ---------------------------------------------------------------------------
// Tool activity row
//
// Each `tool_status` chat message holds one tool call. Adjacent
// tool_status messages get merged into one render group upstream
// (see `tool_status_group` in itemsWithDividers); this component
// renders that merged content as a chronological list of pills, plus
// an optional click-to-expand detail panel.
//
// Grouping: consecutive same-name calls collapse into one pill, but
// pills split on status boundaries so a "fail" mid-burst doesn't get
// hidden inside an otherwise-green ×N. Color: `done` uses a per-tool-
// family hue (toolHex) so visually scanning a transcript groups
// browser_*, terminal_*, etc. together; running/error/warning/
// interrupted use status-semantic colors so they pop.
// ---------------------------------------------------------------------------

type ToolStatus = "running" | "done" | "error" | "warning" | "interrupted";

interface ToolEntryLike {
  name: string;
  done: boolean;
  isError?: boolean;
  isInterrupted?: boolean;
  callKey?: string;
  startedAt?: number;
  endedAt?: number;
  args?: unknown;
  result?: unknown;
}

interface Pill {
  key: string;
  name: string;
  status: ToolStatus;
  entries: ToolEntryLike[];
}

function isTerminalTool(name: string): boolean {
  return name.startsWith("terminal_");
}

// Commands invoked via terminal_exec get their own friendly pill label so a
// burst of DB reads / scripts / sleeps reads as distinct work instead of one
// generic "terminal_exec ×N". Matched on the command's FIRST TOKEN (after
// stripping leading ENV=val / sudo), so short names like `cat` can't false-
// match (`catalog` won't hit `cat`). Applies in queen DM + colonies (both
// render through ChatPanel). Add tokens here as usage grows.
const CLI_LABELS: Record<string, string> = {
  "hive-global-db": "hive-crm",
  "hive-crm": "hive-crm",
  sqlite3: "terminal-sql",
  cat: "terminal-read",
  sleep: "sleep",
  python3: "terminal-python",
  python: "terminal-python",
};

/** If a terminal_exec call runs a known command, return its friendly label. */
function terminalExecLabel(args: unknown): string | null {
  if (typeof args !== "object" || args === null) return null;
  let cmd = String((args as { command?: unknown }).command ?? "").trim();
  while (/^[A-Z_][A-Z0-9_]*=\S*\s/.test(cmd)) {
    cmd = cmd.replace(/^[A-Z_][A-Z0-9_]*=\S*\s/, "");
  }
  if (cmd.startsWith("sudo ")) cmd = cmd.slice(5).trim();
  const tok = cmd.split(/\s+/)[0] ?? "";
  return CLI_LABELS[tok] ?? null;
}

/** The grouping key + pill label for a tool entry. terminal_exec calls that run
 *  a known CLI are grouped under that CLI's label, separately from generic
 *  terminal_exec. */
function pillNameFor(t: ToolEntryLike): string {
  if (isTerminalTool(t.name)) {
    const label = terminalExecLabel(t.args);
    if (label) return label;
  }
  return t.name;
}

function entryStatus(t: ToolEntryLike): ToolStatus {
  if (!t.done) return "running";
  if (t.isError) return "error";
  if (t.isInterrupted) return "interrupted";
  if (isTerminalTool(t.name) && t.result && typeof t.result === "object") {
    const w = (t.result as { warning?: unknown }).warning;
    if (typeof w === "string" && w.length > 0) return "warning";
  }
  return "done";
}

// Warm honey palette: same-prefix tools (`browser_*`, `terminal_*`,
// `chart_*`, …) hash to the same hue so a long burst reads as one
// visual family. Only used for `done` pills — other statuses paint
// from STATUS_CLASSES so attention-grabbing states still pop.
const TOOL_HEX = [
  "#ffb825", "#ff9624", "#c48820", "#e89530",
  "#d4a040", "#cc7a10", "#e5a820",
];

function toolHex(name: string): string {
  const key = name.split("_", 1)[0] || name;
  let h = 0;
  for (let i = 0; i < key.length; i++) h = (h * 31 + key.charCodeAt(i)) | 0;
  return TOOL_HEX[Math.abs(h) % TOOL_HEX.length];
}

function doneStyle(name: string): React.CSSProperties {
  const hex = toolHex(name);
  return { color: hex, backgroundColor: `${hex}18`, borderColor: `${hex}35` };
}

const STATUS_CLASSES: Record<ToolStatus, string> = {
  running:
    "text-emerald-700 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-950/40 border-emerald-300/70 dark:border-emerald-700/60",
  done: "", // doneStyle() supplies an inline hue per tool family
  interrupted:
    "text-muted-foreground/80 bg-muted/30 border-dashed border-border/60",
  error:
    "text-red-700 dark:text-red-400 bg-red-50 dark:bg-red-950/40 border-red-300/70 dark:border-red-800/60",
  warning:
    "text-amber-700 dark:text-amber-400 bg-amber-50 dark:bg-amber-950/40 border-amber-300/70 dark:border-amber-800/60",
};

/** Groups by name across the WHOLE block (not run-length): an
 * alternating burst A,B,A,B,A collapses to one `A ×3` + one `B ×2`
 * instead of five separate pills. Status still splits, so a mixed-
 * state run (some done, one errored, some still running) shows as
 * multiple adjacent pills instead of one ambiguous ×N. Names and
 * statuses surface in first-appearance order (insertion-ordered Map).
 */
function buildPills(tools: ToolEntryLike[]): Pill[] {
  const ORDER: ToolStatus[] = ["done", "interrupted", "error", "warning", "running"];
  const byName = new Map<string, Map<ToolStatus, ToolEntryLike[]>>();
  for (const t of tools) {
    const status = entryStatus(t);
    const name = pillNameFor(t);
    let inner = byName.get(name);
    if (!inner) {
      inner = new Map();
      byName.set(name, inner);
    }
    const list = inner.get(status);
    if (list) {
      list.push(t);
    } else {
      inner.set(status, [t]);
    }
  }
  const out: Pill[] = [];
  for (const [name, statuses] of byName) {
    for (const status of ORDER) {
      const entries = statuses.get(status);
      if (!entries || entries.length === 0) continue;
      out.push({ key: `${out.length}-${status}-${name}`, name, status, entries });
    }
  }
  return out;
}

function StatusGlyph({ status, className = "w-2.5 h-2.5" }: { status: ToolStatus; className?: string }) {
  if (status === "running") return <Loader2 className={`${className} animate-spin`} />;
  if (status === "error") return <X className={className} />;
  if (status === "warning") return <AlertTriangle className={className} />;
  if (status === "interrupted") return <Ban className={`${className} opacity-70`} />;
  return <Check className={`${className} opacity-70`} />;
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${Math.max(0, Math.round(ms))}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  const m = Math.floor(ms / 60_000);
  const s = Math.floor((ms % 60_000) / 1000);
  return `${m}m${s.toString().padStart(2, "0")}s`;
}

function formatTimeOfDay(ms: number): string {
  const d = new Date(ms);
  return [d.getHours(), d.getMinutes(), d.getSeconds()]
    .map((n) => n.toString().padStart(2, "0"))
    .join(":");
}

/** Per-call timing line shown inside the expanded panel for non-
 * terminal tools (terminal_* uses TerminalToolDetail with stdout). */
function GenericCallDetail({ entry }: { entry: ToolEntryLike }) {
  const status = entryStatus(entry);
  const interrupted = status === "interrupted";
  const started = entry.startedAt;
  const duration =
    started !== undefined && !interrupted
      ? formatDuration((entry.endedAt ?? Date.now()) - started)
      : null;
  return (
    <div className="flex items-center gap-2 text-[11px] text-muted-foreground font-mono">
      <span className="shrink-0 w-3 text-foreground/60">
        <StatusGlyph status={status} />
      </span>
      {started !== undefined && <span>{formatTimeOfDay(started)}</span>}
      {duration && <span className="text-muted-foreground/70">· {duration}</span>}
      {interrupted && <span className="italic text-muted-foreground/70">· interrupted</span>}
      {started === undefined && !interrupted && (
        <span className="italic text-muted-foreground/70">no timing</span>
      )}
    </div>
  );
}

/** Concatenate the `tools` arrays of multiple `tool_status` messages
 * into a single content blob, so a `tool_status_group` renders as one
 * flex-wrap pill row. Each ChatPanel `tool_status` message holds one
 * tool, but a stable shape `{tools, allDone}` is preserved. */
export function mergeToolStatusContents(messages: ChatMessage[]): string {
  const tools: unknown[] = [];
  for (const m of messages) {
    try {
      const parsed = JSON.parse(m.content);
      if (Array.isArray(parsed?.tools)) tools.push(...parsed.tools);
    } catch {
      // Legacy plain-text fallback — skip.
    }
  }
  const allDone =
    tools.length > 0 &&
    tools.every((t) => (t as { done?: boolean })?.done === true);
  return JSON.stringify({ tools, allDone });
}

/** One campaign the user can import from, as `hive-crm reveal` reported it. */
type MigrationCandidate = {
  colony_id: string;
  name?: string;
  table?: string;
  row_count: number;
};

/**
 * Pull the migration options out of a completed `hive-crm reveal`.
 *
 * Read off the tool RESULT, not the command string: the candidates are computed
 * by the runtime from its colony index, never authored by the agent. That is
 * deliberate — clicking one of these sends a message attributed to the user, and
 * a label the agent wrote would be the agent putting words in their mouth which
 * then re-enter its own context as their intent. The runtime also already
 * excludes the seeded demo colony, so it can never become a button.
 */
function readRevealMigration(t: ToolEntryLike): MigrationCandidate[] {
  const stdout = (t.result as { stdout?: unknown } | undefined)?.stdout;
  if (typeof stdout !== "string" || !stdout.includes("migration")) return [];
  try {
    const parsed = JSON.parse(stdout) as {
      migration?: { candidates?: unknown };
    };
    const raw = parsed.migration?.candidates;
    if (!Array.isArray(raw)) return [];
    return raw.filter(
      (c): c is MigrationCandidate =>
        !!c &&
        typeof (c as MigrationCandidate).colony_id === "string" &&
        typeof (c as MigrationCandidate).row_count === "number",
    );
  } catch {
    // Not JSON (the agent ran reveal without --json, or output was truncated).
    // The Open-CRM card still renders; only the extra buttons are lost.
    return [];
  }
}

/**
 * Did this `hive-crm reveal` fail?
 *
 * `isError` cannot answer that, and the gap is the whole bug: it reports whether
 * the TOOL CALL failed, while a shell command that exits non-zero is a perfectly
 * successful `terminal_exec`. So the refusal a colony agent gets (exit 3,
 * `reveal_not_permitted` — revealing is the setup handoff, which belongs to the
 * user's DM) arrives as a *successful* tool with the failure buried in its
 * envelope, and the card rendered regardless: an "Open CRM" invitation for a
 * board nobody ever handed over.
 *
 * Positive evidence only — a non-zero exit, or the CLI's `{"error":{…}}`
 * envelope. Output we cannot parse is deliberately NOT treated as failure: the
 * card has always rendered in that case with only the import buttons lost (see
 * readRevealMigration, and the sibling test), and a parse quirk is not evidence
 * the reveal didn't happen.
 */
function revealFailed(t: ToolEntryLike): boolean {
  const result = t.result as { exit_code?: unknown; stdout?: unknown } | undefined;
  if (!result) return false;
  if (typeof result.exit_code === "number" && result.exit_code !== 0) return true;
  if (typeof result.stdout !== "string") return false;
  try {
    return !!(JSON.parse(result.stdout) as { error?: unknown }).error;
  } catch {
    return false;
  }
}

/** "linkedin_outreach" → "linkedin outreach" — the user's own colony name. */
function humanizeColony(c: MigrationCandidate): string {
  return (c.name || c.colony_id).replace(/[_-]+/g, " ").trim();
}

/** Collapsible thinking trace. Streams a tail-capped snapshot live, then the
 *  full block on completion — collapsed by default so it never crowds the
 *  conversation, but present so a long native think doesn't look like a hang. */
export function ReasoningRow({ content }: { content: string }) {
  const [open, setOpen] = useState(false);
  const trimmed = content.trim();
  if (!trimmed) return null;
  const preview = trimmed.length > 120 ? trimmed.slice(0, 120) + "…" : trimmed;
  return (
    <div className="my-1 text-xs">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 text-muted-foreground/70 hover:text-muted-foreground transition-colors"
      >
        <Brain className="w-3.5 h-3.5 shrink-0" />
        <span className="italic">{open ? "Thinking" : preview}</span>
        <ChevronRight
          className={`w-3 h-3 shrink-0 transition-transform ${open ? "rotate-90" : ""}`}
        />
      </button>
      {open && (
        <div className="mt-1 ml-5 pl-3 border-l border-border/60 text-muted-foreground/80 whitespace-pre-wrap leading-relaxed">
          {trimmed}
        </div>
      )}
    </div>
  );
}

export function ToolActivityRow({
  content,
  onQuickReply,
}: {
  content: string;
  /** Send a message as the user. Omitted in history/colony views, which must
   *  not offer live actions — that is also what keeps a resumed transcript's
   *  older reveal cards from re-asking a question already answered. */
  onQuickReply?: (text: string) => void;
}) {
  let tools: ToolEntryLike[] = [];
  try {
    tools = JSON.parse(content).tools ?? [];
  } catch {
    return (
      <div className="flex gap-3 pl-10">
        <span className="text-[11px] text-muted-foreground bg-muted/40 px-3 py-1 rounded-full border border-border/40">
          {content}
        </span>
      </div>
    );
  }
  if (tools.length === 0) return null;

  const pills = buildPills(tools);
  // Chart embeds render below the pill row, unchanged.
  const charts = tools.filter((t) => t.name.startsWith("chart_"));
  // If the agent completed a `hive-crm reveal` checkpoint in this block,
  // surface a persistent "Open CRM" card. Derived from the tool_status message
  // itself (not live-injected) so it survives session resume and renders in
  // both queen DM and colonies. Only when the command itself did not fail — see
  // revealFailed for why `!t.isError` cannot carry that on its own.
  const revealTool = tools.find(
    (t) =>
      isTerminalTool(t.name) &&
      t.done &&
      !t.isError &&
      /\bhive-crm\s+reveal\b/.test(
        String((t.args as { command?: unknown } | undefined)?.command ?? ""),
      ) &&
      !revealFailed(t),
  );
  const revealed = !!revealTool;
  // Campaign-import options, offered only where a live send handler exists.
  const migration = revealTool && onQuickReply ? readRevealMigration(revealTool) : [];

  return (
    <div className="flex flex-col gap-1.5">
      <div className="pl-10">
        <ToolPillRow pills={pills} />
      </div>
      {charts.map((t, idx) => (
        <ChartToolDetail key={t.callKey ?? `${t.name}-${idx}`} entry={t as ChartToolEntry} />
      ))}
      {revealed && (
        // Compact action card — left-aligned with the agent's tool activity
        // (not a centered promo CTA). Light surface, hairline border, the only
        // accent is the icon so it reads as part of the conversation, not an ad.
        <div className="pl-10">
          <Link
            to="/crm"
            className="group flex max-w-sm items-center gap-3 rounded-lg border border-border/60 bg-card px-3 py-2 hover:border-primary/40 hover:bg-accent/40 transition-colors"
          >
            <span className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
              <Table2 className="h-4 w-4" />
            </span>
            <span className="min-w-0 flex-1">
              <span className="block text-[13px] font-medium leading-tight text-foreground">
                Open CRM
              </span>
              <span className="block text-[11px] leading-tight text-muted-foreground">
                View the pipeline and contacts
              </span>
            </span>
            <ExternalLink className="h-3.5 w-3.5 flex-shrink-0 text-muted-foreground group-hover:text-primary transition-colors" />
          </Link>
        </div>
      )}
      {migration.length > 0 && onQuickReply && (
        <MigrationOptions candidates={migration} onQuickReply={onQuickReply} />
      )}
    </div>
  );
}

/**
 * "Bring your existing leads in" — the choice offered beside the Open-CRM card.
 *
 * This exists because the one question this stage turns on — WHICH campaign is
 * the user's real pipeline — is one only the user can answer. Row count alone
 * ranks an 86k-row scrape above a 227-lead pipeline, so the agent asking itself
 * gets it wrong; asking in prose can be skipped by an agent in a hurry. Buttons
 * ask at the moment the user has just been handed their board.
 *
 * The counts are shown deliberately: "86,425" beside "227" is a warning label to
 * someone who knows their own pipeline, and it lets them choose correctly with
 * no advice from us.
 *
 * The message text is OURS, not the agent's, and reads like something a person
 * would type — a click is an endorsement of a label, not of a sentence the agent
 * wrote and will read back as the user's intent.
 */
function MigrationOptions({
  candidates,
  onQuickReply,
}: {
  candidates: MigrationCandidate[];
  onQuickReply: (text: string) => void;
}) {
  // Answered once, gone — a question already answered must stop looking askable.
  const [answered, setAnswered] = useState(false);
  if (answered) return null;

  const pick = (text: string) => {
    setAnswered(true);
    onQuickReply(text);
  };

  return (
    <div className="pl-10">
      <div className="max-w-sm space-y-1.5">
        <p className="text-[11px] text-muted-foreground">
          Bring in leads you already have?
        </p>
        <div className="flex flex-wrap gap-1.5">
          {candidates.map((c) => (
            <button
              key={c.colony_id}
              onClick={() =>
                pick(
                  `Import the ${c.row_count.toLocaleString()} contacts from ${c.colony_id} into my CRM.`,
                )
              }
              className="rounded-md border border-border/60 bg-card px-2.5 py-1.5 text-[12px] text-foreground hover:border-primary/40 hover:bg-accent/40 transition-colors"
            >
              Import {c.row_count.toLocaleString()} from{" "}
              <span className="font-medium">{humanizeColony(c)}</span>
            </button>
          ))}
          <button
            onClick={() => pick("Don't import anything for now.")}
            className="rounded-md px-2.5 py-1.5 text-[12px] text-muted-foreground hover:text-foreground transition-colors"
          >
            Not now
          </button>
        </div>
      </div>
    </div>
  );
}

function ToolPillRow({ pills }: { pills: Pill[] }) {
  const [openKey, setOpenKey] = useState<string | null>(null);
  const open = pills.find((p) => p.key === openKey) || null;
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex flex-wrap items-center gap-1.5">
        {pills.map((p) => (
          <ToolPillButton
            key={p.key}
            pill={p}
            isOpen={p.key === openKey}
            onClick={() => setOpenKey(p.key === openKey ? null : p.key)}
          />
        ))}
      </div>
      {open && (
        <div className="ml-2 pl-3 border-l border-border/60 space-y-2 py-1">
          {open.entries.map((entry, idx) => (
            <div key={entry.callKey ?? `entry-${idx}`} className="text-[11px]">
              {isTerminalTool(entry.name) ? (
                <TerminalToolDetail entry={entry as TerminalToolEntry} />
              ) : (
                <GenericCallDetail entry={entry} />
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function ToolPillButton({
  pill,
  isOpen,
  onClick,
}: {
  pill: Pill;
  isOpen: boolean;
  onClick: () => void;
}) {
  const style = pill.status === "done" ? doneStyle(pill.name) : undefined;
  const single = pill.entries.length === 1 ? pill.entries[0] : null;
  return (
    <button
      type="button"
      onClick={onClick}
      style={style}
      className={`inline-flex items-center gap-1 text-[11px] px-2.5 py-0.5 rounded-full border transition-colors cursor-pointer ${STATUS_CLASSES[pill.status]} ${
        isOpen
          ? "ring-2 ring-offset-1 ring-offset-background ring-foreground/20"
          : "hover:brightness-110"
      }`}
      aria-expanded={isOpen}
    >
      <StatusGlyph status={pill.status} />
      <span className="font-medium">{pill.name}</span>
      {pill.entries.length > 1 && (
        <span className="text-[10px] opacity-80">×{pill.entries.length}</span>
      )}
      {pill.status === "running" && single?.startedAt !== undefined && (
        <RunningElapsed startedAt={single.startedAt} />
      )}
    </button>
  );
}

/** Live-ticking elapsed counter — the surrounding row already re-
 * renders every second via ChatPanel's setNowTick while the queen is
 * busy, so this just reads Date.now() at render time. */
function RunningElapsed({ startedAt }: { startedAt: number }) {
  const elapsed = Math.max(0, Math.floor((Date.now() - startedAt) / 1000));
  return <span className="text-[10px] tabular-nums opacity-80">{elapsed}s</span>;
}

// --- Inline ask_user fallback ---------------------------------------------
// Sometimes the model prints the ask_user payload as regular assistant
// text instead of invoking the tool. We detect that payload here and
// render a QuestionWidget / MultiQuestionWidget inline so the user still
// gets the nice button UI. Submissions are sent back as a regular user
// message via onSend (there is no pending backend state to fulfill, so
// we treat it like the user answering in chat).

type AskUserInlinePayload = {
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

  // Normalize to the unified ask_user shape:
  //   { questions: [{ id, prompt, options? }, ...] }
  // Accept either the array form directly, or a legacy single-question
  // shape { question, options } that models occasionally still emit —
  // it gets wrapped into a one-entry array.
  let raw: unknown[] | null = null;
  if (Array.isArray(obj.questions)) {
    raw = obj.questions as unknown[];
  } else if (typeof obj.question === "string" || typeof obj.prompt === "string") {
    raw = [obj];
  }
  if (!raw || raw.length < 1 || raw.length > 8) return null;

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

  // Require either a multi-question batch or a single-with-options
  // payload — a single free-form prompt isn't worth a widget.
  if (questions.length === 1 && !(questions[0].options && questions[0].options.length >= 2)) {
    return null;
  }
  return { questions };
}

function InlineAskUserBubble({
  msg,
  payload,
  activeThread,
  onSend,
  queenPhase,
  showQueenPhaseBadge = true,
  queenTitle,
  queenProfileId,
  queenAvatarUrl,
  queenPortrait,
  onImageClick,
}: {
  msg: ChatMessage;
  payload: AskUserInlinePayload;
  activeThread: string;
  queenAvatarUrl?: string | null;
  queenPortrait?: PortraitDescriptor | null;
  onSend: (
    message: string,
    thread: string,
    images?: ImageContent[],
  ) => void;
  queenPhase?: QueenPhase;
  showQueenPhaseBadge?: boolean;
  queenTitle?: string;
  queenProfileId?: string | null;
  onImageClick?: (images: ImageContent[], index: number, sessionId?: string) => void;
}) {
  const [state, setState] = useState<"pending" | "submitted" | "dismissed">(
    "pending",
  );
  // Both context hooks must stay above the early returns below — without
  // this React unmounts on the first state transition with "Rendered
  // fewer hooks than expected." See SessionsTab for the same pattern.
  const { openQueenProfile } = useQueenProfile();
  const { openColonyWorkers } = useColonyWorkers();

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
        queenTitle={queenTitle}
        queenProfileId={queenProfileId}
        queenAvatarUrl={queenAvatarUrl}
        queenPortrait={queenPortrait}
        onImageClick={onImageClick}
      />
    );
  }

  const isQueen = msg.role === "queen";
  const color = getColor(msg.agent, msg.role);
  const thread = msg.thread || activeThread;
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

  const handleSubmit = (answers: Record<string, string>) => {
    setState("submitted");
    if (payload.questions.length === 1) {
      const only = payload.questions[0];
      onSend(answers[only.id] ?? "", thread);
      return;
    }
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
          boxShadow: isQueen ? `0 0 6px ${color}10` : undefined,
        }}
        onClick={handleAvatarClick}
        title={avatarTitle}
      >
        {isQueen ? (
          <QueenAvatarIcon url={queenAvatarUrl ?? null} size={9} portrait={queenPortrait} />
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
          {(!isQueen || showQueenPhaseBadge) && (() => {
            const effectivePhase = msg.phase ?? queenPhase;
            const badgeClass = isQueen
              ? queenPhaseBadgeClass(effectivePhase)
              : "bg-muted text-muted-foreground";
            const label = isQueen ? queenPhaseLabel(effectivePhase, queenTitle) : "Worker";
            return (
              <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded-md ${badgeClass}`}>
                {label}
              </span>
            );
          })()}
        </div>
        {payload.questions.length >= 2 ? (
          <MultiQuestionWidget
            inline
            questions={payload.questions}
            onSubmit={handleSubmit}
            onDismiss={() => setState("dismissed")}
          />
        ) : (
          <QuestionWidget
            inline
            question={payload.questions[0].prompt}
            options={payload.questions[0].options ?? []}
            onSubmit={(answer) =>
              handleSubmit({ [payload.questions[0].id]: answer })
            }
            onDismiss={() => setState("dismissed")}
          />
        )}
      </div>
    </div>
  );
}

function InheritedBlock({
  content,
  renderMessage,
}: {
  content: string;
  renderMessage: (msg: ChatMessage) => React.ReactNode;
}) {
  // Default to collapsed — the colony's own conversation is what the
  // user navigated for; the inherited DM transcript is one click away.
  const [open, setOpen] = useState(false);
  let parsed: {
    parent_session_id?: string | null;
    fork_time?: string | null;
    summary_preview?: string;
    inherited_message_count?: number;
    messages?: ChatMessage[];
  } = {};
  try {
    parsed = JSON.parse(content);
  } catch {
    // fall through to a degraded "Inherited from previous chat" affordance
  }
  const messages = Array.isArray(parsed.messages) ? parsed.messages : [];
  const count =
    typeof parsed.inherited_message_count === "number"
      ? parsed.inherited_message_count
      : messages.length;
  const preview = (parsed.summary_preview || "").trim();

  return (
    <div className="my-3">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-2 text-[11px] text-muted-foreground bg-muted/30 hover:bg-muted/50 px-3 py-2 rounded-md border border-border/40 transition-colors"
      >
        <span className="font-medium">
          {open ? "▼" : "▶"} Inherited from previous queen DM
        </span>
        <span className="text-muted-foreground/70">
          ({count} message{count === 1 ? "" : "s"})
        </span>
      </button>
      {open ? (
        <div className="mt-2 pl-3 border-l-2 border-border/40 space-y-2">
          {messages.length === 0 ? (
            <div className="text-[11px] text-muted-foreground italic px-2 py-1">
              {preview || "No messages preserved."}
            </div>
          ) : (
            messages.map((m) => (
              <div key={m.id} className="opacity-80">
                {renderMessage(m)}
              </div>
            ))
          )}
        </div>
      ) : preview ? (
        <div className="mt-1 text-[11px] text-muted-foreground/80 italic px-3 line-clamp-2">
          {preview}
        </div>
      ) : null}
    </div>
  );
}

function QueenAvatarIcon({
  url,
  size,
  portrait,
}: {
  url: string | null;
  size: number;
  portrait?: PortraitDescriptor | null;
}) {
  const [ok, setOk] = useState(!!url);
  const dim = size === 9 ? "w-9 h-9" : "w-7 h-7";
  if (ok && url) {
    return <img src={url} alt="" className={`${dim} rounded-xl object-cover`} onError={() => setOk(false)} />;
  }
  if (portrait) {
    return <QueenPortraitGlyph p={portrait} className={`${dim} rounded-xl`} />;
  }
  return <Crown className={size === 9 ? "w-4 h-4" : "w-3.5 h-3.5"} style={{ color: queenColor }} />;
}

// Answers to a multi-question ask_user are sent as `"prompt"="answer"`
// lines (see handleQuestionAnswer in queen-dm). Detect that shape so the
// user bubble can render a clean Q&A list instead of raw quoted text.
// Returns null unless *every* line matches — partial matches fall back
// to plain text so a normal message with a quoted phrase isn't mangled.
function parseQnA(content: string): { q: string; a: string }[] | null {
  const lines = content
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean);
  if (lines.length < 2) return null;
  const pairs: { q: string; a: string }[] = [];
  for (const line of lines) {
    const m = /^"(.+?)"="(.*)"$/.exec(line);
    if (!m) return null;
    pairs.push({ q: m[1], a: m[2] });
  }
  return pairs;
}

const MessageBubble = memo(
  function MessageBubble({
    msg,
    queenPhase,
    showQueenPhaseBadge = true,
    queenTitle,
    queenProfileId,
    queenAvatarUrl,
    queenPortrait,
    onColonyLinkClick,
    onSteer,
    onCancelQueued,
    onRetry,
    onEdit,
    isQueenBusy,
    onImageClick,
    feedbackSessionId,
    initialVote,
  }: {
    msg: ChatMessage;
    queenPhase?: QueenPhase;
    showQueenPhaseBadge?: boolean;
    queenTitle?: string;
    queenProfileId?: string | null;
    queenAvatarUrl?: string | null;
    queenPortrait?: PortraitDescriptor | null;
    onColonyLinkClick?: (colonyName: string) => void;
    onImageClick?: (images: ImageContent[], index: number, sessionId?: string) => void;
    onSteer?: (messageId: string) => void;
    onCancelQueued?: (messageId: string) => void;
    onRetry?: (text: string) => void;
    onEdit?: (text: string) => void;
    isQueenBusy?: boolean;
    /** Backend session id used to persist thumbs-up/down votes. */
    feedbackSessionId?: string | null;
    /** Pre-loaded vote for this message; hydrates FeedbackBtns. */
    initialVote?: Vote | null;
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
    // Worker messages: clicking the avatar opens the Colony
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

    if (msg.type === "trigger") {
      // Rendered when a scheduler/webhook trigger fires. Content is a JSON
      // payload: { trigger_id, trigger_type, name, task, last_fired_at,
      // fire_count }. Shown as a distinctive banner marking the start of
      // the turn the queen is about to run in response.
      let parsed: {
        trigger_id?: string;
        trigger_type?: string;
        name?: string;
        task?: string;
        fire_count?: number;
        last_fired_at?: number;
      } = {};
      try {
        parsed = JSON.parse(msg.content);
      } catch {
        // Fall through to plain text
      }
      const label = parsed.name || parsed.trigger_id || "trigger";
      const kind = parsed.trigger_type || "timer";
      const task = (parsed.task || "").trim();
      const fireCount = parsed.fire_count;
      return (
        <div className="flex justify-center py-2">
          <div className="max-w-[85%] w-full rounded-lg border border-amber-500/30 bg-amber-500/5 px-3 py-2">
            <div className="flex items-center gap-2 mb-1">
              <span className="inline-flex items-center justify-center w-5 h-5 rounded-full bg-amber-500/15 text-amber-400">
                <Zap className="w-3 h-3" />
              </span>
              <span className="text-[11px] font-semibold text-amber-400 uppercase tracking-wider">
                {kind === "webhook" ? "Webhook" : "Scheduler"} fired
              </span>
              <span className="text-[11px] text-foreground font-mono truncate">{label}</span>
              {fireCount != null && fireCount > 0 && (
                <span className="ml-auto text-[10px] text-muted-foreground">#{fireCount}</span>
              )}
            </div>
            {task && (
              <p className="text-[12px] text-muted-foreground leading-snug whitespace-pre-wrap">
                {task}
              </p>
            )}
          </div>
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
        colony_id?: string;
        is_new?: boolean;
        skill_name?: string;
        href?: string;
      } = {};
      try {
        parsed = JSON.parse(msg.content);
      } catch {
        // ignore — fall through to a plain text render
      }
      const colonyId = parsed.colony_id || "";
      const href = parsed.href || (colonyId ? `/colony/${colonyId}` : "");
      const skillLabel = parsed.skill_name
        ? ` · skill: ${parsed.skill_name}`
        : "";
      const isNewLabel = parsed.is_new === false ? " (updated)" : " (new)";
      return (
        <div className="flex justify-center py-2">
          <Link
            to={href}
            onClick={() => {
              if (colonyId && onColonyLinkClick) {
                onColonyLinkClick(colonyId);
              }
            }}
            className="inline-flex items-center gap-2 text-xs font-medium text-primary bg-primary/10 hover:bg-primary/20 px-4 py-2 rounded-full border border-primary/20 transition-colors"
          >
            <span>🏛️</span>
            <span>
              Colony <strong>{colonyId}</strong>{isNewLabel} ready{skillLabel} — open
            </span>
          </Link>
        </div>
      );
    }

    if (msg.type === "inherited_block") {
      return (
        <InheritedBlock
          content={msg.content}
          renderMessage={(inner) => (
            <MessageBubble
              msg={inner}
              queenPhase={queenPhase}
              showQueenPhaseBadge={showQueenPhaseBadge}
              queenTitle={queenTitle}
              queenProfileId={queenProfileId}
              queenAvatarUrl={queenAvatarUrl}
              queenPortrait={queenPortrait}
              onColonyLinkClick={onColonyLinkClick}
              onImageClick={onImageClick}
            />
          )}
        />
      );
    }

    if (msg.type === "tool_status") {
      return <ToolActivityRow content={msg.content} />;
    }

    if (msg.type === "reasoning") {
      return <ReasoningRow content={msg.content} />;
    }

    if (isUser) {
      return (
        <div className="flex flex-col items-end gap-1 group">
          <div
            className={`max-w-[75%] bg-primary text-black text-sm leading-relaxed rounded-2xl rounded-br-md px-4 py-3${msg.queued ? " ring-1 ring-amber-500/50" : ""}`}
          >
            {msg.images && msg.images.length > 0 && (
              <div className="flex flex-wrap gap-2 mb-2">
                {msg.images.map((img, i) => (
                  img._generated ? (
                    <GeneratedImageCard
                      key={i}
                      url={img.image_url.url}
                      fileName={img._fileName}
                      credits={img._credits}
                      sessionId={msg.attachmentSessionId ?? feedbackSessionId ?? undefined}
                      onClick={() => onImageClick?.(msg.images!, i, msg.attachmentSessionId ?? feedbackSessionId ?? undefined)}
                    />
                  ) : (
                    <AttachmentChip
                      key={i}
                      url={img.image_url.url}
                      fileName={img._fileName}
                      byteSize={img._byteSize}
                      credits={img._credits}
                      variant="history"
                      sessionId={msg.attachmentSessionId ?? feedbackSessionId ?? undefined}
                      onClick={() => onImageClick?.(msg.images!, i, msg.attachmentSessionId ?? feedbackSessionId ?? undefined)}
                    />
                  )
                ))}
              </div>
            )}
            {msg.content &&
              (() => {
                const cleanedContent = stripSystemReminders(msg.content);
                const qna = parseQnA(cleanedContent);
                if (qna) {
                  return (
                    <div className="flex flex-col gap-2">
                      {qna.map((pair, i) => (
                        <div key={i} className="flex flex-col gap-0.5">
                          <span className="text-[12px] font-medium opacity-60 break-words">
                            {pair.q}
                          </span>
                          <span className="break-words">{pair.a}</span>
                        </div>
                      ))}
                    </div>
                  );
                }
                return (
                  <SkillMarkerText
                    text={cleanedContent}
                    tone="onPrimary"
                    className="block"
                  />
                );
              })()}
            {(msg.queued || msg.createdAt) && (
              <div className="flex justify-end items-center gap-1.5 mt-1 text-[10px] opacity-60">
                {msg.queued && (
                  <span className="inline-flex items-center gap-1">
                    <span className="w-1 h-1 rounded-full bg-amber-400 animate-pulse" />
                    queued
                  </span>
                )}
                {msg.createdAt && <span>{formatMessageTime(msg.createdAt)}</span>}
              </div>
            )}
          </div>
          <div className="flex items-center gap-0.5 mt-0.5 opacity-0 group-hover:opacity-100 transition-all duration-150">
            <CopyBtn text={stripSystemReminders(msg.content)} />
            {onRetry && (
              <button
                onClick={() => onRetry(stripSystemReminders(msg.content))}
                className="p-1 rounded-md text-muted-foreground/50 hover:text-muted-foreground hover:bg-muted/40 transition-all duration-150"
                title="Retry this message"
              >
                <RotateCcw className="w-3 h-3" />
              </button>
            )}
            {onEdit && (
              <button
                onClick={() => onEdit(stripSystemReminders(msg.content))}
                className="p-1 rounded-md text-muted-foreground/50 hover:text-muted-foreground hover:bg-muted/40 transition-all duration-150"
                title="Edit in composer"
              >
                <Pencil className="w-3 h-3" />
              </button>
            )}
          </div>
          {msg.queued && (onSteer || onCancelQueued) && (
            <div className="flex items-center gap-1.5">
              {onSteer && (
                <button
                  type="button"
                  onClick={() => onSteer(msg.id)}
                  className="inline-flex items-center gap-1 text-[11px] font-medium px-2 py-0.5 rounded-full bg-amber-500/15 text-amber-600 hover:bg-amber-500/25 border border-amber-500/30 transition-colors"
                  title="Send now — influence the current turn after the next tool call"
                >
                  <Zap className="w-3 h-3" />
                  Steer
                </button>
              )}
              {onCancelQueued && (
                <button
                  type="button"
                  onClick={() => onCancelQueued(msg.id)}
                  className="inline-flex items-center gap-1 text-[11px] font-medium px-2 py-0.5 rounded-full bg-muted/60 text-muted-foreground hover:bg-muted border border-border transition-colors"
                  title="Remove this queued message"
                >
                  <X className="w-3 h-3" />
                  Cancel
                </button>
              )}
            </div>
          )}
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
      <div className="flex gap-3 group">
        <div
          className={`flex-shrink-0 ${isQueen ? "w-9 h-9" : "w-7 h-7"} rounded-xl flex items-center justify-center overflow-hidden${handleAvatarClick ? " cursor-pointer hover:opacity-80 transition-opacity" : ""}`}
          style={isQueen && queenAvatarUrl ? undefined : {
            backgroundColor: `${color}18`,
            border: `1.5px solid ${color}35`,
            boxShadow: isQueen ? `0 0 6px ${color}10` : undefined,
          }}
          onClick={handleAvatarClick}
          title={avatarTitle}
        >
          {isQueen ? (
            <QueenAvatarIcon url={queenAvatarUrl ?? null} size={9} portrait={queenPortrait} />
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
                    ? queenPhaseBadgeClass(msg.phase ?? queenPhase)
                    : "bg-muted text-muted-foreground"
                }`}
              >
                {isQueen ? queenPhaseLabel(msg.phase ?? queenPhase, queenTitle) : "Worker"}
              </span>
            )}
            {isQueen && isQueenBusy && (
              <Loader2 className="w-3 h-3 animate-spin text-muted-foreground flex-shrink-0" />
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
            {msg.images && msg.images.length > 0 && (
              <div className="flex flex-wrap gap-2 mb-2">
                {msg.images.map((img, i) => (
                  img._generated ? (
                    <GeneratedImageCard
                      key={i}
                      url={img.image_url.url}
                      fileName={img._fileName}
                      credits={img._credits}
                      sessionId={msg.attachmentSessionId ?? feedbackSessionId ?? undefined}
                      onClick={() => onImageClick?.(msg.images!, i, msg.attachmentSessionId ?? feedbackSessionId ?? undefined)}
                    />
                  ) : (
                    <AttachmentChip
                      key={i}
                      url={img.image_url.url}
                      fileName={img._fileName}
                      byteSize={img._byteSize}
                      credits={img._credits}
                      variant="history"
                      sessionId={msg.attachmentSessionId ?? feedbackSessionId ?? undefined}
                      onClick={() => onImageClick?.(msg.images!, i, msg.attachmentSessionId ?? feedbackSessionId ?? undefined)}
                    />
                  )
                ))}
              </div>
            )}
            {msg.innerTurns && msg.innerTurns.length > 1 ? (
              // Merged multi-inner-turn bubble presented as an activity
              // timeline: one continuous left rail with a node per step (each
              // step is a beat between the queen's tool calls). A single rail
              // scales cleanly to many steps, unlike a per-boundary divider
              // which reads as a fragmented receipt. Rail/node colors derive
              // from the foreground so they stay visible in both themes.
              <div className="relative flex flex-col gap-2.5 pl-[16px]">
                <span
                  aria-hidden
                  className="absolute left-[4px] top-[0.5lh] bottom-[0.5lh] w-px bg-foreground/10"
                />
                {msg.innerTurns.map((span, i) => (
                  <div key={i} className="relative">
                    {/* Node centered inside a one-line-tall box (h-[1lh]) so it
                        aligns with the first text line's optical center at any
                        line-height — not a guessed em offset. A hollow honeycomb
                        cell to match the hive theme: its opaque fill rebuilds the
                        bubble surface (background + the primary/5 tint) so the
                        rail meets the hex's top/bottom points on the center axis
                        but never shows through its empty interior. */}
                    <span className="group/tlnode absolute -left-[11.5px] top-0 flex h-[1lh] -translate-x-1/2 cursor-default items-center">
                      {/* Delayed tooltip: pure CSS (group-hover + a 750ms
                          transition-delay on show, instant hide) so it stays
                          zero-JS / zero-re-render but only appears after the
                          user lingers >0.75s. */}
                      {msg.innerTurnTimes?.[i] != null && (
                        <span className="pointer-events-none absolute bottom-full left-0 z-20 mb-1.5 whitespace-nowrap rounded-md bg-foreground px-1.5 py-0.5 text-[10px] font-medium text-background opacity-0 shadow-sm transition-opacity duration-100 group-hover/tlnode:opacity-100 group-hover/tlnode:delay-[750ms]">
                          {formatMessageTime(msg.innerTurnTimes[i])}
                        </span>
                      )}
                      <svg
                        viewBox="0 0 20 22"
                        className="h-2.5 w-2.5 text-foreground/10"
                      >
                        <polygon
                          points="10,1 18.66,6 18.66,16 10,21 1.34,16 1.34,6"
                          fill="hsl(var(--background))"
                        />
                        <polygon
                          points="10,1 18.66,6 18.66,16 10,21 1.34,16 1.34,6"
                          fill="hsl(var(--primary) / 0.05)"
                        />
                        <polygon
                          points="10,1 18.66,6 18.66,16 10,21 1.34,16 1.34,6"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth="2"
                          strokeLinejoin="round"
                        />
                      </svg>
                    </span>
                    <MarkdownContent content={span} />
                  </div>
                ))}
              </div>
            ) : (
              <MarkdownContent content={msg.content} />
            )}
          </div>
          <QueenMessageActions
            content={msg.content}
            messageId={msg.id}
            sessionId={feedbackSessionId}
            initialVote={initialVote}
            queenTitle={queenTitle}
          />
        </div>
      </div>
    );
  },
  (prev, next) =>
    prev.msg.id === next.msg.id &&
    prev.msg.content === next.msg.content &&
    prev.msg.phase === next.msg.phase &&
    prev.msg.queued === next.msg.queued &&
    prev.queenPhase === next.queenPhase &&
    prev.showQueenPhaseBadge === next.showQueenPhaseBadge &&
    prev.queenTitle === next.queenTitle &&
    prev.onSteer === next.onSteer &&
    prev.onCancelQueued === next.onCancelQueued &&
    prev.isQueenBusy === next.isQueenBusy &&
    prev.feedbackSessionId === next.feedbackSessionId &&
    prev.initialVote === next.initialVote,
);

// In-progress message drafts, keyed by chat thread, kept in a module-level
// store so a half-written message survives ChatPanel unmounting. Switching to
// another agent or queen in the sidebar is a full route change that destroys
// the page (and the local input state) — without this the draft is wiped.
// In-memory by design: drafts persist across navigation, not a full reload.
const draftStore = new Map<string, string>();

export default function ChatPanel({
  messages,
  onSend,
  isWaiting,
  isBusy,
  colonyActive,
  activeThread,
  disabled,
  sendLocked,
  paymentLocked,
  onPaymentLockedSend,
  onCancel,
  onSteer,
  onCancelQueued,
  pendingQuestions,
  onQuestionSubmit,
  onQuestionDismiss,
  queenPhase,
  showQueenPhaseBadge = true,
  queenTitle,
  contextUsage,
  supportsImages = true,
  sessionId,
  historyTimeline,
  expandedHistoryDays,
  onToggleHistoryDay,
  expandedHistorySessions,
  onToggleHistorySession,
  historySessionMessages,
  currentSessionHasMoreOlder,
  onFetchOlderPage,
  historySessionHasMoreOlder,
  onFetchOlderPageForSession,
  initialDraft,
  initialAttachments,
  autoSendToken,
  queenProfileId,
  queenId,
  onColonyLinkClick,
  colonySpawned,
  spawnedColonyName,
  queenDisplayName,
  queenPortraitOverride,
  onCompactAndFork,
  compactingAndForking,
  onStartNewSession,
  startingNewSession,
  tokenUsage,
  headerAction,
  sseState = "live",
  lastEventAt,
}: ChatPanelProps) {
  // Unique per chat: agentPath already distinguishes colonies, while every
  // queen DM shares the constant activeThread "queen-dm" so the queen id
  // disambiguates those. Drives the per-thread draft store below.
  const draftKey = `${activeThread}::${queenProfileId ?? queenId ?? ""}`;
  const draftKeyRef = useRef(draftKey);
  const [input, setInput] = useState(() => draftStore.get(draftKey) ?? "");
  const [pendingImages, setPendingImages] = useState<ImageContent[]>([]);
  const [uploadError, setUploadError] = useState<string | null>(null);
  // True while a file is being dragged over the composer — drives the drop
  // overlay. A counter (not a bool) so child enter/leave events don't flicker
  // the overlay off mid-drag; we only clear when the count returns to zero.
  const [isDragOver, setIsDragOver] = useState(false);
  const dragDepth = useRef(0);
  // Filenames currently uploading — drives the per-chip spinner so the user
  // sees feedback during the multipart upload (large PDFs can take several
  // seconds and otherwise look frozen).
  const [uploadingFiles, setUploadingFiles] = useState<string[]>([]);
  // `sessionId` rides along so the lightbox resolves `hive-attachment://`
  // refs against the session the attachment actually lives in — for history
  // timeline messages that's a *previous* session, not the active one.
  const [lightbox, setLightbox] = useState<{ images: ImageContent[]; index: number; sessionId?: string } | null>(null);

  // Stable handlers for MessageBubble — it is memo()ized, and fresh inline
  // closures on every render defeated that: every SSE delta re-rendered
  // every bubble on long transcripts, which is also what starved
  // react-router's low-priority navigation transitions (the "click Home,
  // page revives but never navigates" failure).
  const handleBubbleImageClick = useCallback(
    (images: ImageContent[], index: number, sessionId?: string) =>
      setLightbox({ images, index, sessionId }),
    [],
  );
  const handleBubbleRetry = useCallback(
    (text: string) => {
      if (onSend) {
        onSend(text, activeThread);
        setTimeout(() => bottomRef.current?.scrollIntoView({ behavior: "smooth" }), 100);
      }
    },
    [onSend, activeThread],
  );
  const handleBubbleEdit = useCallback((text: string) => {
    setInput(text);
    setTimeout(() => editorRef.current?.focus(), 0);
  }, []);
  const [readMap, setReadMap] = useState<Record<string, number>>({});
  const bottomRef = useRef<HTMLDivElement>(null);
  const bottomSpacerRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const stickToBottom = useRef(true);
  // Scroll position captured at the previous `scroll` event. Every
  // programmatic scroll in this component (the streaming re-pin, the
  // pin-restore after an older-history prepend, scrollToBottom) only ever
  // *increases* scrollTop — so a decrease, paired with a content height
  // that did not shrink (which rules out a clamp from a removed bubble),
  // is unambiguously the user dragging upward. handleScroll needs this to
  // tell the two apart; see the comment there.
  const prevScrollRef = useRef({ top: 0, height: 0 });
  const editorRef = useRef<SkillTextEditorHandle>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const lastAppliedDraftRef = useRef<string | null | undefined>(undefined);
  // Handed-over attachments: which array we've ingested, and whether that
  // ingestion has finished. Auto-send waits on the latter — firing mid-ingest
  // would send the message with only some of the files, or none.
  const lastAppliedAttachmentsRef = useRef<File[] | null | undefined>(undefined);
  const [handoffIngested, setHandoffIngested] = useState(false);
  const autoSentTokenRef = useRef<number | null>(null);

  // In-conversation search (Cmd/Ctrl+F). The overlay is local to the
  // chat panel; matches are highlighted on their wrapper divs and the
  // current match scrolls into view on every step. Match traversal is
  // top-down (oldest match first) so prev/next reads naturally.
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [currentMatchIdx, setCurrentMatchIdx] = useState(0);
  const searchInputRef = useRef<HTMLInputElement>(null);
  const messageWrapperRefs = useRef<Map<string, HTMLDivElement>>(new Map());

  // Lazy older-history windowing — render only the most recent messages
  // and reveal older ones on scroll-up / auto-fill. See useLazyHistoryWindow;
  // the hook is invoked below, once `allThreadMessages` is known.
  const { queenProfiles, queenAvatarVersion, queenHasAvatar } = useColony();
  // Suppress the avatar URL entirely when the runtime says no image exists
  // — that way QueenAvatarIcon falls back to portrait/crown without an
  // `<img>` 404 hitting the console for every message bubble.
  const queenAvatarUrl = queenId && queenHasAvatar(queenId)
    ? apiUrl(`/queen/${queenId}/avatar?v=${queenAvatarVersion(queenId)}`)
    : null;
  const queenPortrait =
    queenPortraitOverride ??
    (queenId ? queenProfiles.find((q) => q.id === queenId)?.portrait ?? null : null);

  // Cmd/Ctrl+F opens the search overlay; Esc closes it.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "f") {
        e.preventDefault();
        setSearchOpen(true);
        window.setTimeout(() => {
          searchInputRef.current?.focus();
          searchInputRef.current?.select();
        }, 0);
      } else if (e.key === "Escape" && searchOpen) {
        e.preventDefault();
        setSearchOpen(false);
        setSearchQuery("");
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [searchOpen]);

  // Reset to the first match whenever the query changes — keeps next/prev
  // intuitive (the user expects the first hit, not wherever they left off).
  useEffect(() => {
    setCurrentMatchIdx(0);
  }, [searchQuery]);

  // Compute message IDs whose `content` matches the (case-insensitive)
  // query. The same array preserves message order so prev/next is
  // chronological. Skipped when search is closed or the query is empty.
  const searchMatchedIds = useMemo<string[]>(() => {
    if (!searchOpen || !searchQuery.trim()) return [];
    const q = searchQuery.toLowerCase();
    return messages
      .filter((m) => typeof m.content === "string" && m.content.toLowerCase().includes(q))
      .map((m) => m.id);
  }, [messages, searchQuery, searchOpen]);

  // Scroll the current match into view whenever it changes. The wrapper
  // ref keyed by msg.id is populated by the message render loop below.
  useEffect(() => {
    if (searchMatchedIds.length === 0) return;
    const id = searchMatchedIds[Math.min(currentMatchIdx, searchMatchedIds.length - 1)];
    const el = messageWrapperRefs.current.get(id);
    if (el) el.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [currentMatchIdx, searchMatchedIds]);

  // Highlight matched substrings inside the rendered messages using the
  // CSS Custom Highlight API. This is the only way to paint over the
  // already-rendered markdown without re-parenting React nodes — we walk
  // the text nodes of each matching message's DOM and register Ranges
  // with the browser. CSS rules below pick up `hive-search-match` and
  // `hive-search-current` to style the spans without touching markup.
  //
  // Re-runs on every keystroke / step / new message so streaming text
  // gets highlighted in flight. The `messages` dep also covers the case
  // where new bubbles appear while the search overlay is open.
  useEffect(() => {
    type HighlightCtor = new (...ranges: Range[]) => unknown;
    interface HighlightRegistry { set(name: string, value: unknown): void; delete(name: string): void; }
    const cssWithHighlights = CSS as unknown as { highlights?: HighlightRegistry };
    const HighlightClass = (window as unknown as { Highlight?: HighlightCtor }).Highlight;
    if (!cssWithHighlights.highlights || !HighlightClass) return;
    if (!searchOpen || !searchQuery.trim() || searchMatchedIds.length === 0) {
      cssWithHighlights.highlights.delete("hive-search-match");
      cssWithHighlights.highlights.delete("hive-search-current");
      return;
    }
    const q = searchQuery.toLowerCase();
    const currentId = searchMatchedIds[Math.min(currentMatchIdx, searchMatchedIds.length - 1)];
    const otherRanges: Range[] = [];
    const currentRanges: Range[] = [];
    for (const id of searchMatchedIds) {
      const wrapper = messageWrapperRefs.current.get(id);
      if (!wrapper) continue;
      const walker = document.createTreeWalker(wrapper, NodeFilter.SHOW_TEXT);
      let node: Node | null;
      const target = id === currentId ? currentRanges : otherRanges;
      while ((node = walker.nextNode())) {
        const text = node.nodeValue ?? "";
        if (!text) continue;
        const lower = text.toLowerCase();
        let idx = 0;
        while ((idx = lower.indexOf(q, idx)) !== -1) {
          const range = document.createRange();
          range.setStart(node, idx);
          range.setEnd(node, idx + q.length);
          target.push(range);
          idx += q.length;
        }
      }
    }
    cssWithHighlights.highlights.set("hive-search-match", new HighlightClass(...otherRanges));
    cssWithHighlights.highlights.set("hive-search-current", new HighlightClass(...currentRanges));
    return () => {
      cssWithHighlights.highlights?.delete("hive-search-match");
      cssWithHighlights.highlights?.delete("hive-search-current");
    };
  }, [searchOpen, searchQuery, searchMatchedIds, currentMatchIdx, messages]);

  useEffect(() => {
    if (!initialDraft || initialDraft === lastAppliedDraftRef.current) return;
    lastAppliedDraftRef.current = initialDraft;
    setInput(initialDraft);
    setTimeout(() => {
      editorRef.current?.focus();
    }, 0);
  }, [initialDraft]);

  // Attach files staged before this session existed (see lib/composerHandoff).
  // Routed through `ingestFiles` rather than straight into `pendingImages` so
  // the size/count/type rules apply exactly as they do to a picked file — a
  // handoff is a convenience, not a way past validation.
  useEffect(() => {
    if (!initialAttachments?.length) return;
    if (initialAttachments === lastAppliedAttachmentsRef.current) return;
    lastAppliedAttachmentsRef.current = initialAttachments;
    setHandoffIngested(false);
    void ingestFiles(initialAttachments).finally(() => setHandoffIngested(true));
    // ingestFiles is a stable closure over state it reads via setState updaters.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialAttachments]);

  // Send a handed-over draft on the user's behalf, once there is actually
  // somewhere to send it: the session exists, the queen is ready, and any
  // handed-over files have finished ingesting. Guarded by a one-shot token so a
  // re-render (or a re-run of this effect as those conditions settle) can never
  // send twice — and skipped outright when no token was passed, which is every
  // ordinary conversation.
  useEffect(() => {
    if (autoSendToken == null || autoSentTokenRef.current === autoSendToken) return;
    if (!sessionId || disabled || sendLocked || paymentLocked) return;
    if (initialAttachments?.length && !handoffIngested) return;
    if (!input.trim() && pendingImages.length === 0) return;
    autoSentTokenRef.current = autoSendToken;
    void handleSubmit({ preventDefault: () => {} } as React.FormEvent);
    // handleSubmit is redefined every render; the token ref is what makes this
    // one-shot, not the dep list.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    autoSendToken,
    sessionId,
    disabled,
    sendLocked,
    paymentLocked,
    handoffIngested,
    initialAttachments,
    input,
    pendingImages,
  ]);

  // Mirror the live draft into the module-level store on every change so it is
  // preserved when ChatPanel unmounts during navigation.
  useEffect(() => {
    draftStore.set(draftKeyRef.current, input);
  }, [input]);

  // Thread changed while ChatPanel stays mounted (e.g. switching colonies in
  // place): stash the outgoing draft and load the incoming one.
  useEffect(() => {
    if (draftKeyRef.current === draftKey) return;
    const prev = draftKeyRef.current;
    draftKeyRef.current = draftKey;
    // Staged attachments belong to the outgoing thread — clear them so the
    // colony-A file chip doesn't linger in colony B's composer and get
    // uploaded into (and injected into the queen prompt of) the wrong session.
    // The draft *text* is swapped per-thread below; attachments have no such
    // per-thread store, so they must be dropped on switch.
    setPendingImages([]);
    setUploadError(null);
    setUploadingFiles([]);
    // activeThread wasn't resolved yet on the previous render (key like
    // "::id") — adopt whatever the user already typed instead of wiping it.
    if (prev.startsWith("::") && input) {
      draftStore.set(draftKey, input);
      return;
    }
    draftStore.set(prev, input);
    setInput(draftStore.get(draftKey) ?? "");
  }, [draftKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const allThreadMessages = messages
    .filter((m) => {
      if (m.type === "system" && !m.thread) return false;
      if (m.thread !== activeThread) return false;
      // Hide queen messages whose content is whitespace-only — these are
      // tool-use-only turns that have no visible text.  During live operation
      // tool pills provide context, but on resume the pills are gone so
      // the empty bubble is meaningless.
      if (m.role === "queen" && !m.type && (!m.content || !m.content.trim()))
        return false;
      return true;
    })
    // Sort by createdAt — the lazy window (tail slice), the day dividers,
    // and the render grouping below all assume chronological order. Never
    // trust the caller to hand us a sorted array: a forked-session restore
    // racing the live SSE re-subscribe can yield an unsorted `messages`,
    // and an unsorted slice renders the transcript out of order. Sort is
    // stable, so a tool-pill batch sharing one createdAt keeps its order.
    .sort((a, b) => (a.createdAt ?? 0) - (b.createdAt ?? 0));
  // Restrict the rendered window to the most recent messages; reveal older
  // history on scroll-up and via auto-fill (keeps initial paint fast on
  // long conversations and prevents a stuck "Loading older messages…"
  // indicator when the recent turn renders shorter than the viewport).
  const { hiddenOlderCount, hasMoreOlder, loadOlderStep } = useLazyHistoryWindow({
    scrollRef,
    bottomSpacerRef,
    stickToBottomRef: stickToBottom,
    resetKey: `${sessionId} ${activeThread}`,
    totalMessages: allThreadMessages.length,
    historyTimeline,
    expandedHistoryDays,
    onToggleHistoryDay,
    expandedHistorySessions,
    onToggleHistorySession,
    historySessionMessages,
    currentSessionHasMoreOlder,
    onFetchOlderPage,
    historySessionHasMoreOlder,
    onFetchOlderPageForSession,
  });
  const threadMessages = hiddenOlderCount > 0
    ? allThreadMessages.slice(hiddenOlderCount)
    : allThreadMessages;

  // TRACE: what ChatPanel actually renders. Compares the incoming
  // `messages` prop against the windowed slice, so the trace file tells
  // a data-loss (allThreadMessages itself short) apart from a windowing
  // artefact (full data, but hiddenOlderCount keeps the middle off-screen).
  useEffect(() => {
    traceLoad("ChatPanel", "render window", {
      activeThread,
      propMessages: messages.length,
      allThreadMessages: allThreadMessages.length,
      hiddenOlderCount,
      visible: msgSummary(threadMessages),
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    messages.length,
    allThreadMessages.length,
    threadMessages.length,
    hiddenOlderCount,
    activeThread,
  ]);

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
    | { kind: "day_divider"; key: string; createdAt: number }
    | {
        /** Consecutive tool_status messages collapsed into one render
         * unit so their pills share lines via flex-wrap, instead of
         * each message becoming its own block-level row. The merge is
         * purely a render-time concern; the underlying ChatMessage
         * objects stay separate so future events still upsert by id. */
        kind: "tool_status_group";
        key: string;
        messages: ChatMessage[];
        createdAt: number;
      };

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
    // Toggle `window.__hiveDebugRender = true` in DevTools to dump the
    // worker_run grouping trace for the next re-render. One-shot: the
    // flag is read here, not stored, so the dump fires per render that
    // happens while it's true. Goes to console.debug (not log) so it
    // doesn't show up in production noise unless filtered for.
    const debug = (window as unknown as { __hiveDebugRender?: boolean })
      .__hiveDebugRender === true;
    const dbg = (event: string, data?: unknown) => {
      if (debug) console.debug(`[renderItems] ${event}`, data ?? "");
    };
    if (debug) {
      dbg("threadMessages", threadMessages.map((m, k) => ({
        k,
        id: m.id,
        role: m.role,
        type: m.type,
        streamId: m.streamId,
        nodeId: m.nodeId,
        contentPreview: (m.content ?? "").slice(0, 60),
        createdAt: m.createdAt,
      })));
    }
    const items: RenderItem[] = [];
    // Per-stream lookup so a worker continuing to emit across a queen-text
    // break lands in the SAME bubble instead of fragmenting. Reset on
    // run_divider so distinct logical runs stay separate.
    let workerRunByStream = new Map<
      string,
      Extract<RenderItem, { kind: "worker_run" }>
    >();
    let i = 0;
    while (i < threadMessages.length) {
      const msg = threadMessages[i];
      const isSubagent = msg.nodeId?.includes(":subagent:");
      if (msg.type === "run_divider") {
        // Distinct logical run — anything that follows must NOT merge
        // back into the worker_run we built for the previous run_id.
        workerRunByStream = new Map();
      }

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
        const interleavedUsers: ChatMessage[] = [];
        const interleavedQueenTools: ChatMessage[] = [];
        const firstWorkerMsg = msg;
        dbg("worker_run open", { startIdx: i, firstId: msg.id, role: msg.role, type: msg.type, streamId: msg.streamId });

        while (i < threadMessages.length) {
          const m = threadMessages[i];

          // Hard boundary — only run_divider ends a worker run.
          // User messages are queen-bound and transparent to workers.
          if (m.type === "run_divider") { dbg("worker_run break run_divider", { idx: i, id: m.id }); break; }
          // Queen message with real text — boundary (queen is talking
          // to the user, not just emitting a tool)
          if (m.role === "queen" && m.content?.trim() && !m.type) { dbg("worker_run break queen-text", { idx: i, id: m.id, contentPreview: m.content.slice(0, 60) }); break; }
          // Trigger banner — scheduler/webhook fire marking a new
          // queen turn. Must not fold into a stale worker run that
          // happens to precede it (see also MessageBubble's
          // ``type === "trigger"`` render at the amber banner).
          if (m.type === "trigger") { dbg("worker_run break trigger", { idx: i, id: m.id }); break; }
          // Other session-wide banners: colony link, inherited block,
          // system notices — none of these belong inside a worker run.
          if (
            m.type === "colony_link" ||
            m.type === "inherited_block" ||
            m.type === "system"
          ) { dbg("worker_run break banner", { idx: i, id: m.id, type: m.type }); break; }
          // Subagent message — different group type, stop here
          if (m.nodeId?.includes(":subagent:")) { dbg("worker_run break subagent", { idx: i, id: m.id, nodeId: m.nodeId }); break; }

          // Queen tool_status — not a worker activity, but also not a
          // hard boundary: the queen's own tool calls (e.g. asking the
          // user a question, scheduling a trigger) routinely fire
          // between worker deltas, and treating each as a break
          // shatters one logical worker run into N tiny bubbles. Keep
          // these aside and emit them as standalone pills after the
          // bubble so the worker run stays aggregated.
          if (m.type === "tool_status" && m.role === "queen") {
            interleavedQueenTools.push(m);
            i++;
            continue;
          }

          // Queen reasoning row — same treatment: the queen's thinking is
          // part of the queen↔user thread, not worker activity. Keep aside
          // so it renders standalone instead of folding into the worker card.
          if (m.type === "reasoning" && m.role === "queen") {
            interleavedQueenTools.push(m);
            i++;
            continue;
          }

          // User messages are queen-bound — skip without breaking
          // the worker run so subsequent deltas stay in the same bubble.
          if (m.type === "user") {
            interleavedUsers.push(m);
            i++;
            continue;
          }

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
          dbg("worker_run close", {
            workerMsgsCount: workerMsgs.length,
            interleavedQueenToolsCount: interleavedQueenTools.length,
            interleavedUsersCount: interleavedUsers.length,
            streamIds: Array.from(new Set(workerMsgs.map((m) => m.streamId ?? "<none>"))),
          });
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
              // Same worker continuing across a queen-text break: append
              // to its existing bubble in items[] so the bubble shows the
              // worker's full activity, instead of spawning a second
              // bubble for the same streamId.
              const existing = workerRunByStream.get(streamKey);
              if (existing) {
                existing.group.messages.push(...bucketMsgs);
                continue;
              }
              const item: Extract<RenderItem, { kind: "worker_run" }> = {
                kind: "worker_run",
                runId: `wrun-${firstWorkerMsg.id}-${streamKey}`,
                group: { messages: bucketMsgs },
                label: deriveWorkerLabel(streamKey, bucketMsgs),
              };
              items.push(item);
              workerRunByStream.set(streamKey, item);
            }
          } else {
            // Single-bubble case (legacy ``streamId="worker"`` or no
            // streamId at all). Key by streamId when present so the same
            // worker's continuation merges; fall back to a fixed key
            // ("worker") so the legacy stream behaves the same way.
            const streamKey = workerMsgs[0]?.streamId || "worker";
            const existing = workerRunByStream.get(streamKey);
            if (existing) {
              existing.group.messages.push(...workerMsgs);
            } else {
              const item: Extract<RenderItem, { kind: "worker_run" }> = {
                kind: "worker_run",
                runId: `wrun-${firstWorkerMsg.id}`,
                group: { messages: workerMsgs },
              };
              items.push(item);
              workerRunByStream.set(streamKey, item);
            }
          }
        }
        // Emit queen tool pills that fired between worker deltas as
        // standalone items so they render outside (not inside) the
        // bubble — same trade-off as interleavedUsers below.
        for (const qt of interleavedQueenTools) {
          items.push({ kind: "message", msg: qt });
        }
        // Emit queen-bound user messages that were interleaved
        // with worker deltas so they still render in the chat.
        for (const um of interleavedUsers) {
          items.push({ kind: "message", msg: um });
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
    if (debug) {
      dbg("items", items.map((it, k) => {
        if (it.kind === "worker_run") {
          return {
            k,
            kind: it.kind,
            runId: it.runId,
            label: it.label,
            msgCount: it.group.messages.length,
            streamIds: Array.from(new Set(it.group.messages.map((m) => m.streamId ?? "<none>"))),
          };
        }
        if (it.kind === "message") {
          return {
            k,
            kind: it.kind,
            id: it.msg.id,
            role: it.msg.role,
            type: it.msg.type,
            streamId: it.msg.streamId,
          };
        }
        return { k, kind: it.kind };
      }));
    }
    return items;
  }, [threadMessages, contextUsage]);

  // Inject day-separator dividers between items that cross a calendar-day
  // boundary, and one before the very first item. Helps the user see when
  // activity resumed after a gap — important since some answers take hours.
  const RECENT_DAYS_VISIBLE = 1;
  // Days whose messages are currently rendered. The most recent day(s) are
  // included implicitly via `recentChatDays`; older days are added here as
  // their dividers scroll into view (lazy load on scroll, Slack-style).
  const [revealedDays, setRevealedDays] = useState<Set<string>>(new Set());

  // Reset revealed days when switching sessions (sessionId changes)
  useEffect(() => {
    setRevealedDays(new Set());
  }, [sessionId]);

  // Per-message thumbs-up/down votes for the active session. Keyed by
  // ChatMessage.id; hydrated from hive-backend on session change. The
  // map lives at the panel level so every queen bubble's FeedbackBtns
  // can be seeded without each one fetching independently.
  const [feedbackVotes, setFeedbackVotes] = useState<Record<string, Vote>>(
    {},
  );
  useEffect(() => {
    // Votes were hydrated from the cloud feedback store (removed). Buttons
    // still work as local UI, so start each session with an empty map.
    setFeedbackVotes({});
  }, [sessionId]);

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
    const makeDayKey = (ts: number) => {
      const d = new Date(ts);
      return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
    };
    const out: RenderItem[] = [];
    let lastDay: string | null = null;
    for (const item of renderItems) {
      const ts = getTime(item);
      if (ts) {
        const key = makeDayKey(ts);
        if (key !== lastDay) {
          out.push({ kind: "day_divider", key: `day-${ts}`, createdAt: ts });
          lastDay = key;
        }
      }
      // Merge consecutive tool_status messages into a single render
      // unit so their pills share lines via flex-wrap. Without this,
      // each tool_status message is its own block-level row even when
      // adjacent — visually each tool stacks on its own line.
      if (item.kind === "message" && item.msg.type === "tool_status") {
        const last = out[out.length - 1];
        if (last && last.kind === "tool_status_group") {
          last.messages.push(item.msg);
          continue;
        }
        out.push({
          kind: "tool_status_group",
          key: `tsg-${item.msg.id}`,
          messages: [item.msg],
          createdAt: item.msg.createdAt ?? 0,
        });
        continue;
      }
      out.push(item);
    }
    return out;
  }, [renderItems]);

  // ID of the most recent queen message that renders the standard queen
  // bubble (i.e., has the name/title row where the spinner lives). Queen
  // messages with a `type` (tool_status, trigger, run_divider, system,
  // colony_link, inherited_block) short-circuit MessageBubble before the
  // spinner JSX, so attaching `isQueenBusy` to them would render no spinner.
  const lastQueenMessageId = useMemo<string | null>(() => {
    for (let i = itemsWithDividers.length - 1; i >= 0; i--) {
      const item = itemsWithDividers[i];
      if (item.kind === "message" && item.msg.role === "queen" && !item.msg.type) {
        return item.msg.id;
      }
    }
    return null;
  }, [itemsWithDividers]);

  // Key of the newest tool block. Only that one may render live actions (the
  // reveal card's campaign-import buttons) — an older card would keep asking a
  // question the user already answered further down the transcript.
  const latestToolGroupKey = useMemo<string | null>(() => {
    for (let i = itemsWithDividers.length - 1; i >= 0; i--) {
      const item = itemsWithDividers[i];
      if (item.kind === "tool_status_group") return item.key;
    }
    return null;
  }, [itemsWithDividers]);

  // Send a message as the user, from a widget rendered in the transcript —
  // the same treatment InlineAskUserBubble gives an answered ask_user.
  const handleQuickReply = (text: string) => onSend(text, activeThread);

  // Determine which days are "recent" (last N unique days — always visible)
  const recentChatDays = useMemo(() => {
    const uniqueDays: string[] = [];
    for (let i = itemsWithDividers.length - 1; i >= 0; i--) {
      const item = itemsWithDividers[i];
      if (item.kind === "day_divider") {
        const dk = item.key;
        if (!uniqueDays.includes(dk)) uniqueDays.push(dk);
      }
    }
    // uniqueDays is newest-first; take the last N
    return new Set(uniqueDays.slice(0, RECENT_DAYS_VISIBLE));
  }, [itemsWithDividers]);

  // Lazy-reveal older days as their dividers scroll into view (Slack-style).
  // Each unrevealed older divider carries a `data-day-key` attribute; the
  // observer fires on intersection and adds the key to `revealedDays`. A
  // 200px rootMargin starts the reveal slightly before the divider is fully
  // visible so the content slide-in feels continuous rather than abrupt.
  useEffect(() => {
    const root = scrollRef.current;
    if (!root) return;
    const observer = new IntersectionObserver(
      (entries) => {
        const newKeys: string[] = [];
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          const key = (entry.target as HTMLElement).dataset.dayKey;
          if (key) newKeys.push(key);
        }
        if (newKeys.length === 0) return;
        setRevealedDays((prev) => {
          const next = new Set(prev);
          for (const k of newKeys) next.add(k);
          return next.size === prev.size ? prev : next;
        });
      },
      { root, rootMargin: "200px 0px" },
    );
    const targets = root.querySelectorAll("[data-day-key]");
    targets.forEach((t) => observer.observe(t));
    return () => observer.disconnect();
  }, [itemsWithDividers, revealedDays]);

  // Mark current thread as read
  useEffect(() => {
    const count = messages.filter((m) => m.thread === activeThread).length;
    setReadMap((prev) => ({ ...prev, [activeThread]: count }));
  }, [activeThread, messages]);

  // Suppress unused var
  void readMap;

  // Slack/Teams-style "jump to latest" pill visibility. Reactive (state, not
  // ref) so the button mounts/unmounts as the user scrolls. Threshold is
  // three full viewport heights — the user has to be clearly deep into
  // history (not just a screen or two back) before the pill appears.
  const [showJumpToLatest, setShowJumpToLatest] = useState(false);

  // Autoscroll: only when user is already near the bottom
  const handleScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    // Did the *user* just scroll up? A decrease in scrollTop with a
    // non-shrinking content height is the one thing no programmatic
    // scroll in this component produces (see prevScrollRef).
    const prev = prevScrollRef.current;
    const userScrolledUp =
      el.scrollTop < prev.top && el.scrollHeight >= prev.height;
    prevScrollRef.current = { top: el.scrollTop, height: el.scrollHeight };

    const distFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    // A genuine upward scroll always unsticks. Proximity alone can't
    // decide it: when the rendered window is short, its top still sits
    // within the 80px bottom band, so `distFromBottom < 80` cannot tell
    // "parked at the bottom" apart from "scrolled up to read history".
    // Treating that as stuck is what snapped the viewport back to the
    // bottom on every lazy-load.
    stickToBottom.current = userScrolledUp ? false : distFromBottom < 80;
    setShowJumpToLatest((cur) => {
      const next = distFromBottom > el.clientHeight * 3;
      return cur === next ? cur : next;
    });
    // Lazy-load older history when the user scrolls up near the top. The
    // direction check matters: a programmatic re-pin to the bottom also
    // lands within 240px of the top in a short window, and loading (plus
    // unsticking) off that would detach the user from a live stream.
    if (userScrolledUp && el.scrollTop < 240) {
      loadOlderStep();
    }
  };

  // Scroll the container to the very bottom. The previous implementation
  // scrolled to the TOP of the last message (block: "start") so long
  // queen replies opened "with their first words visible". That was
  // clever in the static case but unreliable in three common ones: a
  // streaming reply whose target keeps moving as content grows; a tool
  // pill landing whose target sits with empty space below; an async
  // image load that reflows after the scroll fires. Users feel this as
  // "doesn't jump to latest reliably". Direct scrollTop = scrollHeight
  // is atomic, can't be cancelled, and always lands at the bottom.
  //
  // Smooth animations are reserved for the user-initiated "Jump to
  // latest" button — under streaming, smooth is interrupted by every
  // subsequent call and never reaches the bottom.
  const scrollToBottom = (behavior: ScrollBehavior = "auto") => {
    const root = scrollRef.current;
    if (!root) return;
    if (behavior === "smooth") {
      bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
      return;
    }
    root.scrollTop = root.scrollHeight;
    // Re-pin on the next frame to catch late layout (image decode,
    // markdown tables, code-block syntax highlighting, screenshot
    // tool pills). Without this, a screenshot landing 50ms after the
    // text stream completes leaves the user 600px above the bottom.
    requestAnimationFrame(() => {
      const r = scrollRef.current;
      if (r) r.scrollTop = r.scrollHeight;
    });
  };
  // Back-compat shim for the existing "Jump to latest" button.
  const scrollToLatest = (behavior: ScrollBehavior) => scrollToBottom(behavior);

  // Re-pin to bottom whenever the user switches queens/threads or the page
  // (re)mounts. justSwitchedRef survives across renders until messages
  // actually populate, so the instant-scroll fires once content lands —
  // not on the first empty render before the API/SSE payload arrives.
  const justSwitchedRef = useRef(true);
  // Last user message we've already scrolled for, so an arriving user
  // message re-pins exactly once (and a re-render mid-stream doesn't).
  const lastUserMsgIdRef = useRef<string | null>(null);
  useLayoutEffect(() => {
    stickToBottom.current = true;
    justSwitchedRef.current = true;
    lastUserMsgIdRef.current = null;
    // Drop the previous thread's scroll baseline so the first scroll
    // event here isn't misread as a user scroll-up against stale numbers.
    prevScrollRef.current = { top: 0, height: 0 };
    // Reset the bottom spacer — last thread's gap shouldn't carry over.
    if (bottomSpacerRef.current) bottomSpacerRef.current.style.height = "0px";
  }, [sessionId, activeThread]);

  // Re-pin whenever the scroll container's content height grows AND
  // the user is sticking to bottom. Catches:
  //   • streaming text bubbles whose height grows mid-render
  //   • tool pills with images that decode asynchronously
  //   • markdown blocks (tables, code) that re-flow after first paint
  // Without this observer, scrollToBottom fires once at message-arrival
  // time but the height is still growing for ~100–500ms after — the
  // user lands above the new content and stays there.
  useEffect(() => {
    const root = scrollRef.current;
    if (!root) return;
    let lastHeight = root.scrollHeight;
    const observer = new ResizeObserver(() => {
      if (!stickToBottom.current) return;
      const h = root.scrollHeight;
      // Only re-pin on growth — a shrink (e.g. a deleted bubble)
      // shouldn't yank the user.
      if (h > lastHeight) {
        root.scrollTop = h;
      }
      lastHeight = h;
    });
    // Observe every direct child so any growth bubbles up.  Re-walking
    // children on each MutationObserver firing keeps coverage current
    // for newly-inserted message bubbles.
    const attach = () => {
      observer.disconnect();
      lastHeight = root.scrollHeight;
      for (const child of Array.from(root.children)) {
        observer.observe(child);
      }
    };
    attach();
    const mut = new MutationObserver(attach);
    mut.observe(root, { childList: true });
    return () => {
      observer.disconnect();
      mut.disconnect();
    };
  }, []);

  // Single source of truth for autoscroll. Runs after every render that
  // could change content height. Always uses instant scroll — under
  // streaming, smooth is repeatedly interrupted and never lands.
  //
  // Dependency note: depending on `threadMessages` directly would re-fire
  // this effect on every parent re-render (e.g. every keystroke in the
  // composer, since `setInput` re-renders ChatPanel and `messages.filter`
  // produces a fresh array). Instead we collapse the meaningful signals
  // into a string scalar that only changes when content actually changes:
  // message count, last message id (new turn), and last message content
  // length (streaming progress).
  const lastMsg = threadMessages[threadMessages.length - 1];
  const scrollSignal = `${threadMessages.length}:${lastMsg?.id ?? ""}:${lastMsg?.content?.length ?? 0}:${pendingQuestions?.length ?? 0}`;
  useLayoutEffect(() => {
    // Collapse any spacer height left over from useLazyHistoryWindow's
    // scroll-anchoring once new content lands — otherwise a freshly arrived
    // message or typing bubble floats above a stale empty gap.
    if (!justSwitchedRef.current && bottomSpacerRef.current) {
      bottomSpacerRef.current.style.height = "0px";
    }
    // A message *from the user* always re-pins the viewport, even if they'd
    // scrolled up into history. Covers prompts injected from outside the
    // composer — "Update plan" in the task rail, Sentinel setup — which
    // otherwise land below the fold with no sign anything happened.
    const lastUserId = lastMsg?.type === "user" ? lastMsg.id : null;
    if (
      lastUserId &&
      lastUserId !== lastUserMsgIdRef.current &&
      !justSwitchedRef.current
    ) {
      stickToBottom.current = true;
      setShowJumpToLatest(false);
    }
    if (lastUserId) lastUserMsgIdRef.current = lastUserId;
    if (!stickToBottom.current) return;
    // First content lands after a session/colony switch — pin the BOTTOM
    // of the latest queen-bee message flush against the input box. The
    // previous behavior pinned the TOP of the last wrapper, which left the
    // queen's closing words off-screen with a viewport-sized gap above the
    // input. Worker / tool rows that follow the queen's reply still live
    // in the DOM but sit below the viewport — the user can scroll down to
    // reveal them. lastQueenMessageId already filters out tool_status,
    // dividers, etc., so it lands on a bubble with a real header.
    if (justSwitchedRef.current && threadMessages.length > 0) {
      const root = scrollRef.current;
      const last = lastQueenMessageId && root
        ? root.querySelector<HTMLElement>(`[data-message-id="${CSS.escape(lastQueenMessageId)}"]`)
        : null;
      if (last && root) {
        const desired =
          last.offsetTop - root.offsetTop + last.offsetHeight - root.clientHeight;
        // Clamp: when the queen reply is shorter than the viewport, desired
        // goes negative and there's no scroll range to honor — let the
        // message sit at the natural top.
        root.scrollTop = Math.max(0, desired);
        justSwitchedRef.current = false;
        stickToBottom.current = false;
        return;
      }
    }
    scrollToBottom("auto");
    if (threadMessages.length > 0) justSwitchedRef.current = false;
    // threadMessages length is captured via scrollSignal — safe to read here.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scrollSignal, isWaiting, sessionId, activeThread]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() && pendingImages.length === 0) return;

    // Check subscription FIRST so input + attachments stay intact when
    // the upgrade popup is shown. Otherwise the user loses their typed
    // message and uploaded files when they dismiss the popup.
    // Separate files (PDFs, CSVs, text — need multipart upload) from images (send as data URIs)
    const files = pendingImages.filter((img) => img._file);
    const images = pendingImages.filter((img) => !img._file);

    // Upload files first. We keep `extracted_text` on each ImageContent
    // for chip preview UX, but the backend (handle_chat) is now the
    // single owner of attachment→queen-text injection — Layer F1.
    // Frontend no longer prepends `extracted_text` to queenText.
    const filePageImages: ImageContent[] = [];
    const uploadedFiles: ImageContent[] = [];
    const uploadErrors: string[] = [];
    if (files.length > 0 && sessionId) {
      for (const f of files) {
        const tag = f._fileName || "file";
        setUploadingFiles((prev) => [...prev, tag]);
        try {
          const file = f._bytes
            ? new File([f._bytes], f._file!.name, { type: f._file!.type })
            : f._file!;
          const result = await executionApi.uploadAttachment(sessionId, file);
          // Display ImageContent uses the canonical `hive-attachment://`
          // scheme — Layer F2. AttachmentChip's resolveAttachmentUrl
          // produces the fetchable /api/sessions/{sid}/attachment/{name}
          // URL at render time. Single source of truth for "where the
          // file lives" across submit + replay + persistence.
          const refUrl = result.path
            ? `hive-attachment://${result.path}`
            : "file-uploaded";
          uploadedFiles.push({
            type: "image_url",
            image_url: { url: refUrl },
            _fileName: f._fileName || result.original_name,
            _extractedText: result.extracted_text || undefined,
          });
          // Same canonical ref goes into the LLM payload. Runtime resolves
          // it to a file block (PDF), image_url block (image), or CSV/text
          // text-prepend at handle_chat time.
          if (result.path) {
            filePageImages.push({
              type: "image_url",
              image_url: { url: `hive-attachment://${result.path}` },
            });
          }
        } catch (err) {
          const msg = err instanceof Error ? err.message : String(err);
          console.error("[ChatPanel] file upload failed:", err);
          uploadErrors.push(
            `${f._fileName || "file"}: upload failed — ${msg}`,
          );
        } finally {
          // Remove ONE matching entry (not all) so duplicate filenames in
          // the batch each clear individually as they finish.
          setUploadingFiles((prev) => {
            const next = [...prev];
            const i = next.indexOf(tag);
            if (i !== -1) next.splice(i, 1);
            return next;
          });
        }
      }
    }
    if (uploadErrors.length > 0) {
      setUploadError(uploadErrors.join(" "));
      // Don't send a partial message when every attachment failed and
      // there's no other content the queen could act on.
      if (uploadedFiles.length === 0 && images.length === 0 && !input.trim()) {
        return;
      }
    } else {
      setUploadError(null);
    }

    // Layer F1: backend owns attachment→queen-text injection. The user
    // sees and the queen sees the SAME text — handle_chat extracts and
    // prepends server-side. Frontend just passes the typed message.
    // Collapse any `{{label::value}}` placeholder pills to their values (and
    // remember them) so the agent receives the real text.
    cachePlaceholderValues(collectPlaceholderValues(input));
    const userText = resolvePlaceholders(input.trim());
    const fileNames = files.map((f) => f._fileName || "file").filter(Boolean);

    // When the user attached files but typed nothing, show the file
    // names as chips so the bubble doesn't look empty.
    const displayText = fileNames.length > 0 && !userText
      ? fileNames.map((n) => `[${n}]`).join(" ")
      : userText;
    // Always carry a displayMessage when there's ANY attachment. The
    // server echoes `display_message` in CLIENT_INPUT_RECEIVED rather
    // than the full augmented `message` (which would carry the
    // `[Attachments]` system-reminder + extracted text appended by
    // handle_chat). Without this, the echoed event content differs from
    // the optimistic bubble's content and the queen-dm reconciler
    // (queen-dm.tsx ~line 486) duplicates the user bubble.
    const hasAttachments = fileNames.length > 0 || images.length > 0;
    const useDisplayMessage = hasAttachments;

    // Images sent to the LLM: actual user images + canonical `hive-attachment://`
    // refs (Layer F2). Backend resolves refs and emits provider-native blocks.
    const llmImages = [...images.map(({ type, image_url }) => ({ type, image_url })), ...filePageImages];
    const cleanImages = llmImages.length > 0 ? llmImages : undefined;

    // Images shown in the chat bubble: user images + uploaded file chips (for display)
    const displayImages = [...images, ...uploadedFiles];

    // Skills now live inline in the message as <read_skill> markers (authored
    // in the editor / loaded from a prompt). They go to the agent as-is and the
    // bubble renders them as chips via SkillMarkerText — so no separate steering
    // pass and no display/LLM split is needed except for attachment chips.
    const llmText = userText;
    const finalDisplayMessage = useDisplayMessage ? displayText : undefined;

    onSend(
      llmText,
      activeThread,
      cleanImages,
      finalDisplayMessage,
      displayImages.length > 0 ? displayImages : undefined,
    );
    setInput("");
    setPendingImages([]);
  };

  // Core attachment ingestion — shared by the file picker, drag-and-drop, and
  // image paste. Validates the whole batch (kind, size, count, total bytes)
  // against the current pending state, then commits the survivors. Any
  // rejected files surface a combined error string.
  const ingestFiles = async (files: File[]) => {
    if (files.length === 0) return;

    setUploadError(null);
    const errors: string[] = [];
    // Snapshot of the current pending state so we can validate the whole
    // batch before committing. setPendingImages with a function would be
    // racy across the awaited FileReader calls below.
    let runningCount = pendingImages.length;
    let runningBytes = pendingImages.reduce(
      (sum, p) => sum + (p._byteSize ?? 0),
      0,
    );
    const additions: ImageContent[] = [];

    for (const file of files) {
      const kind = classifyAttachment(file);
      const sizeError = checkAttachmentSize(file, kind);
      if (sizeError) {
        errors.push(sizeError);
        continue;
      }
      if (runningCount + 1 > UPLOAD_LIMITS.maxAttachments) {
        errors.push(
          `${file.name}: max ${UPLOAD_LIMITS.maxAttachments} attachments per message.`,
        );
        continue;
      }
      if (runningBytes + file.size > UPLOAD_LIMITS.maxTotalBytes) {
        errors.push(
          `${file.name}: combined attachment size would exceed ${formatBytes(UPLOAD_LIMITS.maxTotalBytes)}.`,
        );
        continue;
      }

      if (kind === "pdf" || kind === "csv" || kind === "text" || kind === "file") {
        // Read bytes eagerly — on macOS the security-scoped file access
        // granted during the picker can expire before the user submits.
        const bytes = await file.arrayBuffer();
        additions.push({
          type: "image_url",
          image_url: { url: "file-pending" },
          _fileName: file.name,
          _file: file,
          _bytes: bytes,
          _byteSize: file.size,
        });
      } else if (kind === "image") {
        // Read the original file at full resolution — no compression.
        // The backend saves the original to disk and the LLM vision
        // fallback handles any resizing it needs internally.
        const dataUrl = await new Promise<string>((resolve) => {
          const r = new FileReader();
          r.onload = (ev) => resolve(ev.target?.result as string);
          r.readAsDataURL(file);
        });
        additions.push({
          type: "image_url",
          image_url: { url: dataUrl },
          _fileName: file.name,
          _byteSize: file.size,
        });
      }
      runningCount += 1;
      runningBytes += file.size;
    }

    if (additions.length > 0) {
      setPendingImages((prev) => [...prev, ...additions]);
    }
    if (errors.length > 0) {
      setUploadError(errors.join(" "));
    }
  };

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? []);
    // Reset so the same file can be re-selected.
    e.target.value = "";
    await ingestFiles(files);
  };

  // Drag-and-drop onto the composer. Uses a depth counter because dragenter/
  // dragleave also fire when the cursor crosses child elements; clearing the
  // overlay only at depth 0 keeps it from flickering mid-drag.
  const handleDragEnter = (e: React.DragEvent) => {
    if (disabled || !e.dataTransfer.types.includes("Files")) return;
    e.preventDefault();
    dragDepth.current += 1;
    setIsDragOver(true);
  };
  const handleDragOver = (e: React.DragEvent) => {
    if (disabled || !e.dataTransfer.types.includes("Files")) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "copy";
  };
  const handleDragLeave = (e: React.DragEvent) => {
    if (!e.dataTransfer.types.includes("Files")) return;
    dragDepth.current = Math.max(0, dragDepth.current - 1);
    if (dragDepth.current === 0) setIsDragOver(false);
  };
  const handleDrop = (e: React.DragEvent) => {
    if (disabled) return;
    const files = Array.from(e.dataTransfer.files ?? []);
    if (files.length === 0) return;
    e.preventDefault();
    dragDepth.current = 0;
    setIsDragOver(false);
    void ingestFiles(files);
  };

  // Image paste (e.g. a screenshot from the clipboard). The SkillTextEditor
  // owns text paste and preventDefaults it, but doesn't stopPropagation, so
  // this container handler still sees image files. Only act when the clipboard
  // actually carries files — otherwise let normal text paste through.
  const handlePasteFiles = (e: React.ClipboardEvent) => {
    if (disabled) return;
    const files = Array.from(e.clipboardData.files ?? []);
    if (files.length === 0) return;
    e.preventDefault();
    void ingestFiles(files);
  };

  // Liveness pill: a tiny status next to "Conversation" so the user
  // knows whether silence is the queen working, the network blipping,
  // or the queen genuinely stuck. Recomputed each render so the
  // "12s ago" label updates as time passes — paired with the tick
  // effect below that re-renders once per second while busy.
  const [, setNowTick] = useState(0);
  useEffect(() => {
    if (sseState !== "live") return;
    if (!isBusy && !lastEventAt) return;
    const id = setInterval(() => setNowTick((n) => n + 1), 1000);
    return () => clearInterval(id);
  }, [sseState, isBusy, lastEventAt]);

  let livenessPill: { label: string; className: string } | null = null;
  if (sseState === "reconnecting") {
    livenessPill = {
      label: "Reconnecting…",
      className: "text-amber-600 bg-amber-50 dark:bg-amber-950/40 border-amber-200/60",
    };
  } else if (sseState === "closed") {
    livenessPill = {
      label: "Stream closed",
      className: "text-muted-foreground bg-muted/50 border-border",
    };
  } else if (isBusy && lastEventAt) {
    const ageS = Math.floor((Date.now() - lastEventAt) / 1000);
    if (ageS >= 30) {
      livenessPill = {
        label: `No activity for ${ageS}s`,
        className: "text-orange-600 bg-orange-50 dark:bg-orange-950/40 border-orange-200/60",
      };
    } else if (ageS >= 10) {
      // Soft signal: queen is doing something but slow. Useful for
      // long screenshots or LLM TTFT — distinguishes "thinking" from
      // "frozen".
      livenessPill = {
        label: `Working… ${ageS}s`,
        className: "text-muted-foreground bg-muted/50 border-border",
      };
    }
  }

  return (
    <div className="flex flex-col h-full min-w-0">
      {/* Compact sub-header */}
      <div className="px-5 pt-4 pb-2 flex items-center gap-2">
        <p className="text-[11px] text-muted-foreground font-medium uppercase tracking-wider">
          Conversation
        </p>
        {livenessPill && (
          <span
            className={`text-[10px] font-medium px-1.5 py-0.5 rounded-md border ${livenessPill.className}`}
            title="Connection / queen liveness"
          >
            {livenessPill.label}
          </span>
        )}
        {headerAction && <div className="ml-auto">{headerAction}</div>}
      </div>

      {/* Messages */}
      <div className="flex-1 relative flex flex-col min-h-0">
      {searchOpen && (
        <div className="absolute top-2 right-3 z-20 flex items-center gap-1 bg-card border border-border/60 rounded-lg shadow-lg px-2 py-1 pointer-events-auto">
          <input
            ref={searchInputRef}
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                if (searchMatchedIds.length === 0) return;
                setCurrentMatchIdx((i) =>
                  e.shiftKey
                    ? (i - 1 + searchMatchedIds.length) % searchMatchedIds.length
                    : (i + 1) % searchMatchedIds.length,
                );
              } else if (e.key === "Escape") {
                e.preventDefault();
                setSearchOpen(false);
                setSearchQuery("");
              }
            }}
            placeholder="Find in conversation…"
            className="w-48 bg-transparent text-xs text-foreground placeholder:text-muted-foreground/60 focus:outline-none px-1"
          />
          <span className="text-[10px] font-mono text-muted-foreground/70 px-1 select-none">
            {searchQuery.trim()
              ? searchMatchedIds.length === 0
                ? "0/0"
                : `${currentMatchIdx + 1}/${searchMatchedIds.length}`
              : ""}
          </span>
          <button
            onClick={() => {
              if (searchMatchedIds.length === 0) return;
              setCurrentMatchIdx(
                (i) => (i - 1 + searchMatchedIds.length) % searchMatchedIds.length,
              );
            }}
            disabled={searchMatchedIds.length === 0}
            className="p-1 rounded text-muted-foreground hover:text-foreground hover:bg-muted/40 disabled:opacity-40 disabled:cursor-not-allowed"
            title="Previous match (Shift+Enter)"
          >
            <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5"><polyline points="3,7 6,4 9,7" /></svg>
          </button>
          <button
            onClick={() => {
              if (searchMatchedIds.length === 0) return;
              setCurrentMatchIdx((i) => (i + 1) % searchMatchedIds.length);
            }}
            disabled={searchMatchedIds.length === 0}
            className="p-1 rounded text-muted-foreground hover:text-foreground hover:bg-muted/40 disabled:opacity-40 disabled:cursor-not-allowed"
            title="Next match (Enter)"
          >
            <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5"><polyline points="3,5 6,8 9,5" /></svg>
          </button>
          <button
            onClick={() => {
              setSearchOpen(false);
              setSearchQuery("");
            }}
            className="p-1 rounded text-muted-foreground hover:text-foreground hover:bg-muted/40"
            title="Close (Esc)"
          >
            <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5"><line x1="3" y1="3" x2="9" y2="9" /><line x1="9" y1="3" x2="3" y2="9" /></svg>
          </button>
        </div>
      )}
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className="flex-1 overflow-auto px-5 pt-4 space-y-3"
      >
        {/* Loading indicator — older content still un-revealed above.
            `handleScroll` (scroll-up) and the auto-fill layout effect
            reveal it automatically; the indicator clears once everything
            is loaded. Sits at the very top, above the history transcript. */}
        {hasMoreOlder && (
          <div className="flex justify-center py-2 text-[10px] text-muted-foreground/60 select-none">
            Loading older messages…
          </div>
        )}

        {/* History timeline — older sessions grouped by day. Revealed
         * purely by scrolling up (`handleScroll` → `loadOlderStep`) and by
         * the auto-fill effect; there is NO click-to-expand. Each revealed
         * day renders as a date divider followed by its loaded sessions'
         * messages inline, so older history reads as one continuous
         * transcript flowing into the current session below. */}
        {historyTimeline && historyTimeline.length > 0 && (
          <div className="space-y-1 mb-3">
            {historyTimeline.map((day) => {
              // Only days the scroll cascade has reached are rendered.
              if (!expandedHistoryDays?.has(day.key)) return null;
              return (
                <div key={day.key}>
                  <div className="flex items-center gap-3 py-2 my-1">
                    <div className="flex-1 h-px bg-border/60" />
                    <span className="text-[10px] text-muted-foreground font-medium uppercase tracking-wider">
                      {day.label}
                    </span>
                    <div className="flex-1 h-px bg-border/60" />
                  </div>
                  {day.sessions.map((s) => {
                    const inlineMessages = historySessionMessages?.[s.session_id];
                    // Session not yet loaded by the cascade — render
                    // nothing; it fills in once its fetch resolves.
                    if (!inlineMessages || inlineMessages.length === 0) {
                      return null;
                    }
                    // Mirror the main chat's tool-status grouping so
                    // consecutive tool pills pack into one row instead of
                    // stacking. Same predicate as itemsWithDividers.
                    type InlineGroup =
                      | { kind: "msg"; msg: ChatMessage }
                      | { kind: "tools"; key: string; messages: ChatMessage[] };
                    const groups: InlineGroup[] = [];
                    for (const m of inlineMessages) {
                      if (m.type === "tool_status") {
                        const last = groups[groups.length - 1];
                        if (last && last.kind === "tools") {
                          last.messages.push(m);
                          continue;
                        }
                        groups.push({
                          kind: "tools",
                          key: `inline-tsg-${m.id}`,
                          messages: [m],
                        });
                        continue;
                      }
                      groups.push({ kind: "msg", msg: m });
                    }
                    return (
                      <div key={s.session_id} className="space-y-2">
                        {groups.map((g) =>
                          g.kind === "tools" ? (
                            <div key={g.key}>
                              <ToolActivityRow
                                content={mergeToolStatusContents(g.messages)}
                              />
                            </div>
                          ) : (
                            <MessageBubble
                              key={g.msg.id}
                              msg={g.msg}
                              queenTitle={queenTitle}
                              showQueenPhaseBadge={false}
                              onImageClick={(imgs, idx, sid) =>
                                setLightbox({ images: imgs, index: idx, sessionId: sid })
                              }
                              // History messages belong to `s.session_id`, not
                              // the active session — resolve their attachments
                              // against the session they actually live in.
                              feedbackSessionId={s.session_id}
                            />
                          ),
                        )}
                      </div>
                    );
                  })}
                </div>
              );
            })}
          </div>
        )}

        {(() => {
          // Day-collapse removed — the visibleCount lazy-load is now the
          // single mechanism gating how much history renders. Older days
          // are rendered in full as long as they're in the visible window,
          // and the IntersectionObserver on the top sentinel grows the
          // window as the user scrolls up. Day dividers still render as
          // visual separators, just without the hidden-content gate.
          return itemsWithDividers.map((item) => {
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
          if (item.kind === "tool_status_group") {
            // Collapse the messages' tool arrays into one synthetic
            // tool_status content so the pills land in a single
            // flex-wrap container — multiple consecutive bursts now
            // pack horizontally instead of stacking on their own
            // lines.
            const merged = mergeToolStatusContents(item.messages);
            return (
              <div key={item.key}>
                <ToolActivityRow
                  content={merged}
                  // Only the newest tool block may offer live actions. An older
                  // reveal card further up the transcript would otherwise still
                  // be asking which campaign to import, after it was answered.
                  onQuickReply={
                    item.key === latestToolGroupKey ? handleQuickReply : undefined
                  }
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
              <div key={msg.id} data-message-id={msg.id}>
                <InlineAskUserBubble
                  msg={msg}
                  payload={askPayload}
                  activeThread={activeThread}
                  onSend={onSend}
                  queenPhase={queenPhase}
                  showQueenPhaseBadge={showQueenPhaseBadge}
                  queenTitle={queenTitle}
                  queenProfileId={queenProfileId}
                  queenAvatarUrl={queenAvatarUrl}
                  queenPortrait={queenPortrait}
                  onImageClick={handleBubbleImageClick}
                />
              </div>
            );
          }
          // Only tag bubbles that render with a header — tool_status pills,
          // dividers, system rows etc. short-circuit MessageBubble before the
          // standard layout, so scrolling to them would land on the wrong row.
          // User messages and untyped queen/worker bubbles are the real
          // "messages" the user wants to read from the top.
          const scrollAnchorId =
            !msg.type || msg.type === "user" ? msg.id : undefined;
          return (
            <div
              key={msg.id}
              data-message-id={scrollAnchorId}
              ref={(el) => {
                if (el) messageWrapperRefs.current.set(msg.id, el);
                else messageWrapperRefs.current.delete(msg.id);
              }}
            >
              <MessageBubble
                msg={msg}
                queenPhase={queenPhase}
                showQueenPhaseBadge={showQueenPhaseBadge}
                queenTitle={queenTitle}
                queenProfileId={queenProfileId}
                queenAvatarUrl={queenAvatarUrl}
                queenPortrait={queenPortrait}
                onColonyLinkClick={onColonyLinkClick}
                onImageClick={handleBubbleImageClick}
                onSteer={onSteer}
                onCancelQueued={onCancelQueued}
                isQueenBusy={isBusy && msg.id === lastQueenMessageId}
                feedbackSessionId={sessionId}
                initialVote={feedbackVotes[msg.id]}
                onRetry={handleBubbleRetry}
                onEdit={handleBubbleEdit}
              />
            </div>
          );
        });
        })()}

        {/* Show typing indicator while waiting for first queen response
            (disabled / sendLocked + empty chat counts as warm-up). */}
        {(isWaiting ||
          ((disabled || sendLocked) && threadMessages.length === 0)) && (
          <div className="flex gap-3">
            <div
              className="flex-shrink-0 w-9 h-9 rounded-xl flex items-center justify-center overflow-hidden"
              style={queenAvatarUrl ? undefined : {
                backgroundColor: `${queenColor}18`,
                border: `1.5px solid ${queenColor}35`,
                boxShadow: `0 0 6px ${queenColor}10`,
              }}
            >
              <QueenAvatarIcon url={queenAvatarUrl} size={9} portrait={queenPortrait} />
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
        {/* Bottom spacer — grown on session switch so a short last reply
            can still reach the top of the viewport. Without this, the
            browser clamps scrollTop and the user lands at the bottom. */}
        <div ref={bottomSpacerRef} aria-hidden />
        <div ref={bottomRef} />
      </div>
      {showJumpToLatest && (
        <button
          type="button"
          onClick={() => {
            stickToBottom.current = true;
            setShowJumpToLatest(false);
            scrollToLatest("smooth");
          }}
          className="absolute bottom-3 left-1/2 -translate-x-1/2 flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-background border border-border shadow-md text-xs text-foreground hover:bg-muted transition-colors"
          aria-label="Jump to latest message"
        >
          <ArrowDown className="w-3.5 h-3.5" />
          Jump to latest
        </button>
      )}
      </div>

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
            <div className="flex flex-wrap items-center justify-center gap-2">
              <button
                type="button"
                onClick={onCompactAndFork}
                disabled={
                  !onCompactAndFork ||
                  compactingAndForking ||
                  startingNewSession
                }
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
              {onStartNewSession && (
                <button
                  type="button"
                  onClick={onStartNewSession}
                  disabled={startingNewSession || compactingAndForking}
                  className="inline-flex items-center gap-2 text-xs font-medium text-foreground bg-muted hover:bg-muted/70 disabled:opacity-50 disabled:cursor-not-allowed px-4 py-2 rounded-full transition-colors"
                >
                  {startingNewSession ? (
                    <>
                      <Loader2 className="w-3.5 h-3.5 animate-spin" />
                      <span>Starting…</span>
                    </>
                  ) : (
                    <span>
                      Start new session
                      {queenDisplayName ? ` with ${queenDisplayName}` : ""}
                    </span>
                  )}
                </button>
              )}
            </div>
          </div>
        </div>
      ) : pendingQuestions &&
        pendingQuestions.length >= 2 &&
        onQuestionSubmit ? (
        <MultiQuestionWidget
          questions={pendingQuestions}
          onSubmit={onQuestionSubmit}
          onDismiss={onQuestionDismiss}
        />
      ) : pendingQuestions &&
        pendingQuestions.length === 1 &&
        pendingQuestions[0].options &&
        pendingQuestions[0].options.length >= 2 &&
        onQuestionSubmit ? (
        <QuestionWidget
          question={pendingQuestions[0].prompt}
          options={pendingQuestions[0].options}
          onSubmit={(answer) =>
            onQuestionSubmit({ [pendingQuestions[0].id]: answer })
          }
          onDismiss={onQuestionDismiss}
        />
      ) : (
        <form
          onSubmit={handleSubmit}
          className="relative p-4"
          onDragEnter={handleDragEnter}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
          onPaste={handlePasteFiles}
        >
          {/* Drop overlay — shown while a file is dragged over the composer */}
          {isDragOver && (
            <div className="absolute inset-2 z-10 flex flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed border-primary/60 bg-background/85 backdrop-blur-sm pointer-events-none">
              <Paperclip className="w-5 h-5 text-primary" />
              <span className="text-sm font-medium text-primary">
                Drop to attach
              </span>
              <span className="text-xs text-muted-foreground">
                Images, PDF, or CSV
              </span>
            </div>
          )}
          {/* Image preview strip */}
          {pendingImages.length > 0 && (
            <div className="flex flex-wrap gap-2 mb-2 px-1">
              {pendingImages.map((img, i) => {
                const isUploadingThis =
                  img._fileName != null && uploadingFiles.includes(img._fileName);
                return (
                  <div key={i} className="relative group">
                    <AttachmentChip
                      url={img.image_url.url}
                      fileName={img._fileName}
                      byteSize={img._byteSize}
                      isUploading={isUploadingThis}
                      variant="pending"
                      sessionId={sessionId ?? undefined}
                    />
                    <button
                      type="button"
                      disabled={isUploadingThis}
                      onClick={() =>
                        setPendingImages((prev) => prev.filter((_, j) => j !== i))
                      }
                      className="absolute -top-1.5 -right-1.5 w-4 h-4 rounded-full bg-destructive text-destructive-foreground flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity disabled:opacity-0"
                    >
                      <X className="w-2.5 h-2.5" />
                    </button>
                  </div>
                );
              })}
            </div>
          )}
          {uploadError && (
            <div className="mb-2 px-3 py-2 rounded-lg bg-destructive/10 border border-destructive/30 text-xs text-destructive flex items-start gap-2">
              <span className="flex-1">{uploadError}</span>
              <button
                type="button"
                onClick={() => setUploadError(null)}
                className="flex-shrink-0 opacity-70 hover:opacity-100"
                aria-label="Dismiss"
              >
                <X className="w-3 h-3" />
              </button>
            </div>
          )}
          <div className="relative flex items-center gap-3 bg-muted/40 rounded-xl px-4 py-2.5 border border-border focus-within:border-primary/40 transition-colors">
            <input
              ref={fileInputRef}
              type="file"
              accept={FILE_INPUT_ACCEPT}
              multiple
              className="hidden"
              onChange={handleFileChange}
            />
            <button
              type="button"
              disabled={disabled}
              onClick={() => fileInputRef.current?.click()}
              className="flex-shrink-0 p-1 rounded-md text-muted-foreground hover:text-foreground disabled:opacity-30 transition-colors"
              title="Attach a file (image, PDF, CSV, or text)"
            >
              <Paperclip className="w-4 h-4" />
            </button>
            <div className="flex-1 min-w-0" data-tour="tour-queen-chat">
              <SkillTextEditor
                ref={editorRef}
                value={input}
                onChange={setInput}
                disabled={disabled}
                suggestionPlacement="up"
                maxHeightPx={160}
                className="text-sm text-foreground"
                onFocus={() => {
                  // User is engaging with the input — pull the chat all the way
                  // to the bottom so they can see the queen's thinking spinner
                  // and reply land as it happens, instead of staring at history.
                  stickToBottom.current = true;
                  setShowJumpToLatest(false);
                  bottomRef.current?.scrollIntoView({ behavior: "smooth" });
                }}
                onSubmit={() => {
                  if (paymentLocked) {
                    onPaymentLockedSend?.();
                    return;
                  }
                  // Mirror the native form submit path.
                  void handleSubmit({ preventDefault: () => {} } as React.FormEvent);
                }}
                placeholder={
                  disabled
                    ? "Connecting to agent..."
                    : paymentLocked
                      ? "Subscribe to start chatting..."
                      : sendLocked
                        ? "Type ahead — send unlocks once the queen is ready..."
                        : isBusy
                          ? "Queue a message — or click Steer to inject now..."
                          : "Message Queen Bee..."
                }
              />
            </div>
            {(colonyActive || isBusy) && onCancel && (
              <button
                type="button"
                onClick={onCancel}
                title="Stop all colony activity"
                className="p-2 rounded-lg bg-red-500/15 text-red-400 border border-red-500/40 hover:bg-red-500/25 transition-colors"
              >
                <Square className="w-4 h-4" />
              </button>
            )}
            {paymentLocked ? (
              <button
                type="button"
                onClick={onPaymentLockedSend}
                title="Subscribe to send. Click to view your plan."
                className="p-2 rounded-lg bg-muted text-muted-foreground border border-border/60 hover:bg-muted/70 transition-colors"
              >
                <Lock className="w-4 h-4" />
              </button>
            ) : (
              <button
                type="submit"
                disabled={
                  (!input.trim() && pendingImages.length === 0) ||
                  disabled ||
                  sendLocked ||
                  uploadingFiles.length > 0
                }
                title={
                  sendLocked
                    ? "Hold tight — the queen is starting up. Send unlocks once she's ready."
                    : uploadingFiles.length > 0
                      ? `Uploading ${uploadingFiles.length} file${uploadingFiles.length === 1 ? "" : "s"}…`
                      : isBusy
                        ? "Queue message — sent after the current turn, or click Steer on the bubble to send now"
                        : "Send"
                }
                className={`p-2 rounded-lg disabled:opacity-30 hover:opacity-90 transition-opacity ${
                  isBusy
                    ? "bg-amber-500/20 text-amber-600 border border-amber-500/40"
                    : "bg-primary text-primary-foreground"
                }`}
              >
                {uploadingFiles.length > 0 ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : isBusy ? (
                  <Zap className="w-4 h-4" />
                ) : (
                  <Send className="w-4 h-4" />
                )}
              </button>
            )}
          </div>
        </form>
      )}

      {/* Image carousel modal — portalled to body so it escapes overflow clipping */}
      {lightbox && createPortal(
        <ImageCarouselModal
          images={lightbox.images}
          initialIndex={lightbox.index}
          onClose={() => setLightbox(null)}
          sessionId={lightbox.sessionId ?? sessionId ?? undefined}
        />,
        document.body,
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Image carousel modal with zoom
// ---------------------------------------------------------------------------

function ImageCarouselModal({
  images,
  initialIndex,
  onClose,
  sessionId,
}: {
  images: ImageContent[];
  initialIndex: number;
  onClose: () => void;
  /** Needed so canonical `hive-attachment://` refs (Layer F2) resolve to
   * fetchable /api/sessions/{sid}/attachment/{name} URLs that the
   * `<embed>` PDF viewer and `<img>` element can actually load. */
  sessionId?: string;
}) {
  const [index, setIndex] = useState(initialIndex);
  const [zoom, setZoom] = useState(1);
  const [copied, setCopied] = useState(false);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const dragging = useRef(false);
  const lastPos = useRef({ x: 0, y: 0 });

  const current = images[index];
  // Use original full-res URL if available, fall back to ref; then
  // resolve canonical hive-attachment:// refs to fetchable URLs.
  const rawUrl = current._originalUrl || current.image_url.url;
  const displayUrl = sessionId ? resolveAttachmentUrl(rawUrl, sessionId) : rawUrl;
  // An unresolved `hive-attachment://` ref can't load (no protocol handler,
  // CSP refuses it). Only happens if the lightbox opens before sessionId is
  // known; show a placeholder instead of an <img>/<embed> that 404s + spams
  // the console.
  const isUnresolved = displayUrl.startsWith("hive-attachment://");
  // Type detection uses the original ref — extensions ride through
  // unchanged from `hive-attachment://X.pdf` and from resolved URLs.
  const isPdf = rawUrl.startsWith("data:application/pdf") || rawUrl.includes(".pdf");
  const isCsv = rawUrl.includes(".csv");
  const isText = TEXT_FILE_EXT_RE.test(rawUrl);
  const isFile = isPdf || isCsv || isText;

  const resetView = () => { setZoom(1); setPan({ x: 0, y: 0 }); };

  const goTo = (i: number) => {
    setIndex(i);
    resetView();
  };

  const handleWheel = (e: React.WheelEvent) => {
    e.preventDefault();
    setZoom((z) => Math.min(5, Math.max(0.25, z - e.deltaY * 0.002)));
  };

  const handleMouseDown = (e: React.MouseEvent) => {
    if (zoom <= 1) return;
    dragging.current = true;
    lastPos.current = { x: e.clientX, y: e.clientY };
  };

  const handleMouseMove = (e: React.MouseEvent) => {
    if (!dragging.current) return;
    setPan((p) => ({
      x: p.x + e.clientX - lastPos.current.x,
      y: p.y + e.clientY - lastPos.current.y,
    }));
    lastPos.current = { x: e.clientX, y: e.clientY };
  };

  const handleMouseUp = () => { dragging.current = false; };

  // Keyboard navigation
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      else if (e.key === "ArrowLeft") goTo((index - 1 + images.length) % images.length);
      else if (e.key === "ArrowRight") goTo((index + 1) % images.length);
      else if (e.key === "+" || e.key === "=") setZoom((z) => Math.min(5, z + 0.25));
      else if (e.key === "-") setZoom((z) => Math.max(0.25, z - 0.25));
      else if (e.key === "0") resetView();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  });

  return (
    <div
      className="fixed inset-0 z-[9999] flex items-center justify-center"
      onClick={onClose}
    >
      <div className="absolute inset-0 bg-black/20" />

      <div
        className="relative bg-card border border-border/60 rounded-2xl shadow-2xl flex flex-col"
        style={{ width: "min(90vw, 900px)", height: "min(85vh, 720px)" }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-2.5 border-b border-border/40">
          <span className="text-xs text-muted-foreground">
            {images.length > 1
              ? `${index + 1} of ${images.length}`
              : isFile ? "File preview" : "Image preview"}
          </span>
          <div className="flex items-center gap-1">
            {!isFile && !isUnresolved && (
              <>
                <button
                  onClick={() => {
                    void copyImageUrlToClipboard(displayUrl).then((r) => {
                      if (r.ok) {
                        setCopied(true);
                        setTimeout(() => setCopied(false), 1500);
                      }
                    });
                  }}
                  className="p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
                  title="Copy image to clipboard"
                >
                  {copied ? (
                    <Check className="w-4 h-4 text-primary" />
                  ) : (
                    <Copy className="w-4 h-4" />
                  )}
                </button>
                <button
                  onClick={() => {
                    saveAttachmentAsDownload(displayUrl, current._fileName);
                  }}
                  className="p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
                  title="Save as…"
                >
                  <Download className="w-4 h-4" />
                </button>
                <button
                  onClick={() => {
                    openAttachmentInBrowser(displayUrl);
                  }}
                  className="p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
                  title="Open with default app"
                >
                  <ExternalLink className="w-4 h-4" />
                </button>
                <div className="w-px h-4 bg-border/40 mx-1" />
              </>
            )}
            {!isFile && (
              <>
                <button
                  onClick={() => setZoom((z) => Math.max(0.25, z - 0.25))}
                  className="p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
                  title="Zoom out (−)"
                >
                  <ZoomOut className="w-4 h-4" />
                </button>
                <span className="text-[11px] text-muted-foreground w-12 text-center tabular-nums">
                  {Math.round(zoom * 100)}%
                </span>
                <button
                  onClick={() => setZoom((z) => Math.min(5, z + 0.25))}
                  className="p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
                  title="Zoom in (+)"
                >
                  <ZoomIn className="w-4 h-4" />
                </button>
                <button
                  onClick={resetView}
                  className="p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
                  title="Reset (0)"
                >
                  <RotateCw className="w-3.5 h-3.5" />
                </button>
                <div className="w-px h-4 bg-border/40 mx-1" />
              </>
            )}
            <button
              onClick={onClose}
              className="p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Content viewport */}
        {isUnresolved ? (
          <div className="flex-1 flex items-center justify-center p-4">
            <Loader2 className="w-5 h-5 animate-spin text-muted-foreground" />
          </div>
        ) : (isCsv || isText) && current._extractedText ? (
          <div className="flex-1 overflow-auto p-4">
            <pre className="text-xs font-mono text-foreground/80 whitespace-pre-wrap">{current._extractedText}</pre>
          </div>
        ) : isPdf ? (
          <div className="flex-1 overflow-hidden">
            <embed
              src={displayUrl}
              type="application/pdf"
              className="w-full h-full"
            />
          </div>
        ) : (
          <div
            className="flex-1 overflow-hidden flex items-center justify-center"
            style={{ cursor: zoom > 1 ? (dragging.current ? "grabbing" : "grab") : "default" }}
            onWheel={handleWheel}
            onMouseDown={handleMouseDown}
            onMouseMove={handleMouseMove}
            onMouseUp={handleMouseUp}
            onMouseLeave={handleMouseUp}
          >
            <img
              src={displayUrl}
              alt={`Image ${index + 1}`}
              draggable={false}
              className="select-none"
              style={{
                transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`,
                maxWidth: zoom <= 1 ? "100%" : "none",
                maxHeight: zoom <= 1 ? "100%" : "none",
                objectFit: "contain",
                transition: dragging.current ? "none" : "transform 150ms ease-out",
              }}
            />
          </div>
        )}

        {/* Navigation */}
        {images.length > 1 && (
          <div className="flex items-center justify-center gap-3 px-4 py-2.5 border-t border-border/40">
            <button
              onClick={() => goTo((index - 1 + images.length) % images.length)}
              className="p-2 rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
            >
              <ChevronLeft className="w-5 h-5" />
            </button>
            <div className="flex items-center gap-1.5">
              {images.map((_, i) => (
                <button
                  key={i}
                  onClick={() => goTo(i)}
                  className={`w-2 h-2 rounded-full transition-colors ${
                    i === index ? "bg-primary" : "bg-muted-foreground/30 hover:bg-muted-foreground/50"
                  }`}
                />
              ))}
            </div>
            <button
              onClick={() => goTo((index + 1) % images.length)}
              className="p-2 rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
            >
              <ChevronRight className="w-5 h-5" />
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
