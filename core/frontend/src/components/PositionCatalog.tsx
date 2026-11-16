import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { queensApi, type QueenProfile } from "@/api/queens";
import { ApiError } from "@/api/client";
import { useColony } from "@/context/ColonyContext";
import { activateQueen, isQueenDecommissioned, useMe, useQueenDecommission, useSetQueenLead } from "@/lib/me";
import { orderQueens } from "@/lib/colony-registry";
import { QUEEN_LEADERS, queenFunctionLabel, type QueenLeader } from "@/lib/queen-leaders";
import type { QueenProfileSummary } from "@/types/colony";
import QueenAvatar from "./QueenAvatar";
import QueenPortraitGlyph, { HEX_CLIP } from "./QueenPortraitGlyph";

/**
 * The positions on the user's team, for the org chart: every queen holds one, the shipped
 * functions and the ones the user made alike. A position is added (a new queen, its name her
 * title), removed (her files stay, and she can be restored), or decommissioned; a shipped
 * function also offers the leaders she can be modelled after.
 */

type Removed = Pick<QueenProfile, "id" | "name" | "title">;

function LeaderCard({ leader, isCurrent, saving, onHire }: { leader: QueenLeader; isCurrent: boolean; saving: boolean; onHire: () => void }) {
  return (
    <div
      className={`flex flex-col items-center w-[7.5rem] flex-shrink-0 rounded-xl border bg-card p-3 text-center ${
        isCurrent ? "border-primary/40 ring-1 ring-primary/20" : "border-border/60"
      }`}
      title={leader.bio}
    >
      <div className="w-11 h-11 bg-primary/15 flex items-center justify-center overflow-hidden mb-2" style={{ clipPath: HEX_CLIP }}>
        <QueenPortraitGlyph p={leader.p} frame={false} className="w-full h-full" />
      </div>
      <span className="text-xs font-semibold text-foreground line-clamp-1 w-full">{leader.n}</span>
      <span className="text-[10px] text-muted-foreground mt-0.5 line-clamp-1 w-full">{leader.t}</span>
      <button
        onClick={onHire}
        disabled={isCurrent || saving}
        className={`mt-2 w-full rounded-md border border-primary/30 px-2 py-1 text-[10px] font-medium transition-colors ${
          isCurrent ? "text-primary cursor-default opacity-80" : "text-primary hover:bg-primary/10 disabled:opacity-50"
        }`}
      >
        {isCurrent ? "Current lead" : saving ? "Hiring…" : "Hire"}
      </button>
    </div>
  );
}

/** A position with no leaders to hire: the queen holding it. */
function HolderCard({ queen }: { queen: QueenProfileSummary }) {
  const navigate = useNavigate();
  return (
    <div className="flex flex-col items-center w-[7.5rem] flex-shrink-0 rounded-xl border border-primary/40 ring-1 ring-primary/20 bg-card p-3 text-center">
      <QueenAvatar queen={queen} className="w-11 h-11 mb-2 text-sm" />
      <span className="text-xs font-semibold text-foreground line-clamp-1 w-full">{queen.name || queen.id}</span>
      <span className="text-[10px] text-muted-foreground mt-0.5 line-clamp-1 w-full">Holds it</span>
      <button
        onClick={() => navigate(`/queen/${queen.id}/profile`)}
        className="mt-2 w-full rounded-md border border-border/60 px-2 py-1 text-[10px] font-medium text-muted-foreground transition-colors hover:text-foreground hover:border-primary/30"
      >
        Profile
      </button>
    </div>
  );
}

