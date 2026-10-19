/**
 * "Report a problem" — a self-contained header action (button + modal) for a
 * session. Drop `<SessionReportAction sessionId={...} />` into a page's header
 * actions; it manages its own modal state. Packages the session locally
 * (credential-scrubbed), uploads it for the team, and optionally saves a copy.
 */

import { useState } from "react";
import { createPortal } from "react-dom";
import { Flag, X, Loader2, Check, AlertCircle } from "lucide-react";

import { submitSessionReport, type Severity } from "@/api/sessionReport";
import { Tooltip } from "@/components/Tooltip";

const SEVERITIES: { value: Severity; label: string }[] = [
  { value: "low", label: "Low" },
  { value: "medium", label: "Medium" },
  { value: "high", label: "High" },
  { value: "critical", label: "Critical" },
];

export default function SessionReportAction({ sessionId }: { sessionId: string }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Tooltip label="Report a problem">
        <button
          onClick={() => setOpen(true)}
          aria-label="Report a problem with this session"
          className="w-7 h-7 rounded-md flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-muted/60 transition-colors"
        >
          <Flag className="w-4 h-4" />
        </button>
      </Tooltip>
      {open && <ReportModal sessionId={sessionId} onClose={() => setOpen(false)} />}
    </>
  );
}

export function ReportModal({
  sessionId,
  onClose,
  initialDescription = "",
  title = "Report a problem",
  subtitle = "Sends this session's data so we can investigate.",
}: {
  sessionId: string;
  onClose: () => void;
  initialDescription?: string;
  title?: string;
  subtitle?: string;
}) {
  const [description, setDescription] = useState(initialDescription);
  const [severity, setSeverity] = useState<Severity>("medium");
  const [saveLocal, setSaveLocal] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<{ savedTo?: string; bytes: number } | null>(null);

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      const res = await submitSessionReport({ sessionId, description, severity, saveLocal });
      setDone({ savedTo: res.savedTo, bytes: res.bytes });
    } catch (e) {
      const msg = e && typeof e === "object" && "body" in e
        ? ((e as { body?: { error?: string } }).body?.error ?? null)
        : null;
      setError(msg || (e instanceof Error ? e.message : "Failed to submit report"));
    } finally {
      setBusy(false);
    }
  }

  // Portal to <body>: the header bar uses backdrop-blur, which makes it the
  // containing block for position:fixed — rendering the overlay in-place would
  // trap it inside the 48px header instead of covering the viewport.
  return createPortal(
    <>
      <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm" onClick={busy ? undefined : onClose} />
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4 pointer-events-none">
        <div className="bg-card border border-border rounded-xl shadow-2xl w-full max-w-md pointer-events-auto max-h-[90vh] overflow-y-auto">
          {/* Header */}
          <div className="flex items-start justify-between px-5 pt-5 pb-3 border-b border-border/60">
            <div className="flex items-center gap-3">
              <div className="w-8 h-8 rounded-lg bg-primary/10 border border-primary/20 flex items-center justify-center">
                <Flag className="w-4 h-4 text-primary" />
              </div>
              <div>
                <h2 className="text-sm font-semibold text-foreground">{title}</h2>
                <p className="text-[11px] text-muted-foreground">{subtitle}</p>
              </div>
            </div>
            <button
              onClick={onClose}
              className="p-1.5 rounded-md hover:bg-muted/60 text-muted-foreground hover:text-foreground transition-colors"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          {/* Body */}
          {done ? (
            <div className="px-5 py-6 space-y-3 text-center">
              <div className="w-10 h-10 rounded-full bg-emerald-500/10 border border-emerald-500/30 flex items-center justify-center mx-auto">
                <Check className="w-5 h-5 text-emerald-500" />
              </div>
              <p className="text-sm text-foreground">Thanks — your report was submitted.</p>
              {done.savedTo && (
                <p className="text-[11px] text-muted-foreground break-all">Saved a copy to {done.savedTo}</p>
              )}
              <button className="text-xs px-4 py-1.5 rounded-md bg-primary text-primary-foreground" onClick={onClose}>
                Close
              </button>
            </div>
          ) : (
            <div className="px-5 py-4 space-y-3">
              <div>
                <label className="block text-[11px] font-medium text-muted-foreground mb-1">
                  What went wrong?
                </label>
                <textarea
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  rows={4}
                  placeholder="Describe the problem (what you expected vs. what happened)…"
                  className="w-full bg-muted/30 border border-border/50 rounded-lg px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-primary/40 resize-none"
                />
              </div>
              <div>
                <label className="block text-[11px] font-medium text-muted-foreground mb-1">Severity</label>
                <select
                  value={severity}
                  onChange={(e) => setSeverity(e.target.value as Severity)}
                  className="w-full bg-muted/30 border border-border/50 rounded-lg px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-primary/40"
                >
                  {SEVERITIES.map((s) => (
                    <option key={s.value} value={s.value}>{s.label}</option>
                  ))}
                </select>
              </div>
              <label className="flex items-center gap-2 text-xs text-muted-foreground cursor-pointer">
                <input type="checkbox" checked={saveLocal} onChange={(e) => setSaveLocal(e.target.checked)} />
                Also save a copy of the report bundle to my computer
              </label>
              <p className="text-[11px] text-muted-foreground/80 leading-relaxed">
                The bundle includes this session's messages, tool activity, screenshots, and logs
                for debugging. API keys and tokens are removed; everything else is kept. It uploads
                securely to your team's storage.
              </p>
              {error && (
                <div className="flex items-start gap-2 text-[11px] text-destructive bg-destructive/10 border border-destructive/20 rounded-md px-3 py-2">
                  <AlertCircle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
                  <span>{error}</span>
                </div>
              )}
              <div className="flex justify-end gap-2 pt-1">
                <button
                  onClick={onClose}
                  disabled={busy}
                  className="text-xs px-4 py-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/60"
                >
                  Cancel
                </button>
                <button
                  onClick={submit}
                  disabled={busy}
                  className="text-xs px-4 py-1.5 rounded-md bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-50 flex items-center gap-1.5"
                >
                  {busy && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                  {busy ? "Submitting…" : "Submit report"}
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </>,
    document.body,
  );
}
