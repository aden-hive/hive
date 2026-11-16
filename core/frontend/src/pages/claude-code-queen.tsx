import { useCallback, useEffect, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { AlertCircle, ArrowLeft, Loader2, RefreshCw, SquareTerminal, TriangleAlert, Wrench } from "lucide-react";
import { claudeCodeQueensApi, type ClaudeCodeQueen, type TranscriptEntry } from "@/api/claudeCodeQueens";

/**
 * A queen run by Claude Code, seen from Hive: the queens she writes with, and what was said and
 * done in each conversation. Read only: she lives in Claude Code, and her letters are her input.
 */

const REFRESH_MS = 15_000;

function when(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString(undefined, { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function Entry({ entry }: { entry: TranscriptEntry }) {
  if (entry.kind === "letter") {
    return (
      <div className="rounded-lg border border-border/60 bg-muted/40 px-3 py-2">
        <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">Handed to her · {when(entry.at)}</div>
        <div className="text-sm whitespace-pre-wrap break-words">{entry.text}</div>
      </div>
    );
  }
  if (entry.kind === "text") {
    return <div className="text-sm whitespace-pre-wrap break-words px-1">{entry.text}</div>;
  }
  if (entry.kind === "tool") {
    return (
      <div className="flex items-start gap-2 text-xs px-1">
        <Wrench className="w-3.5 h-3.5 mt-0.5 shrink-0 text-muted-foreground" />
        <div className="min-w-0">
          <span className="font-semibold">{entry.tool}</span>
          <code className="ml-2 font-mono text-muted-foreground break-all">{entry.text}</code>
        </div>
      </div>
    );
  }
  return (
    <pre
      className={`ml-5 max-h-48 overflow-auto rounded-md border px-2 py-1.5 font-mono text-[11px] whitespace-pre-wrap break-words ${
        entry.error ? "border-destructive/40 text-destructive" : "border-border/50 text-muted-foreground"
      }`}
    >
      {entry.text || "(no output)"}
    </pre>
  );
}

export default function ClaudeCodeQueenPage() {
  const { queenId = "" } = useParams<{ queenId: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  // undefined while loading, null when there is no such queen.
  const [queen, setQueen] = useState<ClaudeCodeQueen | null | undefined>(undefined);
  const [selected, setSelected] = useState<string | null>(null);
  const [entries, setEntries] = useState<TranscriptEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const { queens } = await claudeCodeQueensApi.list();
      const found = queens.find((q) => q.id === queenId) ?? null;
      setQueen(found);
      setSelected((current) => current ?? found?.conversations[0]?.session_id ?? null);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [queenId]);

  useEffect(() => {
    void load();
    const timer = setInterval(() => void load(), REFRESH_MS);
    return () => clearInterval(timer);
  }, [load]);

  // Re-read the open conversation whenever the list refreshes: a turn may have added to it.
  useEffect(() => {
    if (!selected) {
      setEntries(null);
      return;
    }
    let stale = false;
    claudeCodeQueensApi
      .transcript(queenId, selected)
      .then((r) => !stale && setEntries(r.entries))
      .catch((e) => !stale && setError(e instanceof Error ? e.message : String(e)));
    return () => {
      stale = true;
    };
  }, [queenId, selected, queen]);

  const back = () => (location.key === "default" ? navigate("/org-chart") : navigate(-1));
  const open = queen?.conversations.find((c) => c.session_id === selected);

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      <div className="px-6 py-4 border-b border-border/60 flex items-center gap-3">
        <button onClick={back} className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
          <ArrowLeft className="w-3.5 h-3.5" /> Back
        </button>
        <div className="w-9 h-9 rounded-full bg-primary/10 text-primary flex items-center justify-center">
          <SquareTerminal className="w-4.5 h-4.5" />
        </div>
        <div className="min-w-0">
          <h2 className="text-lg font-semibold leading-tight">{queen?.name ?? queenId}</h2>
          <div className="text-xs text-muted-foreground">
            {queen
              ? `${queen.title} · ${queen.auth === "subscription" ? "subscription" : "API key"} · ${queen.permission_mode}${
                  queen.model ? ` · ${queen.model}` : ""
                } · read only`
              : " "}
          </div>
        </div>
        <button
          onClick={() => void load()}
          title="Refresh"
          className="ml-auto p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted"
        >
          <RefreshCw className="w-4 h-4" />
        </button>
      </div>

      {error && (
        <div className="mx-6 mt-3 flex items-center gap-2 text-xs text-destructive">
          <AlertCircle className="w-3.5 h-3.5" /> {error}
        </div>
      )}

      {queen?.auth === "subscription" && (
        <div role="note" className="mx-6 mt-3 flex items-start gap-2 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs">
          <TriangleAlert className="w-3.5 h-3.5 mt-0.5 shrink-0 text-amber-600" />
          <span>
            She runs on a Claude subscription signed in on this computer. Running a plan unattended for other agents may
            break its terms, and the account may be limited or closed: that is at your own risk. An Anthropic API key is the
            supported way.
          </span>
        </div>
      )}

      {queen === undefined ? (
        <div className="flex-1 flex items-center justify-center text-muted-foreground">
          <Loader2 className="w-5 h-5 animate-spin" />
        </div>
      ) : queen === null ? (
        <div className="flex-1 flex items-center justify-center text-sm text-muted-foreground">
          No queen {queenId} runs on Claude Code here (queen_mail.claude_code in configuration.json).
        </div>
      ) : (
        <div className="flex-1 flex overflow-hidden">
          <aside className="w-64 shrink-0 border-r border-border/60 overflow-y-auto p-2">
            <div className="px-2 py-1.5 text-[11px] uppercase tracking-wider text-muted-foreground">Conversations</div>
            {queen.conversations.length === 0 && (
              <div className="px-2 py-1 text-xs text-muted-foreground">No queen has written to her yet.</div>
            )}
            {queen.conversations.map((c) => (
              <button
                key={c.session_id}
                onClick={() => setSelected(c.session_id)}
                className={`w-full text-left rounded-md px-2 py-2 mb-0.5 ${
                  c.session_id === selected ? "bg-primary/10" : "hover:bg-muted"
                }`}
              >
                <div className="flex items-center gap-1.5 text-sm font-medium">
                  {c.peer_name}
                  {c.running && <span className="w-2 h-2 rounded-full bg-emerald-500" title="She is working on it now" />}
                </div>
                <div className="text-[11px] text-muted-foreground">
                  {c.letters} {c.letters === 1 ? "letter" : "letters"} · {when(c.last_at)}
                </div>
              </button>
            ))}
          </aside>
          <section className="flex-1 overflow-y-auto px-6 py-4">
            {open && (
              <div className="text-xs text-muted-foreground mb-3">
                With {open.peer_name} ({open.peer}) · what she ends each turn with goes back to {open.peer_name}
              </div>
            )}
            {entries === null ? null : entries.length === 0 ? (
              <div className="text-sm text-muted-foreground">Nothing recorded yet.</div>
            ) : (
              <div className="flex flex-col gap-2.5 max-w-3xl">
                {entries.map((entry, i) => (
                  <Entry key={i} entry={entry} />
                ))}
              </div>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
