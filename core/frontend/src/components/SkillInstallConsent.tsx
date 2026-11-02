import { useEffect, useState } from "react";
import { AlertTriangle, Loader2, Package, X } from "lucide-react";
import { skillsApi, type SkillInstallRequest } from "@/api/skills";

interface Props {
  /** The session whose queen asked. */
  sessionId: string;
  /** Changes when a request is filed or decided in this session, so the list is read again. */
  refreshKey: number;
}

/**
 * Asks the user whether to add a skill the queen wrote to the shared library,
 * where every queen and colony sees it (`write_skill(scope="global")`).
 *
 * The queen doesn't wait for the answer; she gets it as a message. Closing the
 * prompt decides nothing: the request stays and comes back the next time the
 * session opens.
 */
export default function SkillInstallConsent({ sessionId, refreshKey }: Props) {
  const [requests, setRequests] = useState<SkillInstallRequest[]>([]);
  const [closed, setClosed] = useState<ReadonlySet<string>>(new Set());
  const [deciding, setDeciding] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    skillsApi.listInstallRequests(sessionId).then(
      (res) => {
        if (!cancelled) setRequests(res.requests);
      },
      () => {
        if (!cancelled) setRequests([]);
      },
    );
    return () => {
      cancelled = true;
    };
  }, [sessionId, refreshKey]);

  useEffect(() => {
    setClosed(new Set());
  }, [sessionId]);

  const waiting = requests.filter((r) => !closed.has(r.id));
  const request = waiting[0];
  if (!request) return null;

  const close = () => {
    setError(null);
    setClosed((prev) => new Set(prev).add(request.id));
  };

  const decide = async (decision: "approve" | "deny") => {
    if (deciding) return;
    setDeciding(true);
    setError(null);
    try {
      await skillsApi.decideInstallRequest(sessionId, request.id, decision);
      setRequests((prev) => prev.filter((r) => r.id !== request.id));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't record your decision");
    } finally {
      setDeciding(false);
    }
  };

  const sections = [
    { path: "SKILL.md", content: request.body },
    ...request.files,
  ];

  return (
    <>
      <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm" onClick={close} />
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4 pointer-events-none">
        <div
          role="dialog"
          aria-label="Add a skill to the shared library"
          className="bg-card border border-border rounded-xl shadow-2xl w-full max-w-lg max-h-[85vh] flex flex-col pointer-events-auto"
        >
          {/* Header */}
          <div className="flex items-start justify-between px-5 pt-5 pb-3 border-b border-border/60">
            <div className="flex items-center gap-3">
              <div className="w-8 h-8 rounded-lg bg-primary/10 border border-primary/20 flex items-center justify-center">
                <Package className="w-4 h-4 text-primary" />
              </div>
              <div>
                <h2 className="text-sm font-semibold text-foreground">
                  Add a skill to the shared library?
                </h2>
                <p className="text-[11px] text-muted-foreground">
                  {request.name}
                  {waiting.length > 1 ? ` · 1 of ${waiting.length}` : ""}
                </p>
              </div>
            </div>
            <button
              onClick={close}
              aria-label="Close"
              className="p-1.5 rounded-md hover:bg-muted/60 text-muted-foreground hover:text-foreground transition-colors"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          {/* Body */}
          <div className="px-5 py-4 space-y-3 overflow-y-auto">
            <p className="text-xs text-foreground">{request.description}</p>
            <p className="text-xs text-muted-foreground">
              The queen in this chat asks to share this skill with every queen
              and colony. Declining keeps it out; either way she's told.
            </p>

            {request.replaces && (
              <div className="flex items-start gap-2 px-3 py-2 rounded-lg border border-amber-500/30 bg-amber-500/10 text-[11px] text-amber-700 dark:text-amber-400">
                <AlertTriangle className="w-3.5 h-3.5 flex-shrink-0 mt-px" />
                <span>
                  The shared library already has a skill named{" "}
                  <span className="font-mono">{request.name}</span>. Installing
                  replaces it.
                </span>
              </div>
            )}

            <div className="space-y-1.5">
              {sections.map((s) => (
                <details
                  key={s.path}
                  className="rounded-lg border border-border/60 bg-muted/20"
                >
                  <summary className="cursor-pointer select-none px-3 py-1.5 text-[11px] font-mono text-muted-foreground hover:text-foreground">
                    {s.path}
                  </summary>
                  <pre className="max-h-64 overflow-auto px-3 pb-2 text-[11px] leading-relaxed whitespace-pre-wrap break-words text-foreground">
                    {s.content}
                  </pre>
                </details>
              ))}
            </div>

            {error && (
              <div className="px-3 py-2 rounded-lg border border-destructive/20 bg-destructive/5 text-xs text-destructive">
                {error}
              </div>
            )}
          </div>

          {/* Footer */}
          <div className="flex items-center justify-end gap-2 px-5 py-4 border-t border-border/60">
            <button
              onClick={() => decide("deny")}
              disabled={deciding}
              className="px-3 py-2 rounded-lg text-sm font-medium text-muted-foreground hover:bg-muted/60 transition-colors disabled:opacity-50"
            >
              Decline
            </button>
            <button
              onClick={() => decide("approve")}
              disabled={deciding}
              className="flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {deciding && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
              Install for everyone
            </button>
          </div>
        </div>
      </div>
    </>
  );
}