function Position({
  queen,
  label,
  decommissioned,
  currentLeaderId,
  hireSaving,
  onHire,
  onRemove,
}: {
  queen: QueenProfileSummary;
  label: string;
  decommissioned: boolean;
  currentLeaderId: string | null;
  hireSaving: boolean;
  onHire: (leader: QueenLeader) => void;
  onRemove: () => Promise<void>;
}) {
  const { setDecommissioned, saving } = useQueenDecommission(queen.id);
  const [confirming, setConfirming] = useState(false);
  const [removing, setRemoving] = useState(false);
  const leaders = QUEEN_LEADERS[queen.id] ?? [];
  return (
    <div className={decommissioned ? "opacity-60" : ""}>
      <div className="flex flex-wrap items-center gap-2 mb-2">
        <span className="text-[11px] font-semibold text-foreground/80">{label}</span>
        {decommissioned && (
          <>
            <span className="text-[9px] uppercase tracking-wider text-muted-foreground rounded bg-muted px-1.5 py-0.5">Decommissioned</span>
            <button
              onClick={() => void setDecommissioned(false)}
              disabled={saving}
              className="rounded-md border border-primary/30 px-2 py-0.5 text-[10px] font-medium text-primary transition-colors hover:bg-primary/10 disabled:opacity-50"
            >
              {saving ? "…" : "Re-enable"}
            </button>
          </>
        )}
        <span className="ml-auto flex items-center gap-2">
          {confirming ? (
            <>
              <span className="text-[10px] text-muted-foreground">Remove this position? Her chats and memory stay, to restore.</span>
              <button
                onClick={async () => {
                  setRemoving(true);
                  try {
                    await onRemove();
                  } finally {
                    setRemoving(false);
                    setConfirming(false);
                  }
                }}
                disabled={removing}
                className="rounded-md border border-red-500/40 px-2 py-0.5 text-[10px] font-medium text-red-600 transition-colors hover:bg-red-500/10 disabled:opacity-50"
              >
                {removing ? "…" : "Remove"}
              </button>
              <button onClick={() => setConfirming(false)} className="px-1 text-[10px] text-muted-foreground hover:text-foreground">
                Cancel
              </button>
            </>
          ) : (
            <button
              onClick={() => setConfirming(true)}
              title="Take this position out of the catalog"
              className="rounded-md px-2 py-0.5 text-[10px] font-medium text-muted-foreground transition-colors hover:text-red-600 hover:bg-red-500/[0.06]"
            >
              Remove
            </button>
          )}
        </span>
      </div>
      <div className="flex flex-wrap gap-2">
        {leaders.length > 0 ? (
          leaders.map((leader) => (
            <LeaderCard key={leader.id} leader={leader} isCurrent={currentLeaderId === leader.id} saving={hireSaving} onHire={() => onHire(leader)} />
          ))
        ) : (
          <HolderCard queen={queen} />
        )}
      </div>
    </div>
  );
}

function NewPositionDialog({ onClose }: { onClose: () => void }) {
  const { refresh } = useColony();
  const navigate = useNavigate();
  const [position, setPosition] = useState("");
  const [name, setName] = useState("");
  const [persona, setPersona] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const submit = async () => {
    if (!position.trim() || !name.trim() || saving) return;
    setSaving(true);
    setError(null);
    try {
      const { queen } = await queensApi.createQueen({
        name: name.trim(),
        title: position.trim(),
        persona: persona.trim() || undefined,
      });
      // On the team at once: a position created then hidden would look like it failed.
      activateQueen(queen.id);
      refresh();
      onClose();
      navigate(`/queen/${queen.id}/profile`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setSaving(false);
    }
  };
  const inputCls =
    "w-full mb-3 rounded-md border border-border/60 bg-background px-2.5 py-1.5 text-xs text-foreground outline-none focus:border-primary/50";
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onMouseDown={onClose}>
      <div className="w-[26rem] max-w-[92vw] rounded-xl border border-border/60 bg-card p-5 shadow-xl" onMouseDown={(e) => e.stopPropagation()}>
        <div className="text-sm font-semibold text-foreground mb-3">New position</div>
        <label className="block text-[11px] text-muted-foreground mb-1">Position *</label>
        <input value={position} onChange={(e) => setPosition(e.target.value)} autoFocus className={inputCls} placeholder="e.g. Illustrator, Head of Archives" />
        <label className="block text-[11px] text-muted-foreground mb-1">Her name *</label>
        <input value={name} onChange={(e) => setName(e.target.value)} className={inputCls} placeholder="Who holds it" />
        <label className="block text-[11px] text-muted-foreground mb-1">Persona — free text, becomes her core traits</label>
        <textarea
          value={persona}
          onChange={(e) => setPersona(e.target.value)}
          rows={4}
          className={inputCls + " resize-y"}
          placeholder="Voice, temperament, duties… (her profile page can take it from here)"
        />
        {error && <div className="mb-3 text-[11px] text-red-500">{error}</div>}
        <div className="flex justify-end gap-2">
          <button
            onClick={onClose}
            className="rounded-md border border-border/60 px-3 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:text-foreground"
          >
            Cancel
          </button>
          <button
            onClick={() => void submit()}
            disabled={!position.trim() || !name.trim() || saving}
            className="rounded-md border border-primary/40 bg-primary/10 px-3 py-1.5 text-xs font-medium text-primary transition-colors hover:bg-primary/20 disabled:opacity-50"
          >
            {saving ? "Creating…" : "Create"}
          </button>
        </div>
      </div>
    </div>
  );
}

