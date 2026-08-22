import { useState, useCallback, useRef, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { apiUrl } from "@/api/client";
import {
  User, Component, X, Calendar, Target, Activity, ArrowRight, Clock,
  Rocket, Globe, Mail, Search, Shield, TrendingUp, Briefcase, Code,
  Database, FileText, MessageSquare, Zap, BarChart3, Users, Bot, Network,
  type LucideIcon,
} from "lucide-react";
import { useColony } from "@/context/ColonyContext";
import { activateQueen, isQueenDecommissioned, useMe, useQueenDecommission, useSetQueenLead, useSetQueenPosition, useSetQueenPositions, useResetQueenPositions } from "@/lib/me";
import { agentsApi } from "@/api/agents";
import { queensApi } from "@/api/queens";
import type { QueenProfileSummary, Colony } from "@/types/colony";
import QueenProfilePanel from "@/components/QueenProfilePanel";
import QueenPortraitGlyph from "@/components/QueenPortraitGlyph";
import { orderQueens, QUEEN_DISPLAY_ORDER } from "@/lib/colony-registry";
import {
  allPersonaSummaries,
  queenFunctionLabel,
  type PersonaSummary,
} from "@/lib/queen-leaders";
import { useLiveSessions } from "@/hooks/use-live-sessions";
import { deriveColonyStatus, describeColonyStatus, STATUS_DOT_CLASS, STATUS_LABEL, STATUS_TEXT_CLASS } from "@/lib/colony-status";
import { Tooltip } from "@/components/Tooltip";

const COLONY_ICONS: Record<string, LucideIcon> = {
  component: Component, rocket: Rocket, globe: Globe, mail: Mail,
  search: Search, shield: Shield, trending: TrendingUp, briefcase: Briefcase,
  code: Code, database: Database, file: FileText, message: MessageSquare,
  zap: Zap, chart: BarChart3, users: Users, bot: Bot,
};
const COLONY_ICON_KEYS = Object.keys(COLONY_ICONS);

/* ── Canvas layout geometry ──────────────────────────────────────────────
 * Queen cards are positioned absolutely in this fixed canvas coordinate
 * space; saved positions (preferences.queens[id].pos) are stored in the same
 * space so they restore identically. The canvas is centered in the viewport
 * and pan/zoom move the whole thing. */
const CANVAS_W = 2200;
const CANVAS_H = 1500;
const CENTER_X = CANVAS_W / 2;
const CARD_W = 140; // 8.75rem queen card
const CARD_H = 130; // 8.125rem card body (connector anchor; tags hang below)
const ROW_GAP = 28;
const CEO_W = 190;
const CEO_H = 104;
const CEO_X = CENTER_X - CEO_W / 2;
const CEO_Y = 56;
const QUEEN_ROW_Y = 336;

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

/** Default row position for a queen with no saved position. */
function defaultQueenPos(index: number, count: number): { x: number; y: number } {
  const rowW = count * CARD_W + Math.max(0, count - 1) * ROW_GAP;
  const startX = CENTER_X - rowW / 2;
  return { x: startX + index * (CARD_W + ROW_GAP), y: QUEEN_ROW_Y };
}

/* Pointy-top hexagon matching the bee-theme HiveLogo / QueenPortraitGlyph —
   used to clip org-chart node avatars into honeycomb cells instead of circles. */
const HEX_CLIP = "polygon(50% 0%, 93.3% 25%, 93.3% 75%, 50% 100%, 6.7% 75%, 6.7% 25%)";

/* ── User avatar (CEO card) ──────────────────────────────────────────── */

function UserAvatar({ initials, avatarVersion, userHasAvatar }: { initials: string; avatarVersion: number; userHasAvatar: boolean }) {
  const [hasAvatar, setHasAvatar] = useState(userHasAvatar);
  const url = apiUrl(`/config/profile/avatar?v=${avatarVersion}`);
  useEffect(() => setHasAvatar(userHasAvatar), [avatarVersion, userHasAvatar]);
  return (
    <div className="w-12 h-12 bg-primary/15 mx-auto mb-3 flex items-center justify-center overflow-hidden" style={{ clipPath: HEX_CLIP }}>
      {hasAvatar ? (
        <img src={url} alt="" className="w-full h-full object-cover" onError={() => setHasAvatar(false)} />
      ) : initials ? (
        <span className="text-sm font-bold text-primary">{initials}</span>
      ) : (
        <User className="w-5 h-5 text-primary" />
      )}
    </div>
  );
}

/* ── Colony tag ──────────────────────────────────────────────────────── */

function ColonyTag({ colony, onSelect }: { colony: Colony; onSelect: () => void }) {
  const Icon = (colony.icon && COLONY_ICONS[colony.icon]) || Component;
  return (
    <button
      onClick={onSelect}
      onMouseDown={(e) => e.stopPropagation()}
      data-tour="tour-colony-tag"
      className="flex items-center gap-1.5 rounded-lg border border-border/50 bg-muted/40 px-2.5 py-1.5 text-xs text-muted-foreground hover:border-primary/30 hover:text-foreground transition-colors w-full text-left"
    >
      <Icon className="w-3 h-3 flex-shrink-0 text-primary/60" />
      <span className="truncate">{colony.name}</span>
    </button>
  );
}

/* ── Colony detail drawer ────────────────────────────────────────────── */

function ColonyDetailPanel({ colony, queenName, onClose, onIconChange }: {
  colony: Colony; queenName: string; onClose: () => void;
  onIconChange: (colonyId: string, icon: string) => void;
}) {
  const navigate = useNavigate();
  const { byColony } = useLiveSessions();
  const [iconPickerOpen, setIconPickerOpen] = useState(false);

  const formatDate = (iso: string | null) => {
    if (!iso) return "—";
    try {
      const d = new Date(iso);
      return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" })
        + " at " + d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
    } catch { return "—"; }
  };

  const formatRelative = (iso: string | null) => {
    if (!iso) return null;
    try {
      const diff = Date.now() - new Date(iso).getTime();
      const mins = Math.floor(diff / 60000);
      if (mins < 1) return "just now";
      if (mins < 60) return `${mins}m ago`;
      const hrs = Math.floor(mins / 60);
      if (hrs < 24) return `${hrs}h ago`;
      const days = Math.floor(hrs / 24);
      return `${days}d ago`;
    } catch { return null; }
  };

  const currentIconKey = colony.icon || "component";
  const CurrentIcon = COLONY_ICONS[currentIconKey] || Component;

  const handlePickIcon = async (key: string) => {
    setIconPickerOpen(false);
    onIconChange(colony.id, key);
    await agentsApi.updateMetadata(colony.agentPath, { icon: key }).catch(() => {});
  };

  return (
    <aside className="w-[320px] min-w-[320px] max-w-[320px] flex-shrink-0 border-l border-border/60 bg-card overflow-y-auto overflow-x-hidden overscroll-contain">
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-3.5 border-b border-border/60">
        <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
          <Component className="w-4 h-4 text-primary" />
          Colony Details
        </div>
        <button onClick={onClose} className="p-1 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/60">
          <X className="w-4 h-4" />
        </button>
      </div>

      <div className="px-5 py-6">
        {/* Icon + Name */}
        <div className="mb-6 text-center">
          <div className="relative inline-block">
            <button
              onClick={() => setIconPickerOpen(!iconPickerOpen)}
              className="w-12 h-12 rounded-xl bg-primary/10 flex items-center justify-center mx-auto mb-3 hover:bg-primary/20 transition-colors"
              title="Change icon"
            >
              <CurrentIcon className="w-6 h-6 text-primary" />
            </button>
            {iconPickerOpen && (
              <div className="absolute top-14 left-1/2 -translate-x-1/2 bg-card border border-border/60 rounded-lg shadow-xl z-20 p-2 w-[200px]">
                <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider mb-2 px-1">Choose icon</p>
                <div className="grid grid-cols-4 gap-1">
                  {COLONY_ICON_KEYS.map((key) => {
                    const Icon = COLONY_ICONS[key];
                    return (
                      <button key={key} onClick={() => handlePickIcon(key)}
                        className={`w-10 h-10 rounded-lg flex items-center justify-center ${key === currentIconKey ? "bg-primary/15 text-primary" : "text-muted-foreground hover:bg-muted/50 hover:text-foreground"}`}>
                        <Icon className="w-4.5 h-4.5" />
                      </button>
                    );
                  })}
                </div>
              </div>
            )}
          </div>
          <h3 className="text-base font-semibold text-foreground">{colony.name}</h3>
          {queenName && <p className="text-xs text-muted-foreground mt-0.5">Managed by {queenName}</p>}
        </div>

        {/* Go to colony */}
        <button
          onClick={() => navigate(`/colony/${colony.id}`)}
          className="w-full flex items-center justify-center gap-2 rounded-lg bg-primary text-primary-foreground py-2.5 text-sm font-medium hover:bg-primary/90 mb-6"
        >
          Open Colony
          <ArrowRight className="w-4 h-4" />
        </button>

        {/* Metadata */}
        <div className="space-y-4">
          <div>
            <h4 className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider mb-1.5">Start Date</h4>
            <div className="flex items-center gap-2 text-sm text-foreground">
              <Calendar className="w-3.5 h-3.5 text-muted-foreground flex-shrink-0" />
              {formatDate(colony.createdAt)}
            </div>
          </div>

          <div>
            <h4 className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider mb-1.5">Project Goal</h4>
            <div className="flex items-start gap-2 text-sm text-foreground/80 min-w-0">
              <Target className="w-3.5 h-3.5 text-muted-foreground flex-shrink-0 mt-0.5" />
              <p className="leading-relaxed break-words min-w-0">{colony.task || colony.description || "No goal specified"}</p>
            </div>
          </div>

          <div>
            <h4 className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider mb-1.5">Current Status</h4>
            <div className="flex items-center gap-2 text-sm">
              <Activity className="w-3.5 h-3.5 text-muted-foreground flex-shrink-0" />
              {(() => {
                const liveness = byColony.get(colony.id);
                const s = deriveColonyStatus(colony.sessionId !== null, liveness);
                return (
                  <Tooltip label={describeColonyStatus(s, liveness)} atCursor>
                    <span className={`inline-flex items-center gap-1.5 ${STATUS_TEXT_CLASS[s]}`}>
                      <span className={`w-1.5 h-1.5 rounded-full ${STATUS_DOT_CLASS[s]}`} />
                      {STATUS_LABEL[s]}
                    </span>
                  </Tooltip>
                );
              })()}
            </div>
          </div>

          {colony.lastActive && (
            <div>
              <h4 className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider mb-1.5">Last Active</h4>
              <div className="flex items-center gap-2 text-sm text-foreground">
                <Clock className="w-3.5 h-3.5 text-muted-foreground flex-shrink-0" />
                {formatRelative(colony.lastActive) || formatDate(colony.lastActive)}
              </div>
            </div>
          )}

          <div>
            <h4 className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider mb-1.5">Stats</h4>
            <div className="grid grid-cols-2 gap-2">
              <div className="rounded-lg bg-muted/30 px-3 py-2 text-center">
                <p className="text-lg font-semibold text-foreground">{colony.sessionCount}</p>
                <p className="text-[10px] text-muted-foreground">Sessions</p>
              </div>
              <div className="rounded-lg bg-muted/30 px-3 py-2 text-center">
                <p className="text-lg font-semibold text-foreground">{colony.runCount}</p>
                <p className="text-[10px] text-muted-foreground">Runs</p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </aside>
  );
}

/* ── Queen avatar ────────────────────────────────────────────────────── */

function QueenAvatar({ queenId, name, size = "w-11 h-11" }: { queenId: string; name: string; size?: string }) {
  const { queenProfiles, queenAvatarVersion, queenHasAvatar } = useColony();
  const version = queenAvatarVersion(queenId);
  const [hasAvatar, setHasAvatar] = useState(() => queenHasAvatar(queenId));
  const url = apiUrl(`/queen/${queenId}/avatar?v=${version}`);
  // Re-sync the "has an avatar" guard whenever the version bumps (a fresh
  // upload just flipped the flag true) or the runtime confirms presence.
  useEffect(() => setHasAvatar(queenHasAvatar(queenId)), [version, queenId, queenHasAvatar]);
  const portrait = queenProfiles.find((q) => q.id === queenId)?.portrait;
  return (
    <div className={`${size} bg-primary/15 flex items-center justify-center overflow-hidden`} style={{ clipPath: HEX_CLIP }}>
      {hasAvatar ? (
        <img src={url} alt={name} className="w-full h-full object-cover" onError={() => setHasAvatar(false)} />
      ) : portrait ? (
        <QueenPortraitGlyph p={portrait} frame={false} className="w-full h-full" />
      ) : (
        <span className="text-sm font-bold text-primary">{name.charAt(0)}</span>
      )}
    </div>
  );
}

/* ── Queen card in the org grid ───────────────────────────────────────── */

function QueenCard({
  queen,
  colonies,
  selected,
  decommissioned,
  dragging,
  onCardMouseDown,
  onSelectColony,
}: {
  queen: QueenProfileSummary;
  colonies: Colony[];
  selected: boolean;
  decommissioned: boolean;
  dragging: boolean;
  onCardMouseDown: (e: React.MouseEvent) => void;
  onSelectColony: (colony: Colony) => void;
}) {
  return (
    <div className="flex flex-col items-center w-full">
      {/* Queen card — drag handle. Fixed height so all cards align. */}
      <div
        onMouseDown={onCardMouseDown}
        data-tour="tour-queen-card"
        title={decommissioned ? "Decommissioned" : "Drag to move · click to open"}
        className={`group flex flex-col items-center justify-center rounded-xl border bg-card p-4 w-full h-[8.125rem] text-center select-none ${
          dragging
            ? "cursor-grabbing shadow-xl ring-2 ring-primary/40"
            : "cursor-grab transition-all duration-200"
        } ${
          selected
            ? "border-primary/40 bg-primary/[0.04] ring-1 ring-primary/20"
            : "border-border/60 hover:border-primary/30 hover:bg-primary/[0.03]"
        } ${decommissioned ? "opacity-50 grayscale" : ""}`}
      >
        <div className="mb-2.5">
          <QueenAvatar queenId={queen.id} name={queen.name} />
        </div>
        <span className={`text-sm font-semibold transition-colors line-clamp-1 ${
          decommissioned
            ? "text-muted-foreground line-through"
            : "text-foreground group-hover:text-primary"
        }`}>
          {queen.name}
        </span>
        <span className="text-xs text-muted-foreground mt-0.5 line-clamp-1">
          {decommissioned ? "Decommissioned" : queen.title}
        </span>
      </div>

      {/* Colony connections — hidden for decommissioned queens since
          colonies don't list them either */}
      {!decommissioned && colonies.length > 0 && (
        <>
          <div className="w-px h-4 bg-border" />
          <div className="flex flex-col gap-1.5 w-full">
            {colonies.map((colony) => (
              <ColonyTag key={colony.id} colony={colony} onSelect={() => onSelectColony(colony)} />
            ))}
          </div>
        </>
      )}
    </div>
  );
}

/* ── Leader persona card (hireable from the catalog) ─────────────────── */

function PersonaCard({ persona, isCurrent, isSaving, onHire }: {
  persona: PersonaSummary;
  isCurrent: boolean;
  isSaving: boolean;
  onHire: () => void;
}) {
  return (
    <div
      className={`flex flex-col items-center w-[7.5rem] flex-shrink-0 rounded-xl border bg-card p-3 text-center ${
        isCurrent ? "border-primary/40 ring-1 ring-primary/20" : "border-border/60"
      }`}
      title={persona.bio}
    >
      <div className="w-11 h-11 bg-primary/15 flex items-center justify-center overflow-hidden mb-2" style={{ clipPath: HEX_CLIP }}>
        <QueenPortraitGlyph p={persona.portrait} frame={false} className="w-full h-full" />
      </div>
      <span className="text-xs font-semibold text-foreground line-clamp-1 w-full">
        {persona.name}
      </span>
      <span className="text-[10px] text-muted-foreground mt-0.5 line-clamp-1 w-full">
        {persona.title}
      </span>
      <button
        onClick={onHire}
        disabled={isCurrent || isSaving}
        className={`mt-2 w-full rounded-md border border-primary/30 px-2 py-1 text-[10px] font-medium transition-colors ${
          isCurrent
            ? "text-primary cursor-default opacity-80"
            : "text-primary hover:bg-primary/10 disabled:opacity-50"
        }`}
      >
        {isCurrent ? "Current lead" : isSaving ? "Hiring…" : "Hire"}
      </button>
    </div>
  );
}

/* ── One function's leaders, with inline decommission/re-enable ──────── */

function FunctionGroup({
  functionId,
  label,
  personas,
  currentLeaderId,
  decommissioned,
  hireSaving,
  onHire,
}: {
  functionId: string;
  /** Resolved from her profile title — see queenFunctionLabel. */
  label: string;
  personas: PersonaSummary[];
  currentLeaderId: string | null;
  decommissioned: boolean;
  hireSaving: boolean;
  onHire: (functionId: string, persona: PersonaSummary) => void;
}) {
  const { setDecommissioned, saving } = useQueenDecommission(functionId);
  return (
    <div className={decommissioned ? "opacity-60" : ""}>
      <div className="flex items-center gap-2 mb-2">
        <span className="text-[11px] font-semibold text-foreground/80">
          {label}
        </span>
        {decommissioned && (
          <>
            <span className="text-[9px] uppercase tracking-wider text-muted-foreground rounded bg-muted px-1.5 py-0.5">
              Decommissioned
            </span>
            <button
              onClick={() => void setDecommissioned(false)}
              disabled={saving}
              className="rounded-md border border-primary/30 px-2 py-0.5 text-[10px] font-medium text-primary transition-colors hover:bg-primary/10 disabled:opacity-50"
            >
              {saving ? "…" : "Re-enable"}
            </button>
          </>
        )}
      </div>
      <div className="flex flex-wrap gap-2">
        {personas.map((persona) => (
          <PersonaCard
            key={persona.id}
            persona={persona}
            isCurrent={currentLeaderId === persona.leaderId}
            isSaving={hireSaving}
            onHire={() => onHire(functionId, persona)}
          />
        ))}
      </div>
    </div>
  );
}

/* ── Custom queens (user-created, outside the preset catalog) ────────── */

function CustomQueenRow({ queen }: { queen: QueenProfileSummary }) {
  const navigate = useNavigate();
  const { isDecommissioned, setDecommissioned, saving } =
    useQueenDecommission(queen.id);
  return (
    <div className="flex items-center gap-3 rounded-lg border border-border/60 bg-background/60 px-3 py-2">
      <div className="min-w-0">
        <div className="text-xs font-semibold text-foreground truncate">
          {queen.name || queen.id}
        </div>
        <div className="text-[10px] text-muted-foreground truncate">
          {queen.title || queen.id}
        </div>
      </div>
      <div className="ml-auto flex items-center gap-2">
        {isDecommissioned ? (
          <>
            <span className="text-[9px] uppercase tracking-wider text-muted-foreground rounded bg-muted px-1.5 py-0.5">
              Decommissioned
            </span>
            <button
              onClick={() => void setDecommissioned(false)}
              disabled={saving}
              className="rounded-md border border-primary/30 px-2 py-0.5 text-[10px] font-medium text-primary transition-colors hover:bg-primary/10 disabled:opacity-50"
            >
              {saving ? "…" : "Re-enable"}
            </button>
          </>
        ) : (
          <button
            onClick={() => navigate(`/queen/${queen.id}`)}
            className="rounded-md border border-border/60 px-2 py-0.5 text-[10px] font-medium text-muted-foreground transition-colors hover:text-foreground hover:border-primary/30"
          >
            Open DM
          </button>
        )}
      </div>
    </div>
  );
}

function NewQueenDialog({ onClose }: { onClose: () => void }) {
  const { refresh } = useColony();
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [title, setTitle] = useState("");
  const [persona, setPersona] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const submit = async () => {
    if (!name.trim() || saving) return;
    setSaving(true);
    setError(null);
    try {
      const { queen } = await queensApi.createQueen({
        name: name.trim(),
        title: title.trim() || undefined,
        persona: persona.trim() || undefined,
      });
      // Active immediately — a queen created then hidden by the default
      // roster filter would look like the creation silently failed.
      activateQueen(queen.id);
      refresh();
      onClose();
      navigate(`/queen/${queen.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setSaving(false);
    }
  };
  const inputCls =
    "w-full mb-3 rounded-md border border-border/60 bg-background px-2.5 py-1.5 text-xs text-foreground outline-none focus:border-primary/50";
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      onMouseDown={onClose}
    >
      <div
        className="w-[26rem] max-w-[92vw] rounded-xl border border-border/60 bg-card p-5 shadow-xl"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="text-sm font-semibold text-foreground mb-3">
          New Queen
        </div>
        <label className="block text-[11px] text-muted-foreground mb-1">
          Name *
        </label>
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          autoFocus
          className={inputCls}
          placeholder="Display name"
        />
        <label className="block text-[11px] text-muted-foreground mb-1">
          Title
        </label>
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          className={inputCls}
          placeholder="Role / one-line intro"
        />
        <label className="block text-[11px] text-muted-foreground mb-1">
          Persona — free text, becomes her core traits
        </label>
        <textarea
          value={persona}
          onChange={(e) => setPersona(e.target.value)}
          rows={4}
          className={inputCls + " resize-y"}
          placeholder="Voice, temperament, duties…"
        />
        {error && (
          <div className="mb-3 text-[11px] text-red-500">{error}</div>
        )}
        <div className="flex justify-end gap-2">
          <button
            onClick={onClose}
            className="rounded-md border border-border/60 px-3 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:text-foreground"
          >
            Cancel
          </button>
          <button
            onClick={() => void submit()}
            disabled={!name.trim() || saving}
            className="rounded-md border border-primary/40 bg-primary/10 px-3 py-1.5 text-xs font-medium text-primary transition-colors hover:bg-primary/20 disabled:opacity-50"
          >
            {saving ? "Creating…" : "Create"}
          </button>
        </div>
      </div>
    </div>
  );
}

/* ── Leader catalog grouped by function ──────────────────────────────── */

function LeaderCatalog() {
  const { me } = useMe();
  const { refresh: refreshColony, queenProfiles } = useColony();
  const { setLead, savingQueenId } = useSetQueenLead();
  const [newQueenOpen, setNewQueenOpen] = useState(false);
  // User-created queens live outside the preset function slots.
  const customQueens = queenProfiles.filter((q) => q.custom);
  const personas = allPersonaSummaries(QUEEN_DISPLAY_ORDER);
  const groups: { functionId: string; personas: PersonaSummary[] }[] = [];
  for (const p of personas) {
    let group = groups[groups.length - 1];
    if (!group || group.functionId !== p.functionId) {
      group = { functionId: p.functionId, personas: [] };
      groups.push(group);
    }
    group.personas.push(p);
  }
  const handleHire = async (functionId: string, persona: PersonaSummary) => {
    await setLead(functionId, {
      leaderId: persona.leaderId,
      name: persona.name,
      title: persona.title,
      bio: persona.bio,
      portrait: persona.portrait,
    });
    // Re-pull /queen/profiles so the chart reflects the new lead's persona.
    refreshColony();
  };
  return (
    <div className="space-y-4">
      {groups.map((group) => {
        // Resolve the current lead: an explicit hire preference wins;
        // otherwise match the runtime queen's live name to a persona in this
        // group. Falling back to personas[0] is wrong — for a few functions
        // the catalog's first persona is NOT the runtime default (e.g.
        // product_strategy lists Chesky first but defaults to Jobs), which
        // would falsely disable a hireable card. null → nothing is marked
        // current, so every persona stays hireable.
        const currentName = queenProfiles.find(
          (q) => q.id === group.functionId,
        )?.name;
        const currentLeaderId =
          me?.preferences?.queens?.[group.functionId]?.id ??
          group.personas.find((p) => p.name === currentName)?.leaderId ??
          null;
        return (
          <FunctionGroup
            key={group.functionId}
            functionId={group.functionId}
            label={queenFunctionLabel(queenProfiles, group.functionId)}
            personas={group.personas}
            currentLeaderId={currentLeaderId}
            decommissioned={isQueenDecommissioned(me, group.functionId)}
            hireSaving={savingQueenId === group.functionId}
            onHire={handleHire}
          />
        );
      })}

      {/* Custom queens — user-created, no preset function slot */}
      <div>
        <div className="flex items-center gap-2 mb-2">
          <span className="text-[11px] font-semibold text-foreground/80">
            Custom
          </span>
          <button
            onClick={() => setNewQueenOpen(true)}
            className="rounded-md border border-primary/30 px-2 py-0.5 text-[10px] font-medium text-primary transition-colors hover:bg-primary/10"
          >
            + New Queen
          </button>
        </div>
        {customQueens.length > 0 ? (
          <div className="flex flex-col gap-2">
            {customQueens.map((q) => (
              <CustomQueenRow key={q.id} queen={q} />
            ))}
          </div>
        ) : (
          <div className="text-[11px] text-muted-foreground">
            No custom queens yet — create one from scratch.
          </div>
        )}
      </div>

      {newQueenOpen && <NewQueenDialog onClose={() => setNewQueenOpen(false)} />}
    </div>
  );
}

/* ── Main org chart page ──────────────────────────────────────────────── */

// Fixed left-to-right order for queen cards
export default function OrgChart() {
  const { queenProfiles: unsortedQueenProfiles, colonies, userProfile, userAvatarVersion, userHasAvatar } = useColony();
  const { me } = useMe();
  const setQueenPosition = useSetQueenPosition();
  const setQueenPositions = useSetQueenPositions();
  const resetQueenPositions = useResetQueenPositions();
  const orderedQueens = orderQueens(
    unsortedQueenProfiles,
    Object.keys(me?.preferences?.queens ?? {}),
  );
  // Decommissioned queens are hidden from the chart; they live behind the
  // "decommissioned" toggle in the header where they can be re-enabled.
  const queenProfiles = orderedQueens.filter(
    (q) => !isQueenDecommissioned(me, q.id),
  );
  const [selectedQueenId, setSelectedQueenId] = useState<string | null>(null);
  const [selectedColony, setSelectedColony] = useState<Colony | null>(null);
  const [showDecommissioned, setShowDecommissioned] = useState(false);

  // Pan & zoom state
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [dragging, setDragging] = useState(false);
  const dragStart = useRef({ x: 0, y: 0, panX: 0, panY: 0 });
  const MIN_ZOOM = 0.3;
  const MAX_ZOOM = 2;

  // Per-card drag state. `localPositions` holds optimistic positions for cards
  // moved this session (takes precedence over the saved/default position so
  // there's no flicker between drop and the /v1/me refetch). `cardDrag` tracks
  // the in-flight drag; `draggingId` drives cursor/elevation styling.
  const [localPositions, setLocalPositions] = useState<Record<string, { x: number; y: number }>>({});
  const [draggingId, setDraggingId] = useState<string | null>(null);
  const cardDrag = useRef<{
    id: string; startX: number; startY: number;
    origX: number; origY: number; lastX: number; lastY: number; moved: boolean;
  } | null>(null);

  // Effective on-canvas position per visible queen: optimistic > saved > default.
  const positions: Record<string, { x: number; y: number }> = {};
  queenProfiles.forEach((q, i) => {
    const saved = me?.preferences?.queens?.[q.id]?.pos;
    positions[q.id] =
      localPositions[q.id] ??
      (saved && typeof saved.x === "number" && typeof saved.y === "number"
        ? { x: saved.x, y: saved.y }
        : defaultQueenPos(i, queenProfiles.length));
  });

  // True when at least one card has been moved (this session or persisted) —
  // gates the reset control.
  const hasCustomPositions =
    Object.keys(localPositions).length > 0 ||
    queenProfiles.some((q) => me?.preferences?.queens?.[q.id]?.pos != null);

  // Positions captured at the moment of reset, so the button can offer "Undo"
  // to put them back. Cleared once the user moves a card again (a new layout).
  const [undoSnapshot, setUndoSnapshot] = useState<Record<string, { x: number; y: number }> | null>(null);

  const handleResetPositions = () => {
    const snapshot: Record<string, { x: number; y: number }> = {};
    for (const q of queenProfiles) {
      const saved = me?.preferences?.queens?.[q.id]?.pos;
      const hasCustom =
        localPositions[q.id] != null ||
        (saved && typeof saved.x === "number" && typeof saved.y === "number");
      if (hasCustom) snapshot[q.id] = positions[q.id];
    }
    setUndoSnapshot(Object.keys(snapshot).length > 0 ? snapshot : null);
    setLocalPositions({});
    void resetQueenPositions();
  };

  const handleUndoReset = () => {
    if (!undoSnapshot) return;
    setLocalPositions(undoSnapshot);
    void setQueenPositions(undoSnapshot);
    setUndoSnapshot(null);
  };

  const handleWheel = useCallback((e: React.WheelEvent) => {
    e.preventDefault();
    const delta = e.deltaY > 0 ? 0.93 : 1.07;
    setZoom((z) => Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, z * delta)));
  }, []);

  const startCardDrag = (e: React.MouseEvent, id: string, pos: { x: number; y: number }) => {
    if (e.button !== 0) return;
    e.stopPropagation(); // don't let the canvas start a pan
    e.preventDefault(); // suppress native image/text drag that steals the mouseup
    cardDrag.current = {
      id, startX: e.clientX, startY: e.clientY,
      origX: pos.x, origY: pos.y, lastX: pos.x, lastY: pos.y, moved: false,
    };
    setDraggingId(id);
  };

  const handleMouseDown = (e: React.MouseEvent) => {
    if (e.button !== 0) return;
    setDragging(true);
    dragStart.current = { x: e.clientX, y: e.clientY, panX: pan.x, panY: pan.y };
  };

  // Drag move/up live on `window` (not the canvas div) so a release is caught
  // even when the pointer is over a child that stops propagation or has left
  // the canvas — otherwise the card "glues" to the cursor after the button is
  // up. The latest-closure refs keep these in sync without re-subscribing every
  // render. The effect below attaches them only while a drag is in flight.
  const onDragMove = (e: MouseEvent) => {
    const cd = cardDrag.current;
    if (cd) {
      const dx = (e.clientX - cd.startX) / zoom;
      const dy = (e.clientY - cd.startY) / zoom;
      if (Math.abs(e.clientX - cd.startX) + Math.abs(e.clientY - cd.startY) > 4) cd.moved = true;
      const nx = clamp(cd.origX + dx, 8, CANVAS_W - CARD_W - 8);
      const ny = clamp(cd.origY + dy, CEO_Y + CEO_H + 16, CANVAS_H - CARD_H - 8);
      cd.lastX = nx;
      cd.lastY = ny;
      setLocalPositions((prev) => ({ ...prev, [cd.id]: { x: nx, y: ny } }));
      return;
    }
    if (!dragging) return;
    setPan({
      x: dragStart.current.panX + (e.clientX - dragStart.current.x),
      y: dragStart.current.panY + (e.clientY - dragStart.current.y),
    });
  };

  const onDragUp = () => {
    const cd = cardDrag.current;
    if (cd) {
      cardDrag.current = null;
      setDraggingId(null);
      if (cd.moved) {
        setUndoSnapshot(null); // a new layout supersedes the post-reset undo
        void setQueenPosition(cd.id, { x: cd.lastX, y: cd.lastY });
      } else {
        // No movement: treat as a click → toggle the queen's side panel.
        setSelectedColony(null);
        setSelectedQueenId((prev) => (prev === cd.id ? null : cd.id));
      }
      return;
    }
    setDragging(false);
  };

  const dragMoveRef = useRef(onDragMove);
  const dragUpRef = useRef(onDragUp);
  dragMoveRef.current = onDragMove;
  dragUpRef.current = onDragUp;

  useEffect(() => {
    if (!draggingId && !dragging) return;
    const move = (e: MouseEvent) => dragMoveRef.current(e);
    const up = () => dragUpRef.current();
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", up);
    return () => {
      window.removeEventListener("mousemove", move);
      window.removeEventListener("mouseup", up);
    };
  }, [draggingId, dragging]);

  // Group colonies by their queen profile ID
  const coloniesByQueen = new Map<string, Colony[]>();
  for (const colony of colonies) {
    if (colony.queenProfileId) {
      const list = coloniesByQueen.get(colony.queenProfileId) ?? [];
      list.push(colony);
      coloniesByQueen.set(colony.queenProfileId, list);
    }
  }

  const initials = userProfile.displayName
    .trim()
    .split(/\s+/)
    .map((w) => w[0])
    .join("")
    .toUpperCase()
    .slice(0, 2);

  const handleSelectColony = (colony: Colony) => {
    setSelectedQueenId(null);
    setSelectedColony(selectedColony?.id === colony.id ? null : colony);
  };

  // Resolve queen name for colony panel
  const colonyQueenName = selectedColony?.queenProfileId
    ? (queenProfiles.find((q) => q.id === selectedColony.queenProfileId)?.name ?? "")
    : "";

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      {/* Page header */}
      <div className="px-6 py-4 border-b border-border/60">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <h2 className="text-lg font-semibold text-foreground flex items-center gap-2">
              <Network className="w-5 h-5 text-primary" />
              Org Chart
            </h2>
            <span className="text-xs text-muted-foreground">
              {queenProfiles.length} queens &middot; {colonies.length} colonies
            </span>
          </div>
        </div>
      </div>

      <div className="flex-1 flex overflow-hidden">
      {/* Main chart area — pannable canvas */}
      <div
        className="flex-1 overflow-hidden relative"
        style={{ cursor: dragging ? "grabbing" : "grab", userSelect: "none" }}
        onWheel={handleWheel}
        onMouseDown={handleMouseDown}
      >
        {/* Pannable + zoomable content. The canvas is a fixed coordinate
            space, centered in the viewport (left:50% + translateX(-50%)); cards
            are positioned absolutely within it from saved/default positions. */}
        <div
          style={{
            position: "absolute",
            left: "50%",
            top: 0,
            transform: `translate(calc(-50% + ${pan.x}px), ${pan.y}px) scale(${zoom})`,
            transformOrigin: "center top",
            transition: dragging || draggingId ? "none" : "transform 100ms ease-out",
          }}
        >
          <div className="relative" style={{ width: CANVAS_W, height: CANVAS_H }}>
            {/* Connector lines: CEO → each queen card. Recomputed from live
                positions so they follow drags. */}
            <svg
              className="absolute left-0 top-0 pointer-events-none text-border"
              width={CANVAS_W}
              height={CANVAS_H}
            >
              {queenProfiles.map((queen) => {
                const p = positions[queen.id];
                // Orthogonal "elbow" routing like a classic org chart: drop
                // straight down from the CEO, run horizontally, then drop into
                // the queen card's top — right angles instead of a diagonal.
                const sx = CENTER_X;
                const sy = CEO_Y + CEO_H;
                const ex = p.x + CARD_W / 2;
                const ey = p.y;
                const midY = sy + (ey - sy) / 2;
                return (
                  <path
                    key={queen.id}
                    d={`M ${sx} ${sy} V ${midY} H ${ex} V ${ey}`}
                    fill="none"
                    stroke="currentColor"
                    strokeWidth={1}
                  />
                );
              })}
            </svg>

            {/* CEO card — fixed (it's the user); dragging it pans the canvas. */}
            <div
              className="absolute rounded-xl border border-border/60 bg-card px-8 py-5 text-center"
              style={{ left: CEO_X, top: CEO_Y, width: CEO_W }}
            >
              <UserAvatar initials={initials} avatarVersion={userAvatarVersion} userHasAvatar={userHasAvatar} />
              <div className="font-semibold text-sm text-foreground">
                {userProfile.displayName || "You"}
              </div>
              <div className="text-xs text-muted-foreground mt-0.5">
                CEO / Founder
              </div>
            </div>

            {/* Queens — freely positioned, draggable */}
            {queenProfiles.map((queen) => {
              const p = positions[queen.id];
              return (
                <div
                  key={queen.id}
                  className="absolute"
                  style={{ left: p.x, top: p.y, width: CARD_W, zIndex: draggingId === queen.id ? 10 : 1 }}
                >
                  <QueenCard
                    queen={queen}
                    colonies={coloniesByQueen.get(queen.id) ?? []}
                    selected={selectedQueenId === queen.id}
                    decommissioned={isQueenDecommissioned(me, queen.id)}
                    dragging={draggingId === queen.id}
                    onCardMouseDown={(e) => startCardDrag(e, queen.id, p)}
                    onSelectColony={handleSelectColony}
                  />
                </div>
              );
            })}
          </div>
        </div>

        {/* Floating leader-catalog control, bottom-right of the canvas */}
        <div
          className="absolute bottom-4 right-4 z-20 flex flex-col items-end gap-2"
          onMouseDown={(e) => e.stopPropagation()}
          onWheel={(e) => e.stopPropagation()}
          style={{ cursor: "default" }}
        >
          {showDecommissioned && (
            <div className="w-[66rem] max-w-[90vw] max-h-[60vh] overflow-y-auto rounded-xl border border-border/60 bg-card shadow-xl p-4">
              <div className="text-[11px] uppercase tracking-wider text-muted-foreground mb-3">
                Leader catalog &middot; hire a lead for any function, or re-enable a decommissioned one
              </div>
              <LeaderCatalog />
            </div>
          )}
          <div className="flex items-center gap-2">
            <button
              onClick={undoSnapshot ? handleUndoReset : handleResetPositions}
              disabled={!undoSnapshot && !hasCustomPositions}
              title={undoSnapshot ? "Undo the reset and restore positions" : "Reset queen positions to the default layout"}
              className="w-32 text-center px-3 py-1.5 rounded-lg border border-border/60 bg-card text-xs font-medium text-muted-foreground shadow-md hover:text-foreground hover:border-primary/30 transition-colors disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:text-muted-foreground disabled:hover:border-border/60"
            >
              {undoSnapshot ? "Undo" : "Reset"}
            </button>
            <button
              onClick={() => setShowDecommissioned((v) => !v)}
              className="w-32 text-center px-3 py-1.5 rounded-lg border border-border/60 bg-card text-xs font-medium text-muted-foreground shadow-md hover:text-foreground hover:border-primary/30 transition-colors"
            >
              Leader Catalog
            </button>
          </div>
        </div>
      </div>

      {/* Queen profile side panel */}
      {selectedQueenId && (
        <QueenProfilePanel
          queenId={selectedQueenId}
          colonies={coloniesByQueen.get(selectedQueenId) ?? []}
          onClose={() => setSelectedQueenId(null)}
        />
      )}

      {/* Colony detail side panel */}
      {selectedColony && (
        <ColonyDetailPanel
          colony={selectedColony}
          queenName={colonyQueenName}
          onClose={() => setSelectedColony(null)}
          onIconChange={(colonyId, icon) => {
            setSelectedColony((prev) => prev && prev.id === colonyId ? { ...prev, icon } : prev);
          }}
        />
      )}
      </div>
    </div>
  );
}
