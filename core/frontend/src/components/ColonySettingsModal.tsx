import { useEffect, useMemo, useState } from "react";
import { X, Crown, Component } from "lucide-react";
import { apiUrl } from "@/api/client";
import { useColony } from "@/context/ColonyContext";
import { agentSlug } from "@/lib/colony-registry";
import type { Colony } from "@/types/colony";
import QueenPortraitGlyph from "./QueenPortraitGlyph";

interface ColonySettingsModalProps {
  colony: Colony;
  onClose: () => void;
}

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

function formatRelative(iso: string | null): string | null {
  if (!iso) return null;
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return null;
  const diff = Date.now() - t;
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  if (days < 30) return `${days}d ago`;
  const months = Math.floor(days / 30);
  if (months < 12) return `${months}mo ago`;
  return `${Math.floor(months / 12)}y ago`;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const kb = bytes / 1024;
  if (kb < 1024) return `${kb.toFixed(kb < 10 ? 1 : 0)} KB`;
  const mb = kb / 1024;
  if (mb < 1024) return `${mb.toFixed(mb < 10 ? 1 : 0)} MB`;
  return `${(mb / 1024).toFixed(2)} GB`;
}

const STATUS_STYLES: Record<Colony["status"], { dot: string; label: string }> = {
  active: { dot: "bg-emerald-500", label: "Active" },
  idle: { dot: "bg-muted-foreground/40", label: "Idle" },
  parked: { dot: "bg-amber-500", label: "Parked" },
};

function SectionHeader({ children }: { children: React.ReactNode }) {
  return (
    <h4 className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider mb-2">
      {children}
    </h4>
  );
}

function DetailRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4 px-3 py-2.5">
      <span className="text-sm text-muted-foreground">{label}</span>
      <span className="text-sm text-foreground text-right truncate">{value}</span>
    </div>
  );
}

export default function ColonySettingsModal({ colony, onClose }: ColonySettingsModalProps) {
  const { queenProfiles, queenAvatarVersion, queenHasAvatar } = useColony();

  const queen = useMemo(
    () => queenProfiles.find((q) => q.id === colony.queenProfileId) ?? null,
    [queenProfiles, colony.queenProfileId],
  );

  const slug = useMemo(() => agentSlug(colony.agentPath), [colony.agentPath]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const status = STATUS_STYLES[colony.status];
  const goal = (colony.description || colony.task || "").trim();

  const [queenAvatarOk, setQueenAvatarOk] = useState(() =>
    queen ? queenHasAvatar(queen.id) : false,
  );
  const queenVersion = queen ? queenAvatarVersion(queen.id) : 0;
  useEffect(() => {
    setQueenAvatarOk(queen ? queenHasAvatar(queen.id) : false);
  }, [queen, queenVersion, queenHasAvatar]);

  const queenAvatar = queen ? (
    <span className="w-full h-full rounded-full overflow-hidden flex items-center justify-center bg-primary/15">
      {queenAvatarOk ? (
        <img
          src={apiUrl(`/queen/${queen.id}/avatar?v=${queenVersion}`)}
          alt={queen.name}
          className="w-full h-full object-cover"
          onError={() => setQueenAvatarOk(false)}
        />
      ) : queen.portrait ? (
        <QueenPortraitGlyph p={queen.portrait} className="w-full h-full" />
      ) : (
        <span className="text-[11px] font-bold text-primary">{queen.name.charAt(0)}</span>
      )}
    </span>
  ) : (
    <span className="w-full h-full rounded-full flex items-center justify-center bg-primary/15">
      <Crown className="w-4 h-4 text-primary" />
    </span>
  );

  const createdRel = formatRelative(colony.createdAt);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/40" onClick={onClose} />
      <div className="relative bg-card border border-border/60 rounded-xl shadow-2xl w-full max-w-md flex flex-col max-h-[88vh]">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3.5 border-b border-border/60 flex-shrink-0">
          <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
            <Component className="w-4 h-4 text-primary" />
            COLONY SETTINGS
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/60 transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 min-h-0 overflow-y-auto overscroll-contain px-5 py-6">
          {/* Identity */}
          <div className="flex flex-col items-center text-center mb-6">
            <h3 className="text-base font-semibold text-foreground">{colony.name}</h3>
            <div className="flex items-center gap-1.5 mt-1.5">
              <span className={`w-1.5 h-1.5 rounded-full ${status.dot}`} />
              <span className="text-xs text-muted-foreground">{status.label}</span>
            </div>
          </div>

          {/* Goal */}
          <div className="mb-6">
            <SectionHeader>Goal</SectionHeader>
            <p className="text-sm text-foreground/80 leading-relaxed">
              {goal || <span className="text-muted-foreground/50 italic">No goal recorded.</span>}
            </p>
          </div>

          {/* Queen bee in charge */}
          <div className="mb-6">
            <SectionHeader>Queen bee in charge</SectionHeader>
            <div className="flex items-center gap-3 rounded-lg border border-primary/20 bg-primary/[0.04] px-3 py-2.5">
              <span className="relative w-9 h-9 flex-shrink-0">{queenAvatar}</span>
              <div className="min-w-0">
                <p className="text-sm font-medium text-foreground truncate">
                  {queen?.name ?? colony.queenName ?? "Unassigned"}
                </p>
                <p className="text-xs text-muted-foreground truncate">{queen?.title ?? "Queen bee"}</p>
              </div>
              <Crown className="w-4 h-4 text-primary/60 ml-auto flex-shrink-0" />
            </div>
          </div>

          {/* Details */}
          <div>
            <SectionHeader>Details</SectionHeader>
            <div className="rounded-lg border border-border/60 divide-y divide-border/60">
              <DetailRow
                label="Created"
                value={createdRel ? `${formatDate(colony.createdAt)} · ${createdRel}` : formatDate(colony.createdAt)}
              />
              <DetailRow label="Last active" value={formatRelative(colony.lastActive) ?? "—"} />
              <DetailRow label="Sessions" value={colony.sessionCount.toLocaleString()} />
              <DetailRow label="Runs" value={colony.runCount.toLocaleString()} />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
