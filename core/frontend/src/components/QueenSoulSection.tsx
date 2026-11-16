import { useCallback, useEffect, useRef, useState } from "react";
import { AlertCircle, History, Loader2, Pencil, Sparkles } from "lucide-react";
import { queensApi, type QueenSoul, type SoulEdit, type SoulItem, type SoulSectionView } from "@/api/queens";
import { ApiError } from "@/api/client";

/**
 * The queen's soul: the short, first-person self-description she revises once a day from her chats
 * (configuration.json `soul.queens`). Shows it by section with each section's room, the changes her
 * last reflection proposed (to approve one by one, or dismiss), a hand editor, and its history.
 * Styled for her profile page (the `qp-` classes).
 */

type Enabled = Extract<QueenSoul, { enabled: true }>;

const OP_MARK: Record<SoulEdit["op"], string> = { add: "+", update: "~", remove: "−" };

function shortDate(day: string): string {
  const m = /^\d{4}-(\d{2})-(\d{2})/.exec(day);
  return m ? `${Number(m[1])}/${Number(m[2])}` : day;
}

/** One line per item: "YYYY-MM-DD text", the date optional. */
function toLines(items: SoulItem[]): string {
  return items.map((i) => (i.date ? `${i.date} ${i.text}` : i.text)).join("\n");
}

function fromLines(text: string): SoulItem[] {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const m = /^(\d{4}-\d{2}-\d{2})\s+(.+)$/.exec(line);
      return m ? { date: m[1], text: m[2] } : { date: "", text: line };
    });
}

/** How a section keeps its items, when that differs from the plain case. */
function rules(section: SoulSectionView): string {
  const parts = [];
  if (section.max_age_days) parts.push(`Items last ${section.max_age_days} days`);
  if (section.evidence > 1) parts.push(`Changes need ${section.evidence} sources`);
  return parts.join(" · ");
}

function Room({ used, limit }: { used: number; limit: number }) {
  return (
    <span className="qp-soul-room" data-over={used > limit ? "" : undefined}>
      {used} / {limit}
    </span>
  );
}

function Gauge({ used, limit }: { used: number; limit: number }) {
  return (
    <div className="qp-gauge" data-over={used > limit ? "" : undefined} aria-hidden>
      <span style={{ width: `${Math.min(100, (used / Math.max(1, limit)) * 100)}%` }} />
    </div>
  );
}

