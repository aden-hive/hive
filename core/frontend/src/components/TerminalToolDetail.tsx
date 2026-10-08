/**
 * Per-call detail body for `terminal_*` tool calls. Rendered inside
 * the expanded panel of a ToolActivityRow pill — not a top-level
 * row. Shows `$ command`, optional warning chip for destructive
 * patterns, and (when complete) a scrollable stdout/stderr block.
 *
 * The result envelope is the structured shape produced by
 * `terminal-tools/common/truncation.py:build_exec_envelope`. We read
 * it defensively and fall back to a JSON dump for unknown shapes.
 */

import { AlertTriangle, Loader2 } from "lucide-react";

export interface TerminalToolEntry {
  name: string;
  done: boolean;
  args?: unknown;
  result?: unknown;
  isError?: boolean;
  callKey?: string;
  startedAt?: number;
  endedAt?: number;
}

type Args = Record<string, unknown>;

/** Pick a representative `$ command` line per terminal_* tool. */
function commandLine(name: string, args: Args): string {
  const cmd = String(args.command ?? "");
  switch (name) {
    case "terminal_exec":
      return cmd;
    case "terminal_job_start":
      return `[bg] ${cmd}`;
    case "terminal_job_logs":
      return `[logs] ${args.job_id ?? "?"}${args.wait_until_exit ? " (wait)" : ""}`;
    case "terminal_job_manage":
      return `[${args.action ?? "?"}] ${args.job_id ?? ""}`.trim();
    case "terminal_pty_open":
      return `[pty] open${args.cwd ? ` cwd=${args.cwd}` : ""}`;
    case "terminal_pty_run":
      if (args.read_only) return `[pty] drain ${args.session_id ?? ""}`;
      return `${args.raw_send ? "[pty raw]" : "[pty]"} ${cmd}`;
    case "terminal_pty_close":
      return `[pty] close ${args.session_id ?? ""}`;
    case "terminal_rg":
      return `rg ${JSON.stringify(args.pattern ?? "")} ${args.path ?? ""}`;
    case "terminal_find":
      return `find ${args.path ?? "."}${args.name ? ` -name ${JSON.stringify(args.name)}` : ""}${args.iname ? ` -iname ${JSON.stringify(args.iname)}` : ""}`;
    case "terminal_output_get":
      return `[handle] ${args.output_handle ?? "?"}`;
    default:
      return name;
  }
}

interface Summary {
  meta: string;
  warning?: string;
  body: string;
  empty: boolean;
  truncated?: { handle: string; bytes: number };
  jobId?: string;
}

function asObj(v: unknown): Record<string, unknown> {
  return v && typeof v === "object" ? (v as Record<string, unknown>) : {};
}

/** Pick the most informative output stream from the result envelope.
 * Different terminal_* tools populate different fields (stdout/stderr
 * for exec, data for job_logs/output_get, output for pty, error on
 * failure). First non-empty wins. */
function pickBody(r: Record<string, unknown>): string {
  const stdout = String(r.stdout ?? "");
  const stderr = String(r.stderr ?? "");
  if (stdout || stderr) {
    return stderr ? `${stdout}${stdout ? "\n\n[stderr]\n" : ""}${stderr}` : stdout;
  }
  return String(r.data ?? r.output ?? r.error ?? "");
}

function summarize(entry: TerminalToolEntry): Summary {
  if (!entry.done) return { meta: "running…", body: "", empty: true };

  const result = entry.result;
  if (result == null) return { meta: "no result", body: "", empty: true };
  if (typeof result === "string") {
    const lines = result.split("\n").length;
    return {
      meta: `${lines} ${lines === 1 ? "line" : "lines"}`,
      body: result,
      empty: result.length === 0,
    };
  }

  const r = asObj(result);
  const body = pickBody(r);
  const lineCount = body ? body.split("\n").length : 0;
  const runtimeMs = typeof r.runtime_ms === "number" ? r.runtime_ms : undefined;
  const exit = typeof r.exit_code === "number" ? r.exit_code : undefined;

  const parts: string[] = [];
  if (body) parts.push(`${lineCount} ${lineCount === 1 ? "line" : "lines"}`);
  if (runtimeMs !== undefined) {
    parts.push(runtimeMs < 1000 ? `${runtimeMs}ms` : `${(runtimeMs / 1000).toFixed(1)}s`);
  }
  if (exit !== undefined && exit !== 0) parts.push(`exit ${exit}`);
  if (r.status === "running") parts.push("running");
  if (r.status === "exited" && exit !== undefined) parts.push(`exit ${exit}`);
  if (r.timed_out) parts.push("timed out");
  if (r.auto_backgrounded) parts.push("auto-backgrounded");

  const handle = typeof r.output_handle === "string" ? r.output_handle : null;
  const truncBytes =
    Number(r.stdout_truncated_bytes ?? 0) + Number(r.stderr_truncated_bytes ?? 0);

  return {
    meta: parts.join(" · ") || "done",
    warning: typeof r.warning === "string" && r.warning ? r.warning : undefined,
    body,
    empty: !body,
    truncated: handle ? { handle, bytes: truncBytes } : undefined,
    jobId: typeof r.job_id === "string" ? r.job_id : undefined,
  };
}

export default function TerminalToolDetail({ entry }: { entry: TerminalToolEntry }) {
  const cmd = commandLine(entry.name, asObj(entry.args));
  const s = summarize(entry);
  const running = !entry.done;

  return (
    <div className="space-y-1.5">
      <div className="flex items-start gap-1.5 text-[11px] font-mono text-muted-foreground">
        {running ? (
          <Loader2 className="w-2.5 h-2.5 mt-[3px] shrink-0 animate-spin" />
        ) : (
          <span className="mt-[3px] shrink-0 w-2.5 text-center">$</span>
        )}
        <span className="break-all min-w-0 flex-1 text-foreground/90">{cmd}</span>
        <span className="text-[10px] text-muted-foreground/70 shrink-0">{s.meta}</span>
        {s.jobId && <span className="text-[10px] text-muted-foreground/70 shrink-0">· {s.jobId}</span>}
      </div>

      {s.warning && (
        <div className="flex">
          <span
            className="inline-flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-full"
            style={{
              color: "hsl(35 90% 45%)",
              backgroundColor: "hsl(35 90% 45% / 0.10)",
              border: "1px solid hsl(35 90% 45% / 0.3)",
            }}
          >
            <AlertTriangle className="w-2.5 h-2.5" />
            {s.warning}
          </span>
        </div>
      )}

      {!running && (
        <div className="rounded-md bg-muted/55 border border-border/60 font-mono text-[12px] leading-[1.55] text-foreground/85 overflow-hidden">
          <div className="max-h-[260px] overflow-y-auto p-2.5">
            {s.empty ? (
              <span className="italic text-muted-foreground">no output</span>
            ) : (
              <pre className="whitespace-pre-wrap break-words m-0">{s.body}</pre>
            )}
          </div>
          {s.truncated && (
            <div className="px-2.5 py-1.5 border-t border-border/40 flex items-center justify-between text-[10px] text-muted-foreground bg-muted/30">
              <span>
                +{Math.round(s.truncated.bytes / 1024)} KB · output_handle{" "}
                <span className="font-mono">{s.truncated.handle}</span>
              </span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