export default function PositionCatalog() {
  const { me } = useMe();
  const { refresh, queenProfiles } = useColony();
  const { setLead, savingQueenId } = useSetQueenLead();
  const [newOpen, setNewOpen] = useState(false);
  const [removed, setRemoved] = useState<Removed[]>([]);
  const [error, setError] = useState<string | null>(null);

  const loadRemoved = useCallback(async () => {
    try {
      setRemoved((await queensApi.listRemoved()).queens);
    } catch {
      // Nothing to offer back is no reason to fail the catalog.
    }
  }, []);
  useEffect(() => {
    void loadRemoved();
  }, [loadRemoved]);

  const change = async (action: () => Promise<unknown>, fallback: string) => {
    try {
      await action();
      setError(null);
      refresh();
      await loadRemoved();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : fallback);
    }
  };

  const positions = orderQueens(queenProfiles, Object.keys(me?.preferences?.queens ?? {}));

  return (
    <div className="space-y-4">
      {positions.map((queen) => {
        const leaders = QUEEN_LEADERS[queen.id] ?? [];
        // The current lead: an explicit hire wins; otherwise the leader whose name she bears. None
        // matched leaves every leader hireable rather than marking the wrong one current.
        const currentLeaderId =
          me?.preferences?.queens?.[queen.id]?.id ?? leaders.find((l) => l.n === queen.name)?.id ?? null;
        return (
          <Position
            key={queen.id}
            queen={queen}
            label={queenFunctionLabel(queenProfiles, queen.id)}
            decommissioned={isQueenDecommissioned(me, queen.id)}
            currentLeaderId={currentLeaderId}
            hireSaving={savingQueenId === queen.id}
            onHire={async (leader) => {
              await setLead(queen.id, { leaderId: leader.id, name: leader.n, title: leader.t, bio: leader.bio, portrait: leader.p });
              // Her new name and portrait show once the profiles are read again.
              refresh();
            }}
            onRemove={() => change(() => queensApi.removeQueen(queen.id), "Couldn't remove the position")}
          />
        );
      })}

      <div>
        <button
          onClick={() => setNewOpen(true)}
          className="rounded-md border border-primary/30 px-2.5 py-1 text-[11px] font-medium text-primary transition-colors hover:bg-primary/10"
        >
          + New position
        </button>
      </div>

      {removed.length > 0 && (
        <div>
          <div className="text-[11px] font-semibold text-foreground/80 mb-2">Removed positions</div>
          <div className="flex flex-col gap-2">
            {removed.map((q) => (
              <div key={q.id} className="flex items-center gap-3 rounded-lg border border-border/60 bg-background/60 px-3 py-2">
                <div className="min-w-0">
                  <div className="text-xs font-semibold text-foreground truncate">{q.title || q.name || q.id}</div>
                  <div className="text-[10px] text-muted-foreground truncate">{q.name || q.id}</div>
                </div>
                <button
                  onClick={() => void change(() => queensApi.restoreQueen(q.id), "Couldn't restore the position")}
                  className="ml-auto rounded-md border border-primary/30 px-2 py-0.5 text-[10px] font-medium text-primary transition-colors hover:bg-primary/10"
                >
                  Restore
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {error && <div className="text-[11px] text-red-500">{error}</div>}
      {newOpen && <NewPositionDialog onClose={() => setNewOpen(false)} />}
    </div>
  );
}
