import { useMemo, useState } from "react";
import { AlertCircle, CalendarClock, Loader2, X } from "lucide-react";
import { sessionsApi } from "@/api/sessions";
import { cronToLabel } from "@/lib/graphUtils";
import {
  buildTimerConfig,
  cronNextUtc,
  type ScheduleForm,
  type ScheduleMode,
} from "@/lib/schedule";

interface Props {
  sessionId: string;
  onClose: () => void;
  /** Fired after the runtime acknowledges creation. The new trigger card
   *  arrives separately over SSE, so this is just a hook for the caller. */
  onCreated?: () => void;
}

const MODES: { key: ScheduleMode; label: string }[] = [
  { key: "daily", label: "Daily" },
  { key: "interval", label: "Interval" },
  { key: "weekly", label: "Weekly" },
  { key: "advanced", label: "Advanced" },
];

// Sunday-first to match the day chips users see in calendar apps. Two letters
// collide (T, S) so each chip carries a title for disambiguation.
const WEEKDAYS = [
  { dow: 0, letter: "S", name: "Sunday" },
  { dow: 1, letter: "M", name: "Monday" },
  { dow: 2, letter: "T", name: "Tuesday" },
  { dow: 3, letter: "W", name: "Wednesday" },
  { dow: 4, letter: "T", name: "Thursday" },
  { dow: 5, letter: "F", name: "Friday" },
  { dow: 6, letter: "S", name: "Saturday" },
];

const inputCls =
  "w-full rounded-md border border-border/60 bg-background/60 px-2.5 py-1.5 text-xs text-foreground placeholder:text-muted-foreground/60 focus:outline-none focus:border-primary/50 transition-colors";

const labelCls =
  "block text-[10px] font-medium text-muted-foreground uppercase tracking-wider mb-1.5";

