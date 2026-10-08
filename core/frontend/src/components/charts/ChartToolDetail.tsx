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
 *   - The download is always available because the server tool wrote
 *     the file before returning. We don't generate the link client-
 *     side; we use ``result.file_url`` directly.
 */

import { lazy, Suspense, useState } from "react";
import { Download, Loader2, Check } from "lucide-react";
import { apiUrl } from "@/api/client";
import { downloadUrl } from "@/lib/desktop-shims";

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
  startedAt?: number;
  endedAt?: number;
}

interface ChartResult {
  kind?: "echarts" | "mermaid";
  spec?: unknown;
  file_path?: string;
  file_url?: string;
  title?: string;
  error?: string;
  // Width/height come back from the server tool but are NOT displayed
  // in the footer (per design feedback 2026-05-01). Kept here so the
  // live in-chat render can match the spec's native aspect ratio
  // instead of forcing a 16:9 box that clips wide dashboards.
  width?: number;
  height?: number;
}

function asResult(v: unknown): ChartResult {
  if (v && typeof v === "object") return v as ChartResult;
  return {};
}

/**
 * Download the rendered chart. The runtime serves the chart image at its
 * on-disk path via the `/api` surface; a temporary `<a download>` saves it
 * under the suggested filename.
 */
function downloadChart(srcPath: string, suggestedName: string): { ok: boolean; cancelled?: boolean } {
  return downloadUrl(apiUrl(srcPath), suggestedName);
}

export default function ChartToolDetail({ entry }: { entry: ChartToolEntry }) {
  const [downloadState, setDownloadState] = useState<"idle" | "saving" | "saved">(
    "idle",
  );

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
    // fixed spec. Showing the raw "Cannot create property 'series' on
    // string '...'" wall-of-text scared users (feedback 2026-05-01).
    return null;
  }

  const kind = result.kind;
  const spec = result.spec;
  if (!kind || spec === undefined) {
    return null;
  }

  const handleDownload = async () => {
    if (!result.file_path) return;
    const suggestedName = `${result.title || "chart"}.png`;
    setDownloadState("saving");
    try {
      const r = await downloadChart(result.file_path, suggestedName);
      if (r.ok && !r.cancelled) {
        setDownloadState("saved");
        // Clear the "saved" indicator after a beat so the button can be
        // reused for further saves.
        window.setTimeout(() => setDownloadState("idle"), 2000);
      } else {
        setDownloadState("idle");
      }
    } catch {
      setDownloadState("idle");
    }
  };

  // Honor the spec's native aspect ratio when both dimensions are
  // known (the server tool always returns them). Wide multi-card
  // dashboards designed at 1400×700 (2:1) used to get crammed into
  // a 16:9 box at 768px wide → content overflowed and clipped
  // (feedback 2026-05-01). Falls back to undefined so EChartsBlock's
  // 16:9 default applies for chart kinds without dimension hints.
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

      {/* Footer: just title + download. The PNG dimensions / dpi /
          file size were displayed earlier but the user pointed out
          (2026-05-01) that nobody cares about those numbers in the
          chat — they're noise. Title gives the chart context; the
          Download button is the only action. */}
      <div className="flex items-center justify-between mt-2 px-1 text-[10.5px] text-muted-foreground/80">
        <span className="truncate min-w-0 flex-1">
          {result.title || kind}
        </span>
        {result.file_path && (
          <button
            type="button"
            onClick={handleDownload}
            disabled={downloadState === "saving"}
            className="inline-flex items-center gap-1 hover:text-foreground transition shrink-0 disabled:opacity-60 cursor-pointer"
            title={
              downloadState === "saved"
                ? `Saved to your chosen location`
                : `Save a copy of ${result.file_path}`
            }
          >
            {downloadState === "saving" ? (
              <Loader2 className="w-3 h-3 animate-spin" />
            ) : downloadState === "saved" ? (
              <Check className="w-3 h-3 text-primary" />
            ) : (
              <Download className="w-3 h-3" />
            )}
            {downloadState === "saved" ? "Saved" : "Download PNG"}
          </button>
        )}
      </div>
    </div>
  );
}
