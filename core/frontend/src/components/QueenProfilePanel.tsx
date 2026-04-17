import { useState, useEffect, useCallback, useRef } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import {
  X,
  MessageSquare,
  Crown,
  ChevronRight,
  Briefcase,
  Award,
} from "lucide-react";
import { useColony } from "@/context/ColonyContext";
import { queensApi, type QueenProfile } from "@/api/queens";
import type { Colony } from "@/types/colony";

interface QueenProfilePanelProps {
  queenId: string;
  colonies: Colony[];
  onClose: () => void;
}

export default function QueenProfilePanel({
  queenId,
  colonies,
  onClose,
}: QueenProfilePanelProps) {
  const navigate = useNavigate();
  const location = useLocation();
  const { queenProfiles } = useColony();
  const summary = queenProfiles.find((q) => q.id === queenId);
  const [profile, setProfile] = useState<QueenProfile | null>(null);
  const [loading, setLoading] = useState(true);

  // Hide the "Message {name}" button when we're already in this queen's PM.
  const alreadyInQueenPm = location.pathname === `/queen/${queenId}`;

  useEffect(() => {
    setLoading(true);
    setProfile(null);
    queensApi
      .getProfile(queenId)
      .then(setProfile)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [queenId]);

  const name = profile?.name ?? summary?.name ?? "Queen";
  const title = profile?.title ?? summary?.title ?? "";

  // ── Resizable width ──────────────────────────────────────────────────
  const MIN_WIDTH = 280;
  const MAX_WIDTH = 600;
  const [width, setWidth] = useState(340);
  const dragging = useRef(false);
  const startX = useRef(0);
  const startWidth = useRef(0);

  const onDragStart = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    dragging.current = true;
    startX.current = e.clientX;
    startWidth.current = width;

    const onMove = (ev: MouseEvent) => {
      if (!dragging.current) return;
      // Panel is on the right, so dragging left (negative delta) grows it
      const delta = startX.current - ev.clientX;
      setWidth(Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, startWidth.current + delta)));
    };
    const onUp = () => {
      dragging.current = false;
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
  }, [width]);

  return (
    <aside
      className="flex-shrink-0 border-l border-border/60 bg-card overflow-y-auto relative"
      style={{ width }}
    >
      {/* Drag handle */}
      <div
        onMouseDown={onDragStart}
        className="absolute top-0 left-0 w-1 h-full cursor-col-resize hover:bg-primary/30 active:bg-primary/50 transition-colors z-10"
      />
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-3.5 border-b border-border/60">
        <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
          <Crown className="w-4 h-4 text-primary" />
          QUEEN PROFILE
        </div>
        <button
          onClick={onClose}
          className="p-1 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/60 transition-colors"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      <div className="px-5 py-6">
        {loading ? (
          <div className="flex justify-center py-10">
            <div className="w-6 h-6 border-2 border-primary/30 border-t-primary rounded-full animate-spin" />
          </div>
        ) : (
          <>
            {/* Avatar + name + title */}
            <div className="flex flex-col items-center text-center mb-6">
              <div className="w-16 h-16 rounded-full bg-primary/15 flex items-center justify-center mb-3">
                <span className="text-xl font-bold text-primary">
                  {name.charAt(0)}
                </span>
              </div>
              <h3 className="text-base font-semibold text-foreground">
                {name}
              </h3>
              <p className="text-xs text-muted-foreground mt-0.5">{title}</p>
            </div>

            {/* Message button — hidden when already in this queen's PM */}
            {!alreadyInQueenPm && (
              <button
                onClick={() => {
                  navigate(`/queen/${queenId}`);
                  onClose();
                }}
                className="w-full flex items-center justify-center gap-2 rounded-lg border border-border/60 py-2.5 text-sm font-medium text-foreground hover:bg-muted/40 transition-colors mb-6"
              >
                <MessageSquare className="w-4 h-4" />
                Message {name}
              </button>
            )}

            {/* About */}
            {profile?.summary && (
              <div className="mb-6">
                <h4 className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider mb-2">
                  About
                </h4>
                <p className="text-sm text-foreground/80 leading-relaxed">
                  {profile.summary}
                </p>
              </div>
            )}

            {/* Experience */}
            {profile?.experience && profile.experience.length > 0 && (
              <div className="mb-6">
                <h4 className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider mb-2">
                  Experience
                </h4>
                <div className="space-y-3">
                  {profile.experience.map((exp, i) => (
                    <div key={i} className="flex items-start gap-2">
                      <Briefcase className="w-3.5 h-3.5 text-muted-foreground mt-0.5 flex-shrink-0" />
                      <div>
                        <p className="text-sm font-medium text-foreground">
                          {exp.role}
                        </p>
                        <ul className="mt-1 space-y-0.5">
                          {exp.details.map((d, j) => (
                            <li
                              key={j}
                              className="text-xs text-muted-foreground"
                            >
                              {d}
                            </li>
                          ))}
                        </ul>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Skills */}
            {profile?.skills && (
              <div className="mb-6">
                <h4 className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider mb-2">
                  Skills
                </h4>
                <div className="flex flex-wrap gap-1.5">
                  {profile.skills.split(",").map((skill, i) => (
                    <span
                      key={i}
                      className="px-2 py-0.5 rounded-full bg-muted/60 text-xs text-muted-foreground"
                    >
                      {skill.trim()}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {/* Signature achievement */}
            {profile?.signature_achievement && (
              <div className="mb-6">
                <h4 className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider mb-2">
                  Signature Achievement
                </h4>
                <div className="flex items-start gap-2">
                  <Award className="w-3.5 h-3.5 text-primary mt-0.5 flex-shrink-0" />
                  <p className="text-sm text-foreground/80">
                    {profile.signature_achievement}
                  </p>
                </div>
              </div>
            )}

            {/* Assigned colonies */}
            {colonies.length > 0 && (
              <div>
                <h4 className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider mb-2">
                  Assigned Colonies
                </h4>
                <div className="flex flex-col gap-1.5">
                  {colonies.map((colony) => (
                    <NavLink
                      key={colony.id}
                      to={`/colony/${colony.id}`}
                      onClick={onClose}
                      className="flex items-center justify-between rounded-lg border border-primary/20 bg-primary/[0.04] px-3 py-2 text-sm text-primary hover:bg-primary/[0.08] transition-colors"
                    >
                      <span className="font-medium">#{colony.id}</span>
                      <ChevronRight className="w-3.5 h-3.5" />
                    </NavLink>
                  ))}
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </aside>
  );
}