export default function QueenSoulSection({ queenId, onChange }: { queenId: string; onChange?: (soul: QueenSoul) => void }) {
  const [soul, setSoul] = useState<QueenSoul | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // The sections being edited, as text; null = editor closed.
  const [draft, setDraft] = useState<Record<string, string> | null>(null);
  const [accepted, setAccepted] = useState<Set<number>>(new Set());
  const [showHistory, setShowHistory] = useState(false);

  // Read through a ref, so a caller's new callback each render doesn't reload her soul.
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;
  const show = useCallback((next: QueenSoul) => {
    setSoul(next);
    onChangeRef.current?.(next);
    if (next.enabled && next.proposal) setAccepted(new Set(next.proposal.edits.map((_, i) => i)));
  }, []);

  const load = useCallback(async () => {
    try {
      show(await queensApi.getSoul(queenId));
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't load her soul");
    }
  }, [queenId, show]);
  useEffect(() => {
    void load();
  }, [load]);

  // While she reflects or answers probes, look again every few seconds.
  const reflecting = soul?.enabled ? soul.reflecting || soul.probing : false;
  useEffect(() => {
    if (!reflecting) return;
    const timer = setInterval(() => void load(), 3000);
    return () => clearInterval(timer);
  }, [reflecting, load]);

  const act = async (action: () => Promise<QueenSoul>, fallback: string): Promise<boolean> => {
    setBusy(true);
    try {
      show(await action());
      setError(null);
      return true;
    } catch (e) {
      setError(e instanceof ApiError ? e.message : fallback);
      return false;
    } finally {
      setBusy(false);
    }
  };

  const start = async (action: () => Promise<unknown>, fallback: string) => {
    setBusy(true);
    try {
      await action();
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : fallback);
    } finally {
      setBusy(false);
    }
  };

  const errorLine = error && (
    <p className="qp-error">
      <AlertCircle className="w-3.5 h-3.5" /> {error}
    </p>
  );

  if (soul === null) {
    return (
      <div className="qp-soul">
        <div className="qp-card qp-soul-status">{errorLine || <span className="qp-meta inline-flex items-center gap-2"><Loader2 className="w-3.5 h-3.5 animate-spin" /> Loading…</span>}</div>
      </div>
    );
  }
  if (!soul.enabled) {
    return (
      <div className="qp-empty">
        She has no soul yet. Turn it on in configuration.json under <code>soul.queens.{queenId}</code>.
      </div>
    );
  }

  const s: Enabled = soul;
  const titleOf = (key: string) => s.sections.find((x) => x.key === key)?.title ?? key;
  const proposal = s.proposal;

  return (
    <div className="qp-soul">
      <div className="qp-card qp-soul-status">
        <div className="min-w-0">
          <p className="qp-soul-version">{s.version ? `Version ${s.version}` : "Not written yet"}</p>
          <p className="qp-soul-line">
            {s.mode === "review" ? "Her changes wait for your approval" : "Her changes apply at once"} · reflects daily after {s.hour}:00
            {s.last_run ? ` · last ${s.last_run}: ${s.last_result ?? ""}` : ""}
          </p>
        </div>
        {draft === null && (
          <div className="qp-soul-actions">
            {s.reflecting && (
              <span className="qp-meta inline-flex items-center gap-1.5">
                <Loader2 className="w-3.5 h-3.5 animate-spin" /> Reflecting…
              </span>
            )}
            <button
              className="qp-btn"
              data-size="sm"
              onClick={() => void start(() => queensApi.reflectSoul(queenId, s.version === 0), "Couldn't start the reflection")}
              disabled={busy || s.reflecting || proposal !== null}
              title={proposal ? "Decide on the waiting changes first" : undefined}
            >
              <Sparkles className="w-3.5 h-3.5" />
              {s.version === 0 ? "Write the first draft" : "Reflect now"}
            </button>
            <button
              className="qp-btn"
              data-size="sm"
              onClick={() => setDraft(Object.fromEntries(s.sections.map((x) => [x.key, toLines(x.items)])))}
              disabled={busy}
            >
              <Pencil className="w-3.5 h-3.5" />
              Edit
            </button>
            {s.history.length > 0 && (
              <button className="qp-btn" data-size="sm" data-tone={showHistory ? undefined : "quiet"} onClick={() => setShowHistory(!showHistory)} aria-expanded={showHistory}>
                <History className="w-3.5 h-3.5" />
                History
              </button>
            )}
          </div>
        )}
      </div>

      {proposal && (
        <div className="qp-proposal">
          <p className="qp-proposal-kicker">Waiting for you</p>
          <h3 className="qp-proposal-title">
            {proposal.bootstrap ? "Her first draft" : "Her reflection"} · {proposal.edits.length} {proposal.edits.length === 1 ? "change" : "changes"}
          </h3>
          {proposal.summary && <p className="qp-proposal-summary">{proposal.summary}</p>}
          <ul className="qp-changes">
            {proposal.edits.map((edit, i) => (
              <li key={i} className="qp-change">
                <input
                  type="checkbox"
                  aria-label={`Apply change ${i + 1}`}
                  checked={accepted.has(i)}
                  onChange={(e) => {
                    const next = new Set(accepted);
                    if (e.target.checked) next.add(i);
                    else next.delete(i);
                    setAccepted(next);
                  }}
                />
                <span className="qp-op" data-op={edit.op} aria-hidden>
                  {OP_MARK[edit.op]}
                </span>
                <div className="min-w-0">
                  <p className="qp-change-where">
                    {titleOf(edit.section)}
                    {edit.expired && " · too old"}
                  </p>
                  <p className="qp-change-text">
                    {edit.op !== "add" && <span className="qp-change-old">{edit.old}</span>}
                    {edit.op !== "remove" && <span>{edit.text}</span>}
                  </p>
                  {edit.evidence.map((ev, j) => (
                    <p key={j} className="qp-quote">
                      “{ev.quote}” — {ev.where}
                    </p>
                  ))}
                </div>
              </li>
            ))}
          </ul>
          <div className="qp-proposal-foot">
            <button
              className="qp-btn"
              data-tone="primary"
              data-size="sm"
              onClick={() => void act(() => queensApi.decideSoulProposal(queenId, proposal.id, [...accepted].sort((a, b) => a - b)), "Couldn't apply the changes")}
              disabled={busy || accepted.size === 0}
            >
              Apply selected <span className="opacity-70">({accepted.size})</span>
            </button>
            <button
              className="qp-btn"
              data-size="sm"
              onClick={() => void act(() => queensApi.decideSoulProposal(queenId, proposal.id, []), "Couldn't dismiss the proposal")}
              disabled={busy}
            >
              Dismiss all
            </button>
            {s.probes > 0 && (
              <button
                className="qp-btn"
                data-size="sm"
                onClick={() => void start(() => queensApi.probeSoulProposal(queenId, proposal.id), "Couldn't try her out")}
                disabled={busy || s.probing}
              >
                {s.probing ? (
                  <>
                    <Loader2 className="w-3.5 h-3.5 animate-spin" /> Trying her out…
                  </>
                ) : (
                  `Try her with these changes (${s.probes} ${s.probes === 1 ? "question" : "questions"})`
                )}
              </button>
            )}
          </div>
          {proposal.probes.length > 0 && (
            <div className="qp-probes">
              {proposal.probes.map((p, i) => (
                <div key={i}>
                  <p className="qp-probe-q">{p.q}</p>
                  {p.anchor && <p className="qp-probe-anchor">Like her: {p.anchor}</p>}
                  <div className="qp-probe-pair">
                    <div>
                      <span className="qp-probe-label">Now</span>
                      {p.before}
                    </div>
                    <div data-after>
                      <span className="qp-probe-label">With the changes</span>
                      {p.after}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {draft === null ? (
        <div className="qp-soul-grid">
          {s.sections.map((section) => {
            const note = rules(section);
            return (
              <article key={section.key} className="qp-card qp-soul-card">
                <header className="qp-soul-card-head">
                  <h4 className="qp-soul-card-title">{section.title}</h4>
                  <Room used={section.used} limit={section.limit} />
                </header>
                <Gauge used={section.used} limit={section.limit} />
                {note && <p className="qp-soul-rules">{note}</p>}
                {section.items.length === 0 ? (
                  <p className="qp-soul-rules mt-3">Nothing here yet.</p>
                ) : (
                  <ul className="qp-soul-items">
                    {section.items.map((item, i) => (
                      <li key={i}>
                        <span>{item.text}</span>
                        <span className="qp-soul-date">{item.date ? shortDate(item.date) : ""}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </article>
            );
          })}
        </div>
      ) : (
        <div>
          <p className="qp-hint mb-3">One item per line; start a line with YYYY-MM-DD to date it.</p>
          <div className="qp-soul-grid">
            {s.sections.map((section) => {
              const used = fromLines(draft[section.key] ?? "").reduce((n, i) => n + i.text.length, 0);
              return (
                <label key={section.key} className="qp-card qp-soul-card block">
                  <span className="qp-soul-card-head">
                    <span className="qp-soul-card-title">{section.title}</span>
                    <Room used={used} limit={section.limit} />
                  </span>
                  <Gauge used={used} limit={section.limit} />
                  <textarea
                    aria-label={`${section.title}, one item per line`}
                    value={draft[section.key] ?? ""}
                    onChange={(e) => setDraft({ ...draft, [section.key]: e.target.value })}
                    rows={Math.max(3, section.items.length + 2)}
                    className="qp-editor mt-3"
                  />
                </label>
              );
            })}
          </div>
          <div className="qp-edit-foot">
            <span />
            <div>
              <button className="qp-btn" data-tone="quiet" data-size="sm" onClick={() => setDraft(null)}>
                Cancel
              </button>
              <button
                className="qp-btn"
                data-tone="primary"
                data-size="sm"
                onClick={async () => {
                  const sections = Object.fromEntries(s.sections.map((x) => [x.key, fromLines(draft[x.key] ?? "")]));
                  if (await act(() => queensApi.setSoul(queenId, sections), "Couldn't save her soul")) setDraft(null);
                }}
                disabled={busy}
              >
                Save
              </button>
            </div>
          </div>
        </div>
      )}

      {showHistory && draft === null && (
        <ol className="qp-card qp-history">
          {s.history.map((v) => (
            <li key={v.version} data-current={v.version === s.version ? "" : undefined}>
              <span className="qp-history-v">v{v.version}</span>
              <span className="qp-meta">{v.at.slice(0, 16).replace("T", " ")}</span>
              <span className="qp-history-note">
                {v.author} · {v.note}
              </span>
              {v.version !== s.version && (
                <button
                  className="qp-btn"
                  data-size="sm"
                  onClick={() => void act(() => queensApi.rollbackSoul(queenId, v.version), "Couldn't restore that version")}
                  disabled={busy}
                >
                  Restore
                </button>
              )}
            </li>
          ))}
        </ol>
      )}

      {errorLine}
    </div>
  );
}
