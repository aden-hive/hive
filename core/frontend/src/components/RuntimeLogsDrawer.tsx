import { useEffect, useRef, useState } from "react";
import { useRuntimeLogs } from "@/hooks/use-runtime-logs";
import { useShowRuntimeLogs } from "@/hooks/use-show-runtime-logs";

/**
 * Floating bottom-right drawer that displays the last 500 lines of runtime
 * stdout/stderr streamed from the Electron main process. Collapsed by
 * default; shows a badge with the count of captured lines and a red
 * indicator when the most-recent entry came from stderr.
 */
export default function RuntimeLogsDrawer() {
  const [visible] = useShowRuntimeLogs();
  const { logs, clear } = useRuntimeLogs();
  const [open, setOpen] = useState(false);
  const [autoScroll, setAutoScroll] = useState(true);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  const lastIsErr = logs.length > 0 && logs[logs.length - 1].stream === "stderr";

  useEffect(() => {
    if (!open || !autoScroll || !scrollRef.current) return;
    scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [logs, open, autoScroll]);

  const handleScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    // If the user scrolls up more than a few lines, pause auto-scroll until
    // they scroll back to (or near) the bottom.
    const distanceFromBottom =
      el.scrollHeight - el.scrollTop - el.clientHeight;
    setAutoScroll(distanceFromBottom < 32);
  };

  if (!visible) return null;

  return (
    <div className="fixed bottom-3 right-3 z-50 flex flex-col items-end gap-2">
      {open && (
        <div className="w-[720px] max-w-[90vw] h-80 flex flex-col rounded-md border border-border bg-zinc-950 text-zinc-100 shadow-xl">
          <div className="flex items-center justify-between border-b border-zinc-800 px-3 py-1.5">
            <div className="text-xs font-medium text-zinc-300">
              Runtime logs{" "}
              <span className="text-zinc-500">({logs.length})</span>
            </div>
            <div className="flex items-center gap-2">
              <label className="flex items-center gap-1 text-xs text-zinc-400">
                <input
                  type="checkbox"
                  checked={autoScroll}
                  onChange={(e) => setAutoScroll(e.target.checked)}
                  className="accent-zinc-400"
                />
                auto-scroll
              </label>
              <button
                type="button"
                onClick={clear}
                className="rounded px-2 py-0.5 text-xs text-zinc-400 hover:bg-zinc-800 hover:text-zinc-100"
              >
                Clear
              </button>
              <button
                type="button"
                onClick={() => setOpen(false)}
                className="rounded px-2 py-0.5 text-xs text-zinc-400 hover:bg-zinc-800 hover:text-zinc-100"
                aria-label="Close runtime logs"
              >
                ✕
              </button>
            </div>
          </div>
          <div
            ref={scrollRef}
            onScroll={handleScroll}
            className="flex-1 overflow-y-auto px-3 py-2 font-mono text-[11px] leading-[1.35] whitespace-pre-wrap"
          >
            {logs.length === 0 ? (
              <div className="text-zinc-500 italic">(no output yet)</div>
            ) : (
              logs.map((entry) => (
                <div
                  key={entry.seq}
                  className={
                    entry.stream === "stderr"
                      ? "text-rose-300"
                      : "text-zinc-200"
                  }
                >
                  {entry.text}
                </div>
              ))
            )}
          </div>
        </div>
      )}
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 rounded-full border border-border bg-background/80 px-3 py-1 text-xs text-muted-foreground shadow backdrop-blur hover:bg-background"
      >
        <span
          className={`inline-block h-2 w-2 rounded-full ${
            lastIsErr
              ? "bg-rose-500"
              : logs.length > 0
                ? "bg-emerald-500"
                : "bg-zinc-400"
          }`}
        />
        Runtime logs{logs.length > 0 && ` · ${logs.length}`}
      </button>
    </div>
  );
}
