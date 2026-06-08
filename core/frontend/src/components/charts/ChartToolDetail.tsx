/**
 * Per-call detail row for ``chart_*`` tool calls.
 *
 * The canonical embedding mechanism: when the agent invokes
 * ``chart_render``, the runtime stores the result envelope in
 * ``events.jsonl``; ``chat-helpers.replayEvent`` retains it and the
 * chat panel dispatches it here. We read ``result.spec`` and mount
 * the live renderer; ``result.file_url`` becomes the download link.
 *
 * Rules baked in:
 *   - The chart is reconstructed FROM THE TOOL RESULT, not from any
 *     markdown fence the agent might have written. Calling the tool
 *     IS the embedding — there's nothing else to remember.
 *   - The chart survives session reload because the spec lives in
 *     events.jsonl alongside the tool_call_completed event.
 *   - The downloadable PNG lives at ``result.file_url`` (a ``file://``
 *     URI on the runtime host). The web frontend can't open file://
 *     directly; we surface ``file_path`` as text and give a Copy
 *     button so the user can paste it into a file manager. (The
 *     desktop renderer has an Electron IPC bridge — not available
 *     in OSS.)
 */

import { lazy, Suspense, useState } from "react";
import { Copy, Loader2, Check } from "lucide-react";

// Lazy chunks so non-chart messages don't drag in echarts/mermaid.
const EChartsBlock = lazy(() => import("./EChartsBlock"));
const MermaidBlock = lazy(() => import("./MermaidBlock"));

export interface ChartToolEntry {
  name: string;
  done: boolean;
  args?: unknown;
  result?: unknown;
  isError?: boolean;
  callKey?: string;
}

interface ChartResult {
  kind?: "echarts" | "mermaid";
  spec?: unknown;
  file_path?: string;
  file_url?: string;
  title?: string;
  error?: string;
  // Width/height come back from the server tool but are NOT displayed
  // in the footer. Kept here so the live in-chat render can match the
  // spec's native aspect ratio instead of forcing a 16:9 box that
  // clips wide dashboards.
  width?: number;
  height?: number;
}

function asResult(v: unknown): ChartResult {
  if (v && typeof v === "object") return v as ChartResult;
  return {};
}

export default function ChartToolDetail({ entry }: { entry: ChartToolEntry }) {
  const [copyState, setCopyState] = useState<"idle" | "copied">("idle");

  // Still running: show a tiny inline spinner. Charts render fast (a
  // few hundred ms), so a full skeleton would flash and feel janky.
  if (!entry.done) {
    return (
      <div className="pl-10 mt-1.5">
        <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
          <Loader2 className="w-3 h-3 animate-spin shrink-0" />
          <span>rendering chart…</span>
        </div>
      </div>
    );
  }

  const result = asResult(entry.result);

  if (result.error) {
    // Errors are intentionally NOT shown to the user — the agent sees
    // them in the tool result envelope and is expected to retry with a
    // fixed spec.
    return null;
  }

  const kind = result.kind;
  const spec = result.spec;
  if (!kind || spec === undefined) {
    return null;
  }

  const handleCopyPath = async () => {
    if (!result.file_path) return;
    try {
      await navigator.clipboard.writeText(result.file_path);
      setCopyState("copied");
      window.setTimeout(() => setCopyState("idle"), 2000);
    } catch {
      // Clipboard API unavailable (insecure context); silently no-op.
    }
  };

  // Honor the spec's native aspect ratio when both dimensions are
  // known (the server tool always returns them).
  const aspectRatio =
    result.width && result.height ? result.width / result.height : undefined;

  return (
    <div className="pl-10 mt-1.5 max-w-5xl">
      <Suspense
        fallback={
          <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
            <Loader2 className="w-3 h-3 animate-spin" />
            <span>loading chart engine…</span>
          </div>
        }
      >
        {kind === "echarts" ? (
          <EChartsBlock spec={spec} aspectRatio={aspectRatio} />
        ) : kind === "mermaid" ? (
          <MermaidBlock source={typeof spec === "string" ? spec : ""} />
        ) : (
          <div className="text-[11px] text-muted-foreground">
            unknown chart kind: {String(kind)}
          </div>
        )}
      </Suspense>

      {/* Footer: title + path-copy. The PNG lives on the runtime host;
          web browsers can't open file:// URIs from a hosted page, so
          we surface the path as a copyable string instead of a fake
          Download button. */}
      <div className="flex items-center justify-between mt-2 px-1 text-[10.5px] text-muted-foreground/80">
        <span className="truncate min-w-0 flex-1">
          {result.title || kind}
        </span>
        {result.file_path && (
          <button
            type="button"
            onClick={handleCopyPath}
            className="inline-flex items-center gap-1 hover:text-foreground transition shrink-0 cursor-pointer"
            title={
              copyState === "copied"
                ? "Copied to clipboard"
                : `Copy path: ${result.file_path}`
            }
          >
            {copyState === "copied" ? (
              <Check className="w-3 h-3 text-primary" />
            ) : (
              <Copy className="w-3 h-3" />
            )}
            {copyState === "copied" ? "Copied" : "Copy path"}
          </button>
        )}
      </div>
    </div>
  );
}
