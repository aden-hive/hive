import { useState, useRef, useEffect } from "react";
import { NavLink, useNavigate, useLocation } from "react-router-dom";
import { MoreHorizontal, Trash2, AlertTriangle } from "lucide-react";
import type { Colony } from "@/types/colony";
import { useColony } from "@/context/ColonyContext";

interface SidebarColonyItemProps {
  colony: Colony;
}

export default function SidebarColonyItem({ colony }: SidebarColonyItemProps) {
  const { deleteColony } = useColony();
  const navigate = useNavigate();
  const location = useLocation();
  const [menuOpen, setMenuOpen] = useState(false);
  const [showDeleteModal, setShowDeleteModal] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

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
    setShowDeleteModal(true);
  };

  const handleConfirmDelete = () => {
    setShowDeleteModal(false);
    if (location.pathname === `/colony/${colony.id}`) {
      navigate("/");
    }
    deleteColony(colony.id);
  };

  return (
    <>
      <div className="group relative flex items-center mx-2">
        <NavLink
          to={`/colony/${colony.id}`}
          className={({ isActive }) =>
            `flex items-center gap-2 px-3 py-1.5 rounded-md text-sm transition-colors flex-1 min-w-0 ${
              isActive
                ? "bg-sidebar-active-bg text-foreground font-medium"
                : "text-foreground/70 hover:bg-sidebar-item-hover hover:text-foreground"
            }`
          }
        >
          <span
            className={`flex-shrink-0 w-2 h-2 rounded-full ${
              colony.status === "running" ? "bg-status-online" : "bg-status-offline"
            }`}
          />
          <span className="truncate flex-1">{colony.name}</span>

          {colony.unreadCount > 0 && (
            <span className="flex-shrink-0 min-w-[18px] h-[18px] flex items-center justify-center rounded-full bg-badge-unread text-badge-unread-text text-[10px] font-bold px-1">
              {colony.unreadCount}
            </span>
          )}
        </NavLink>

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
            <div className="absolute right-0 top-7 z-50 w-40 rounded-lg border border-border/60 bg-card shadow-xl shadow-black/20 overflow-hidden py-1">
              <button
                onClick={handleDeleteClick}
                className="flex items-center gap-2 w-full px-3 py-1.5 text-xs text-destructive hover:bg-destructive/10 transition-colors"
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
                <p className="text-xs text-muted-foreground mt-0.5">
                  This action cannot be undone
                </p>
              </div>
            </div>

            <p className="text-sm text-foreground/80">
              Are you sure you want to delete <span className="font-medium text-foreground">{colony.name}</span>? This agent will be permanently deleted.
            </p>

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