function formatNext(ms: number): string {
  return new Date(ms).toLocaleString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function relative(ms: number, now: number): string {
  const sec = Math.max(0, Math.round((ms - now) / 1000));
  const d = Math.floor(sec / 86400);
  const h = Math.floor((sec % 86400) / 3600);
  const m = Math.floor((sec % 3600) / 60);
  if (d > 0) return `in ${d}d ${h}h`;
  if (h > 0) return `in ${h}h ${m}m`;
  if (m > 0) return `in ${m}m`;
  return "in under a minute";
}

export default function CreateSchedulerModal({ sessionId, onClose, onCreated }: Props) {
  const [name, setName] = useState("");
  const [task, setTask] = useState("");
  const [mode, setMode] = useState<ScheduleMode>("daily");
  const [time, setTime] = useState("09:00"); // local HH:MM
  const [intervalValue, setIntervalValue] = useState(30);
  const [intervalUnit, setIntervalUnit] = useState<"minutes" | "hours">("minutes");
  const [weekdays, setWeekdays] = useState<number[]>([1, 2, 3, 4, 5]);
  const [cron, setCron] = useState("0 9 * * *");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const form: ScheduleForm = useMemo(() => {
    const [hh, mm] = time.split(":").map((n) => parseInt(n, 10));
    return {
      mode,
      hour: Number.isFinite(hh) ? hh : 0,
      minute: Number.isFinite(mm) ? mm : 0,
      intervalValue,
      intervalUnit,
      weekdays,
      cron,
    };
  }, [mode, time, intervalValue, intervalUnit, weekdays, cron]);

  const config = useMemo(() => buildTimerConfig(form), [form]);

  // Live local preview — the exact next fire, computed the same way the
  // runtime will (UTC cron evaluation), then rendered back in local time.
  const preview = useMemo(() => {
    if (!config) return null;
    if ("interval_minutes" in config) {
      const min = config.interval_minutes;
      const label =
        min >= 60 && min % 60 === 0 ? `Every ${min / 60}h` : `Every ${min}m`;
      return { label, next: "First run starts shortly after creation." };
    }
    const label = cronToLabel(config.cron);
    const nextMs = cronNextUtc(config.cron, Date.now());
    return {
      label,
      next: nextMs
        ? `Next: ${formatNext(nextMs)} (${relative(nextMs, Date.now())})`
        : null,
    };
  }, [config]);

  const toggleWeekday = (dow: number) =>
    setWeekdays((prev) =>
      prev.includes(dow) ? prev.filter((d) => d !== dow) : [...prev, dow],
    );

  const valid = name.trim().length > 0 && task.trim().length > 0 && config != null;

  const handleCreate = async () => {
    if (!valid || busy || !config) return;
    setBusy(true);
    setError(null);
    try {
      await sessionsApi.createTrigger(sessionId, {
        name: name.trim(),
        task: task.trim(),
        trigger_config: config,
      });
      onCreated?.();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
  };

  return (
    <>
      <div
        className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm"
        onClick={busy ? undefined : onClose}
      />
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4 pointer-events-none">
        <div className="bg-card border border-border rounded-xl shadow-2xl w-full max-w-md pointer-events-auto flex flex-col max-h-[88vh]">
          {/* Header */}
          <div className="flex items-center justify-between px-5 py-4 border-b border-border/60">
            <div className="flex items-center gap-3">
              <div className="w-8 h-8 rounded-lg bg-primary/15 border border-primary/30 flex items-center justify-center text-primary">
                <CalendarClock className="w-4 h-4" />
              </div>
              <div>
                <h2 className="text-sm font-semibold text-foreground">New schedule</h2>
                <p className="text-[11px] text-muted-foreground">
                  Run this colony automatically on a timer.
                </p>
              </div>
            </div>
            <button
              onClick={onClose}
              disabled={busy}
              className="p-1.5 rounded-md hover:bg-muted/60 text-muted-foreground hover:text-foreground transition-colors disabled:opacity-40"
              title="Close"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          {/* Body */}
          <div className="flex-1 min-h-0 overflow-y-auto px-5 py-4 space-y-4">
            {/* Name */}
            <div>
              <label className={labelCls}>Name</label>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. Morning inbox sweep"
                className={inputCls}
                autoFocus
              />
            </div>

            {/* Schedule type */}
            <div>
              <label className={labelCls}>Schedule</label>
              <div className="flex gap-1 p-0.5 rounded-lg bg-muted/40 border border-border/40">
                {MODES.map((m) => (
                  <button
                    key={m.key}
                    type="button"
                    onClick={() => setMode(m.key)}
                    className={`flex-1 px-2 py-1 rounded-md text-[11px] font-medium transition-colors ${
                      mode === m.key
                        ? "bg-primary/15 text-primary"
                        : "text-muted-foreground hover:text-foreground hover:bg-muted/50"
                    }`}
                  >
                    {m.label}
                  </button>
                ))}
              </div>
            </div>

            {/* Per-mode controls */}
            {mode === "daily" && (
              <div>
                <label className={labelCls}>Time (your local time)</label>
                <input
                  type="time"
                  value={time}
                  onChange={(e) => setTime(e.target.value)}
                  className={inputCls}
                />
              </div>
            )}

            {mode === "interval" && (
              <div>
                <label className={labelCls}>Run every</label>
                <div className="flex gap-2">
                  <input
                    type="number"
                    min={1}
                    value={intervalValue}
                    onChange={(e) => setIntervalValue(Math.max(1, parseInt(e.target.value, 10) || 0))}
                    className={`${inputCls} w-24`}
                  />
                  <div className="flex gap-1 p-0.5 rounded-lg bg-muted/40 border border-border/40">
                    {(["minutes", "hours"] as const).map((u) => (
                      <button
                        key={u}
                        type="button"
                        onClick={() => setIntervalUnit(u)}
                        className={`px-2.5 py-1 rounded-md text-[11px] font-medium transition-colors ${
                          intervalUnit === u
                            ? "bg-primary/15 text-primary"
                            : "text-muted-foreground hover:text-foreground hover:bg-muted/50"
                        }`}
                      >
                        {u}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            )}

            {mode === "weekly" && (
              <div className="space-y-2.5">
                <div>
                  <label className={labelCls}>Days</label>
                  <div className="flex gap-1.5">
                    {WEEKDAYS.map((d) => (
                      <button
                        key={d.dow}
                        type="button"
                        title={d.name}
                        onClick={() => toggleWeekday(d.dow)}
                        className={`w-7 h-7 rounded-full text-[11px] font-semibold border transition-colors ${
                          weekdays.includes(d.dow)
                            ? "bg-primary/15 text-primary border-primary/40"
                            : "bg-muted/40 text-muted-foreground border-border/40 hover:bg-muted/60"
                        }`}
                      >
                        {d.letter}
                      </button>
                    ))}
                  </div>
                  <div className="flex gap-1.5 mt-2">
                    {[
                      { label: "Weekdays", days: [1, 2, 3, 4, 5] },
                      { label: "Weekends", days: [0, 6] },
                      { label: "Every day", days: [0, 1, 2, 3, 4, 5, 6] },
                    ].map((p) => (
                      <button
                        key={p.label}
                        type="button"
                        onClick={() => setWeekdays(p.days)}
                        className="text-[10px] px-2 py-0.5 rounded-full bg-muted/40 text-muted-foreground hover:bg-muted/70 hover:text-foreground border border-border/30 transition-colors"
                      >
                        {p.label}
                      </button>
                    ))}
                  </div>
                </div>
                <div>
                  <label className={labelCls}>Time (your local time)</label>
                  <input
                    type="time"
                    value={time}
                    onChange={(e) => setTime(e.target.value)}
                    className={inputCls}
                  />
                </div>
              </div>
            )}

            {mode === "advanced" && (
              <div>
                <label className={labelCls}>Cron expression (UTC)</label>
                <input
                  type="text"
                  value={cron}
                  onChange={(e) => setCron(e.target.value)}
                  placeholder="0 9 * * 1-5"
                  spellCheck={false}
                  className={`${inputCls} font-mono`}
                />
                <p className="text-[10px] text-muted-foreground mt-1">
                  Five fields: minute hour day month weekday — interpreted in UTC.
                </p>
              </div>
            )}

            {/* Task */}
            <div>
              <label className={labelCls}>Task</label>
              <textarea
                value={task}
                onChange={(e) => setTask(e.target.value)}
                placeholder="Describe what should happen each time this fires…"
                rows={3}
                className={`${inputCls} resize-none`}
              />
              <p className="text-[10px] text-muted-foreground mt-1">
                This instruction runs every time the schedule fires.
              </p>
            </div>

            {/* Live preview */}
            <div className="rounded-lg border border-border/40 bg-background/60 px-3 py-2.5">
              {preview ? (
                <div className="flex items-start gap-2">
                  <CalendarClock className="w-3.5 h-3.5 text-primary mt-0.5 flex-shrink-0" />
                  <div className="min-w-0">
                    <p className="text-xs text-foreground font-medium">{preview.label}</p>
                    {preview.next && (
                      <p className="text-[10.5px] text-muted-foreground mt-0.5">{preview.next}</p>
                    )}
                  </div>
                </div>
              ) : (
                <p className="text-[11px] text-muted-foreground">
                  {mode === "weekly"
                    ? "Pick at least one day to preview the schedule."
                    : mode === "advanced"
                      ? "Enter a valid 5-field cron expression to preview."
                      : "Complete the schedule to see a preview."}
                </p>
              )}
            </div>

            {error && (
              <div className="px-3 py-2 rounded-lg border border-destructive/30 bg-destructive/5 text-xs text-destructive flex items-center gap-2">
                <AlertCircle className="w-3.5 h-3.5 flex-shrink-0" />
                <span className="break-words">{error}</span>
              </div>
            )}
          </div>

          {/* Footer */}
          <div className="flex items-center justify-end gap-2 px-5 py-3 border-t border-border/60">
            <button
              onClick={onClose}
              disabled={busy}
              className="px-3 py-1.5 text-xs font-medium text-muted-foreground hover:text-foreground hover:bg-muted/50 rounded-md transition-colors disabled:opacity-40"
            >
              Cancel
            </button>
            <button
              onClick={handleCreate}
              disabled={!valid || busy}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold bg-primary text-primary-foreground hover:bg-primary/90 rounded-md transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {busy && <Loader2 className="w-3 h-3 animate-spin" />}
              {busy ? "Creating…" : "Create schedule"}
            </button>
          </div>
        </div>
      </div>
    </>
  );
}
