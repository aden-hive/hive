import { useState, useEffect, useCallback, useRef } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { X, MessageSquare, Crown, ChevronRight, Briefcase, Award, Pencil, Check, Loader2, Camera, Plus } from "lucide-react";
import { useColony } from "@/context/ColonyContext";
import { queensApi, type QueenProfile } from "@/api/queens";
import { executionApi } from "@/api/execution";
import { compressImage } from "@/lib/image-utils";
import type { Colony } from "@/types/colony";
import { slugToColonyId } from "@/lib/colony-registry";

interface QueenProfilePanelProps {
  queenId: string;
  colonies: Colony[];
  onClose: () => void;
}

function SectionHeader({ children, onEdit }: { children: React.ReactNode; onEdit?: () => void }) {
  return (
    <div className="flex items-center justify-between mb-2">
      <h4 className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">{children}</h4>
      {onEdit && (
        <button onClick={onEdit} className="p-0.5 rounded text-muted-foreground/40 hover:text-foreground" title="Edit">
          <Pencil className="w-3 h-3" />
        </button>
      )}
    </div>
  );
}

export default function QueenProfilePanel({ queenId, colonies, onClose }: QueenProfilePanelProps) {
  const navigate = useNavigate();
  const location = useLocation();
  const { queenProfiles, refresh } = useColony();
  const summary = queenProfiles.find((q) => q.id === queenId);
  const [profile, setProfile] = useState<QueenProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);

  // Avatar state
  const [avatarUrl, setAvatarUrl] = useState<string | null>(null);
  const [uploadingAvatar, setUploadingAvatar] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Edit form state
  const [editName, setEditName] = useState("");
  const [editTitle, setEditTitle] = useState("");
  const [editSummary, setEditSummary] = useState("");
  const [editSkills, setEditSkills] = useState("");
  const [editAchievement, setEditAchievement] = useState("");

  const alreadyInQueenPm = location.pathname === `/queen/${queenId}`;

  useEffect(() => {
    setLoading(true);
    setProfile(null);
    setEditing(false);
    // Set avatar URL with cache buster
    setAvatarUrl(`/api/queen/${queenId}/avatar?t=${Date.now()}`);
    queensApi.getProfile(queenId).then(setProfile).catch(() => {}).finally(() => setLoading(false));
  }, [queenId]);

  const startEditing = () => {
    if (!profile) return;
    setEditName(profile.name);
    setEditTitle(profile.title);
    setEditSummary(profile.summary || "");
    setEditSkills(profile.skills || "");
    setEditAchievement(profile.signature_achievement || "");
    setEditing(true);
  };

  const cancelEditing = () => setEditing(false);

  const handleSave = async () => {
    setSaving(true);
    try {
      const updated = await queensApi.updateProfile(queenId, {
        name: editName.trim(),
        title: editTitle.trim(),
        summary: editSummary.trim(),
        skills: editSkills.trim(),
        signature_achievement: editAchievement.trim(),
      });
      setProfile(updated);
      setEditing(false);
      refresh();
    } catch (err) {
      console.error("Failed to save profile:", err);
    } finally {
      setSaving(false);
    }
  };

  const handleAvatarClick = () => fileInputRef.current?.click();

  const handleAvatarUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    // Reset input so same file can be re-selected
    e.target.value = "";

    if (!file.type.startsWith("image/")) return;

    setUploadingAvatar(true);
    try {
      const compressed = await compressImage(file);
      await queensApi.uploadAvatar(queenId, compressed);
      setAvatarUrl(`/api/queen/${queenId}/avatar?t=${Date.now()}`);
    } catch (err) {
      console.error("Failed to upload avatar:", err);
    } finally {
      setUploadingAvatar(false);
    }
  };

  // Colony creation
  const [colonyDialogOpen, setColonyDialogOpen] = useState(false);
  const [colonyName, setColonyName] = useState("");
  const [colonyTask, setColonyTask] = useState("");
  const [creatingColony, setCreatingColony] = useState(false);

  const handleCreateColony = async () => {
    const cname = colonyName.trim();
    if (!cname || creatingColony) return;
    setCreatingColony(true);
    try {
      // Create a fresh queen session, then fork it into a colony
      const { session_id } = await queensApi.createNewSession(queenId, colonyTask.trim() || undefined);
      await executionApi.colonySpawn(session_id, cname, colonyTask.trim() || undefined);
      setColonyDialogOpen(false);
      setColonyName("");
      setColonyTask("");
      refresh();
      onClose();
      navigate(`/colony/${slugToColonyId(cname)}`);
    } catch (err) {
      console.error("Failed to create colony:", err);
    } finally {
      setCreatingColony(false);
    }
  };

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

  const inputCls = "w-full bg-muted/30 border border-border/50 rounded-lg px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-primary/40";
  const textareaCls = `${inputCls} resize-none`;

  const avatarElement = (
    <div className="relative group">
      <div className="w-16 h-16 rounded-full bg-primary/15 flex items-center justify-center overflow-hidden">
        {avatarUrl ? (
          <img
            src={avatarUrl}
            alt={name}
            className="w-full h-full object-cover"
            onError={() => setAvatarUrl(null)}
          />
        ) : (
          <span className="text-xl font-bold text-primary">{name.charAt(0)}</span>
        )}
      </div>
      <button
        onClick={handleAvatarClick}
        disabled={uploadingAvatar}
        className="absolute inset-0 w-16 h-16 rounded-full flex items-center justify-center bg-black/50 opacity-0 group-hover:opacity-100 cursor-pointer"
        title="Change photo"
      >
        {uploadingAvatar ? (
          <Loader2 className="w-4 h-4 text-white animate-spin" />
        ) : (
          <Camera className="w-4 h-4 text-white" />
        )}
      </button>
      <input ref={fileInputRef} type="file" accept="image/*" className="hidden" onChange={handleAvatarUpload} />
    </div>
  );

  return (
    <aside
      className="flex-shrink-0 border-l border-border/60 bg-card overflow-y-auto overscroll-contain relative"
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
        <button onClick={onClose} className="p-1 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/60">
          <X className="w-4 h-4" />
        </button>
      </div>

      <div className="px-5 py-6">
        {loading ? (
          <div className="flex justify-center py-10">
            <div className="w-6 h-6 border-2 border-primary/30 border-t-primary rounded-full animate-spin" />
          </div>
        ) : editing ? (
          /* ── Edit Mode ──────────────────────────────────────────── */
          <div className="flex flex-col gap-5">
            {/* Avatar */}
            <div className="flex justify-center mb-1">
              {avatarElement}
            </div>

            <div>
              <label className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider mb-1.5 block">Name</label>
              <input type="text" value={editName} onChange={(e) => setEditName(e.target.value)} className={inputCls} />
            </div>

            <div>
              <label className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider mb-1.5 block">Title</label>
              <input type="text" value={editTitle} onChange={(e) => setEditTitle(e.target.value)} className={inputCls} />
            </div>

            <div>
              <label className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider mb-1.5 block">About</label>
              <textarea value={editSummary} onChange={(e) => setEditSummary(e.target.value)} rows={10} className={textareaCls} />
            </div>

            <div>
              <label className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider mb-1.5 block">Skills (comma-separated)</label>
              <textarea value={editSkills} onChange={(e) => setEditSkills(e.target.value)} rows={3} className={textareaCls} />
            </div>

            <div>
              <label className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider mb-1.5 block">Signature Achievement</label>
              <textarea value={editAchievement} onChange={(e) => setEditAchievement(e.target.value)} rows={5} className={textareaCls} />
            </div>

            <div className="flex items-center gap-2 pt-1">
              <button onClick={handleSave} disabled={saving || !editName.trim() || !editTitle.trim()}
                className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed">
                {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Check className="w-3.5 h-3.5" />}
                {saving ? "Saving..." : "Save"}
              </button>
              <button onClick={cancelEditing} disabled={saving}
                className="px-4 py-2 rounded-lg text-sm font-medium text-muted-foreground hover:text-foreground hover:bg-muted/30">
                Cancel
              </button>
            </div>
          </div>
        ) : (
          /* ── View Mode ──────────────────────────────────────────── */
          <>
            {/* Avatar + name + title */}
            <div className="flex flex-col items-center text-center mb-6 group relative">
              <div className="mb-3">
                {avatarElement}
              </div>
              <h3 className="text-base font-semibold text-foreground">{name}</h3>
              <p className="text-xs text-muted-foreground mt-0.5">{title}</p>
              <button onClick={startEditing}
                className="absolute top-0 right-0 p-1 rounded text-muted-foreground/40 hover:text-foreground opacity-0 group-hover:opacity-100" title="Edit name & title">
                <Pencil className="w-3 h-3" />
              </button>
            </div>

            <div className="flex items-center gap-2 mb-6">
              <button onClick={() => { navigate(`/queen/${queenId}`); onClose(); }}
                className="flex-1 flex items-center justify-center gap-2 rounded-lg border border-border/60 py-2.5 text-sm font-medium text-foreground hover:bg-muted/40">
                <MessageSquare className="w-4 h-4" />
                Message
              </button>
              <button onClick={() => setColonyDialogOpen(true)}
                className="flex-1 flex items-center justify-center gap-2 rounded-lg border border-primary/30 bg-primary/[0.04] py-2.5 text-sm font-medium text-primary hover:bg-primary/[0.08]">
                <Plus className="w-4 h-4" />
                Create Colony
              </button>
            </div>

            {profile?.summary && (
              <div className="mb-6">
                <SectionHeader onEdit={startEditing}>About</SectionHeader>
                <p className="text-sm text-foreground/80 leading-relaxed">{profile.summary}</p>
              </div>
            )}

            {profile?.experience && profile.experience.length > 0 && (
              <div className="mb-6">
                <SectionHeader onEdit={startEditing}>Experience</SectionHeader>
                <div className="space-y-3">
                  {profile.experience.map((exp, i) => (
                    <div key={i} className="flex items-start gap-2">
                      <Briefcase className="w-3.5 h-3.5 text-muted-foreground mt-0.5 flex-shrink-0" />
                      <div>
                        <p className="text-sm font-medium text-foreground">{exp.role}</p>
                        <ul className="mt-1 space-y-0.5">
                          {exp.details.map((d, j) => <li key={j} className="text-xs text-muted-foreground">{d}</li>)}
                        </ul>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {profile?.skills && (
              <div className="mb-6">
                <SectionHeader onEdit={startEditing}>Skills</SectionHeader>
                <div className="flex flex-wrap gap-1.5">
                  {profile.skills.split(",").map((skill, i) => (
                    <span key={i} className="px-2 py-0.5 rounded-full bg-muted/60 text-xs text-muted-foreground">{skill.trim()}</span>
                  ))}
                </div>
              </div>
            )}

            {profile?.signature_achievement && (
              <div className="mb-6">
                <SectionHeader onEdit={startEditing}>Signature Achievement</SectionHeader>
                <div className="flex items-start gap-2">
                  <Award className="w-3.5 h-3.5 text-primary mt-0.5 flex-shrink-0" />
                  <p className="text-sm text-foreground/80">{profile.signature_achievement}</p>
                </div>
              </div>
            )}

            {colonies.length > 0 && (
              <div>
                <h4 className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider mb-2">Assigned Colonies</h4>
                <div className="flex flex-col gap-1.5">
                  {colonies.map((colony) => (
                    <NavLink key={colony.id} to={`/colony/${colony.id}`} onClick={onClose}
                      className="flex items-center justify-between rounded-lg border border-primary/20 bg-primary/[0.04] px-3 py-2 text-sm text-primary hover:bg-primary/[0.08]">
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

      {/* Create Colony dialog */}
      {colonyDialogOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div className="absolute inset-0 bg-black/40" onClick={() => !creatingColony && setColonyDialogOpen(false)} />
          <div className="relative bg-card border border-border/60 rounded-xl shadow-2xl w-full max-w-md p-6 space-y-4">
            <h2 className="text-sm font-semibold text-foreground">Create Colony</h2>
            <p className="text-[11px] text-muted-foreground">
              Create a new colony managed by {name}. The queen will bootstrap it with tools and context.
            </p>
            <div className="space-y-3">
              <div>
                <label className="block text-[11px] font-medium text-muted-foreground mb-1">Colony name <span className="text-primary">*</span></label>
                <input type="text" value={colonyName} autoFocus
                  onChange={(e) => setColonyName(e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, ""))}
                  placeholder="e.g. research_team"
                  className="w-full rounded-md border border-border/60 bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-primary" />
              </div>
              <div>
                <label className="block text-[11px] font-medium text-muted-foreground mb-1">Task <span className="text-muted-foreground/40">(optional)</span></label>
                <input type="text" value={colonyTask} onChange={(e) => setColonyTask(e.target.value)}
                  placeholder="Describe what this colony should work on"
                  className="w-full rounded-md border border-border/60 bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-primary" />
              </div>
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <button onClick={() => { setColonyDialogOpen(false); setColonyName(""); setColonyTask(""); }} disabled={creatingColony}
                className="px-3 py-1.5 rounded-md text-xs font-medium text-muted-foreground hover:text-foreground hover:bg-muted/50">
                Cancel
              </button>
              <button onClick={handleCreateColony} disabled={creatingColony || !colonyName.trim()}
                className="px-3 py-1.5 rounded-md text-xs font-medium bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50">
                {creatingColony ? "Creating..." : "Create"}
              </button>
            </div>
          </div>
        </div>
      )}
    </aside>
  );
}
