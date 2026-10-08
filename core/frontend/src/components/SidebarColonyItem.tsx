import { useState, useRef, useEffect } from "react";
import { NavLink, useNavigate, useLocation } from "react-router-dom";
import {
  AlertTriangle,
  Cloud,
  Loader2,
  MoreHorizontal,
  Pencil,
  Trash2,
} from "lucide-react";
import type { Colony } from "@/types/colony";
import type { QueenLiveness } from "@/hooks/use-live-sessions";
import { useColony } from "@/context/ColonyContext";
import { agentSlug, slugToColonyId } from "@/lib/colony-registry";
import { coloniesApi } from "@/api/colonies";
import { deriveColonyStatus, describeColonyStatus, STATUS_DOT_CLASS } from "@/lib/colony-status";
import { Tooltip } from "@/components/Tooltip";

interface SidebarColonyItemProps {
  colony: Colony;
  /** Live snapshot for this colony, aggregated across any of its
   * active sessions. Set by the sidebar from useLiveSessions. */
  liveness?: QueenLiveness;
}

export default function SidebarColonyItem({ colony, liveness }: SidebarColonyItemProps) {
  const { deleteColony, refresh } = useColony();
  const navigate = useNavigate();
  const location = useLocation();
  const [menuOpen, setMenuOpen] = useState(false);
  const [showDeleteModal, setShowDeleteModal] = useState(false);
  // When checked, the colony's tracked data is permanently removed from
  // disk. Unchecked (default) is a soft delete that just hides the colony.
  const [purgeData, setPurgeData] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  // Rename state. Inline edit replaces the colony name with an <input>
  // until the user confirms or cancels. Mirrors the create-colony slug
  // filter — spaces collapse to underscores, anything else gets stripped.
  const [renaming, setRenaming] = useState(false);
  const [renameValue, setRenameValue] = useState("");
  const [renameSaving, setRenameSaving] = useState(false);
  const [renameError, setRenameError] = useState<string | null>(null);
  const renameInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (renaming) renameInputRef.current?.focus();
  }, [renaming]);

  const diskName = agentSlug(colony.agentPath);
  // "Pushed to workspace" was a cloud feature (removed) — always local now.
  const onWorkspace = false;

  // Close menu on outside click
  useEffect(() => {
    if (!menuOpen) return;
    const handler = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [menuOpen]);

  const handleDeleteClick = () => {
    setMenuOpen(false);
    setPurgeData(false);
    setShowDeleteModal(true);
  };

  const handleConfirmDelete = () => {
    setShowDeleteModal(false);
    if (location.pathname === `/colony/${colony.id}`) {
      navigate("/");
    }
    deleteColony(colony.id, purgeData);
  };

  const handleStartRename = () => {
    setMenuOpen(false);
    setRenameValue(diskName);
    setRenameError(null);
    setRenaming(true);
  };

  const cancelRename = () => {
    setRenaming(false);
    setRenameValue("");
    setRenameError(null);
  };

  const handleConfirmRename = async () => {
    const next = renameValue.trim();
    if (renameSaving) return;
    if (!next || next === diskName) {
      cancelRename();
      return;
    }
    setRenameSaving(true);
    setRenameError(null);
    try {
      await coloniesApi.rename(diskName, next);
      // The new colony id is derived the same way the rest of the app
      // derives it — keep that mapping centralized.
      const newColonyId = slugToColonyId(next);
      // Re-fetch colonies so the sidebar picks up the renamed entry; if
      // we're currently viewing the renamed colony, route to its new id
      // before the old route 404s.
      if (location.pathname === `/colony/${colony.id}`) {
        navigate(`/colony/${newColonyId}`);
      }
      refresh();
      setRenaming(false);
      setRenameValue("");
    } catch (err) {
      setRenameError(err instanceof Error ? err.message : "Failed to rename");
    } finally {
      setRenameSaving(false);
    }
  };

  return (
    <>
      <div className="group relative flex items-center mx-2">
        {renaming ? (
          // Inline rename row — wraps the colony's status dot + an editable
          // input + Save/Cancel hints. We intentionally don't render this
          // as a <NavLink> so clicking the input doesn't navigate.
          <div
            className="flex items-center gap-2 px-3 py-1.5 rounded-md text-[12.5px] flex-1 min-w-0 bg-sidebar-active-bg"
            onClick={(e) => e.stopPropagation()}
          >
            <Tooltip
              label={describeColonyStatus(
                deriveColonyStatus(colony.sessionId !== null, liveness),
                liveness,
              )}
              className="flex-shrink-0"
              atCursor
            >
              <span
                className={`flex-shrink-0 w-2 h-2 rounded-full ${
                  STATUS_DOT_CLASS[deriveColonyStatus(colony.sessionId !== null, liveness)]
                }`}
              />
            </Tooltip>
            <input
              ref={renameInputRef}
              type="text"
              value={renameValue}
              onChange={(e) =>
                setRenameValue(
                  e.target.value.toLowerCase().replace(/\s+/g, "_").replace(/[^a-z0-9_]/g, ""),
                )
              }
              onKeyDown={(e) => {
                if (e.key === "Enter") handleConfirmRename();
                if (e.key === "Escape") cancelRename();
              }}
              onBlur={() => {
                // Defer slightly so a click on the Save/Cancel area can
                // fire before we close the editor on blur.
                window.setTimeout(() => {
                  if (!renameSaving) cancelRename();
                }, 120);
              }}
              disabled={renameSaving}
              className="flex-1 min-w-0 bg-transparent text-foreground placeholder:text-muted-foreground/40 focus:outline-none disabled:opacity-60"
              placeholder={diskName}
            />
            {renameSaving && (
              <Loader2 className="w-3 h-3 animate-spin text-muted-foreground flex-shrink-0" />
            )}
            {renameError && !renameSaving && (
              <span
                title={renameError}
                className="text-[10px] text-destructive flex-shrink-0"
              >
                !
              </span>
            )}
          </div>
        ) : (
        <NavLink
          to={`/colony/${colony.id}`}
          className={({ isActive }) =>
            `flex items-center gap-2 px-3 py-1.5 rounded-md text-[12.5px] transition-colors flex-1 min-w-0 ${
              isActive
                ? "bg-sidebar-active-bg text-foreground font-medium"
                : "text-foreground/70 hover:bg-sidebar-item-hover hover:text-foreground"
            }`
          }
        >
          <Tooltip
            label={describeColonyStatus(
              deriveColonyStatus(colony.sessionId !== null, liveness),
              liveness,
            )}
            className="flex-shrink-0"
            atCursor
          >
            <span
              className={`flex-shrink-0 w-2 h-2 rounded-full ${
                STATUS_DOT_CLASS[deriveColonyStatus(colony.sessionId !== null, liveness)]
              }`}
            />
          </Tooltip>
          <span className="truncate flex-1">{colony.name}</span>

          {onWorkspace && (
            <span
              title="Running on cloud computer"
              className="flex-shrink-0 inline-flex items-center gap-0.5 text-[9px] uppercase tracking-wider font-semibold px-1 py-px rounded bg-primary/15 text-primary"
            >
              <Cloud className="w-2.5 h-2.5" />
              Cloud
            </span>
          )}

        </NavLink>
        )}

        {/* 3-dot menu */}
        <div
          className="relative flex-shrink-0"
          ref={menuRef}
          onClick={(e) => e.stopPropagation()}
        >
          <button
            onClick={() => setMenuOpen((o) => !o)}
            className={`p-1 rounded-md transition-colors text-sidebar-muted hover:text-foreground hover:bg-sidebar-item-hover ${
              menuOpen ? "opacity-100" : "opacity-0 group-hover:opacity-100"
            }`}
          >
            <MoreHorizontal className="w-3.5 h-3.5" />
          </button>

          {menuOpen && (
            <div className="absolute right-0 top-7 z-50 w-44 rounded-lg border border-border/60 bg-card shadow-xl shadow-black/20 overflow-hidden py-1">
              <button
                onClick={handleStartRename}
                className="flex items-center gap-2 w-full px-3 py-1.5 text-[11.5px] text-foreground/80 hover:bg-sidebar-item-hover hover:text-foreground transition-colors"
              >
                <Pencil className="w-3 h-3" />
                Rename
              </button>
              <button
                onClick={handleDeleteClick}
                className="flex items-center gap-2 w-full px-3 py-1.5 text-[11.5px] text-destructive hover:bg-destructive/10 transition-colors"
              >
                <Trash2 className="w-3 h-3" />
                Delete colony
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Delete confirmation modal */}
      {showDeleteModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div
            className="absolute inset-0 bg-black/40 backdrop-blur-sm"
            onClick={() => setShowDeleteModal(false)}
          />
          <div className="relative bg-card border border-border/60 rounded-2xl shadow-2xl w-full max-w-[400px] p-6 flex flex-col gap-4">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-full bg-destructive/15 flex items-center justify-center flex-shrink-0">
                <AlertTriangle className="w-5 h-5 text-destructive" />
              </div>
              <div>
                <h3 className="text-sm font-semibold text-foreground">
                  Delete colony
                </h3>
              </div>
            </div>

            <p className="text-sm text-foreground/80">
              Are you sure you want to delete <span className="font-medium text-foreground">{colony.name}</span>?{" "}
              {purgeData
                ? "This agent and all its tracked data will be permanently deleted."
                : "This agent will be removed from your colonies."}
            </p>

            {onWorkspace && (
              <p className="text-xs text-foreground/60 flex items-start gap-1.5">
                <Cloud className="w-3 h-3 mt-0.5 flex-shrink-0 text-primary" />
                This colony also runs on your cloud computer — it will be removed there too.
              </p>
            )}

            <label className="flex items-start gap-2 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={purgeData}
                onChange={(e) => setPurgeData(e.target.checked)}
                className="mt-0.5 accent-destructive"
              />
              <span className="text-xs text-foreground/70">
                I want to completely remove the data tracked in this colony
              </span>
            </label>

            <div className="flex justify-end gap-2 mt-2">
              <button
                onClick={() => setShowDeleteModal(false)}
                className="px-4 py-2 rounded-lg text-sm font-medium text-foreground/70 hover:bg-muted/50 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleConfirmDelete}
                className="px-4 py-2 rounded-lg bg-destructive text-destructive-foreground text-sm font-medium hover:bg-destructive/90 transition-colors"
              >
                Delete
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
