import { useState, useCallback, useRef } from "react";
import { useNavigate } from "react-router-dom";
import {
  ChevronLeft,
  ChevronRight,
  MessageSquarePlus,
  Network,
  Sparkles,
  KeyRound,
  ChevronDown,
  Plus,
  X,
  Crown,
  Loader2,
} from "lucide-react";
import SidebarColonyItem from "./SidebarColonyItem";
import SidebarQueenItem from "./SidebarQueenItem";
import { useColony } from "@/context/ColonyContext";
import { queensApi } from "@/api/queens";
import { executionApi } from "@/api/execution";
import { slugToColonyId, sortQueenProfiles } from "@/lib/colony-registry";

export default function Sidebar() {
  const navigate = useNavigate();
  const { colonies, queens, queenProfiles, sidebarCollapsed, setSidebarCollapsed, refresh } = useColony();
  const activeQueenIds = new Set(
    queens.filter((q) => q.status === "online").map((q) => q.id),
  );
  const [coloniesExpanded, setColoniesExpanded] = useState(true);
  const [queensExpanded, setQueensExpanded] = useState(true);

  // Colony creation
  const [createColonyOpen, setCreateColonyOpen] = useState(false);
  const [newColonyQueen, setNewColonyQueen] = useState("");
  const [newColonyName, setNewColonyName] = useState("");
  const [newColonyGoal, setNewColonyGoal] = useState("");
  const [creatingColony, setCreatingColony] = useState(false);

  const handleCreateColony = async () => {
    const cname = newColonyName.trim();
    if (!cname || !newColonyQueen || creatingColony) return;
    setCreatingColony(true);
    try {
      const { session_id } = await queensApi.createNewSession(newColonyQueen, newColonyGoal.trim() || undefined);
      await executionApi.colonySpawn(session_id, cname, newColonyGoal.trim() || undefined);
      setCreateColonyOpen(false);
      setNewColonyQueen("");
      setNewColonyName("");
      setNewColonyGoal("");
      refresh();
      navigate(`/colony/${slugToColonyId(cname)}`);
    } catch (err) {
      console.error("Failed to create colony:", err);
    } finally {
      setCreatingColony(false);
    }
  };

  // ── Resizable width ──────────────────────────────────────────────────
  const MIN_WIDTH = 180;
  const MAX_WIDTH = 400;
  const [width, setWidth] = useState(240);
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
      const delta = ev.clientX - startX.current;
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

  if (sidebarCollapsed) {
    return (
      <aside className="w-[52px] flex-shrink-0 flex flex-col bg-sidebar-bg border-r border-sidebar-border h-full">
        {/* Logo */}
        <div className="h-12 flex items-center justify-center border-b border-border/60">
          <button
            onClick={() => navigate("/")}
            className="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center hover:bg-primary/20 transition-colors"
          >
            <span className="text-primary text-sm font-bold">H</span>
          </button>
        </div>

        {/* Expand button */}
        <div className="flex-1 flex flex-col items-center py-3 gap-1">
          <button
            onClick={() => setSidebarCollapsed(false)}
            className="w-8 h-8 rounded-md flex items-center justify-center text-sidebar-muted hover:text-foreground hover:bg-sidebar-item-hover transition-colors"
            title="Expand sidebar"
          >
            <ChevronRight className="w-4 h-4" />
          </button>
        </div>
      </aside>
    );
  }

  return (
    <>
    <aside
      className="flex-shrink-0 flex flex-col bg-sidebar-bg border-r border-sidebar-border h-full relative"
      style={{ width }}
    >
      {/* Drag handle on right edge */}
      <div
        onMouseDown={onDragStart}
        className="absolute top-0 right-0 w-1 h-full cursor-col-resize hover:bg-primary/30 active:bg-primary/50 transition-colors z-10"
      />
      {/* Header */}
      <div className="h-12 flex items-center justify-between px-4 border-b border-border/60">
        <button
          onClick={() => navigate("/")}
          className="flex items-center gap-2 hover:opacity-80 transition-opacity"
        >
          <div className="w-7 h-7 rounded-lg bg-primary/10 flex items-center justify-center">
            <span className="text-primary text-xs font-bold">H</span>
          </div>
          <div className="flex items-baseline gap-0.5">
            <span className="text-sm font-bold text-primary">Open</span>
            <span className="text-sm font-bold text-foreground">Hive</span>
          </div>
        </button>
        <button
          onClick={() => setSidebarCollapsed(true)}
          className="p-1 rounded-md text-sidebar-muted hover:text-foreground hover:bg-sidebar-item-hover transition-colors"
          title="Collapse sidebar"
        >
          <ChevronLeft className="w-4 h-4" />
        </button>
      </div>

      {/* Nav links */}
      <div className="px-2 py-3 flex flex-col gap-0.5 border-b border-border/60">
        <button
          onClick={() => navigate("/")}
          className="flex items-center gap-2.5 px-3 py-1.5 rounded-md text-sm text-foreground/70 hover:bg-sidebar-item-hover hover:text-foreground transition-colors"
        >
          <MessageSquarePlus className="w-4 h-4" />
          <span>New Chat</span>
        </button>
        <button
          onClick={() => navigate("/org-chart")}
          className="flex items-center gap-2.5 px-3 py-1.5 rounded-md text-sm text-foreground/70 hover:bg-sidebar-item-hover hover:text-foreground transition-colors"
        >
          <Network className="w-4 h-4" />
          <span>Org Chart</span>
        </button>
        <button
          onClick={() => navigate("/prompt-library")}
          className="flex items-center gap-2.5 px-3 py-1.5 rounded-md text-sm text-foreground/70 hover:bg-sidebar-item-hover hover:text-foreground transition-colors"
        >
          <Sparkles className="w-4 h-4" />
          <span>Prompt Library</span>
        </button>
        <button
          onClick={() => navigate("/credentials")}
          className="flex items-center gap-2.5 px-3 py-1.5 rounded-md text-sm text-foreground/70 hover:bg-sidebar-item-hover hover:text-foreground transition-colors"
        >
          <KeyRound className="w-4 h-4" />
          <span>Credentials</span>
        </button>
      </div>

      {/* COLONIES section */}
      <div className="flex-1 overflow-y-auto min-h-0">
        <div className="py-2">
          <div className="flex items-center px-4 py-1.5">
            <button
              onClick={() => setColoniesExpanded((v) => !v)}
              className="flex items-center gap-1.5 flex-1 text-[11px] font-semibold text-sidebar-section-text uppercase tracking-wider hover:text-foreground transition-colors"
            >
              <ChevronDown
                className={`w-3 h-3 transition-transform ${coloniesExpanded ? "" : "-rotate-90"}`}
              />
              <span>Colonies</span>
              {colonies.length > 0 && (
                <span className="text-[10px] bg-sidebar-item-hover rounded-full px-1.5 py-0.5 font-medium">
                  {colonies.length}
                </span>
              )}
            </button>
            <button
              onClick={() => setCreateColonyOpen(true)}
              className="p-0.5 rounded text-sidebar-section-text hover:text-foreground hover:bg-sidebar-item-hover transition-colors"
              title="Create colony"
            >
              <Plus className="w-3.5 h-3.5" />
            </button>
          </div>
          {coloniesExpanded && (
            <div className="flex flex-col gap-0.5 mt-0.5">
              {colonies.map((colony) => (
                <SidebarColonyItem key={colony.id} colony={colony} />
              ))}
              {colonies.length === 0 && (
                <p className="px-5 py-2 text-xs text-sidebar-muted">
                  No colonies yet
                </p>
              )}
            </div>
          )}
        </div>

        {/* QUEEN BEES section */}
        <div className="py-2">
          <button
            onClick={() => setQueensExpanded((v) => !v)}
            className="flex items-center gap-1.5 px-4 py-1.5 w-full text-[11px] font-semibold text-sidebar-section-text uppercase tracking-wider hover:text-foreground transition-colors"
          >
            <ChevronDown
              className={`w-3 h-3 transition-transform ${queensExpanded ? "" : "-rotate-90"}`}
            />
            <span>Queen Bees</span>
          </button>
          {queensExpanded && (
            <div className="flex flex-col gap-0.5 mt-0.5">
              {queenProfiles.map((queen) => (
                <SidebarQueenItem
                  key={queen.id}
                  queen={queen}
                  isActive={activeQueenIds.has(queen.id)}
                />
              ))}
              {queenProfiles.length === 0 && (
                <p className="px-5 py-2 text-xs text-sidebar-muted">
                  Loading queens...
                </p>
              )}
            </div>
          )}
        </div>
      </div>
    </aside>

    {/* Create Colony modal */}
    {createColonyOpen && (
      <div className="fixed inset-0 z-50 flex items-center justify-center">
        <div className="absolute inset-0 bg-black/40" onClick={() => !creatingColony && setCreateColonyOpen(false)} />
        <div className="relative bg-card border border-border/60 rounded-xl shadow-2xl w-full max-w-md p-6 space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-foreground">Create Colony</h2>
            <button onClick={() => setCreateColonyOpen(false)} className="p-1 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/50">
              <X className="w-4 h-4" />
            </button>
          </div>

          <div className="space-y-3">
            <div>
              <label className="block text-[11px] font-medium text-muted-foreground mb-1">Queen Bee <span className="text-primary">*</span></label>
              <div className="grid grid-cols-2 gap-1.5 max-h-[160px] overflow-y-auto">
                {sortQueenProfiles(queenProfiles).map((q) => (
                  <button key={q.id} onClick={() => setNewColonyQueen(q.id)}
                    className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-left text-xs transition-colors ${
                      newColonyQueen === q.id
                        ? "border-primary/40 bg-primary/[0.06] text-primary"
                        : "border-border/50 text-foreground hover:border-primary/30"
                    }`}>
                    <Crown className="w-3 h-3 flex-shrink-0" />
                    <div className="min-w-0">
                      <p className="font-medium truncate">{q.name}</p>
                      <p className="text-[10px] text-muted-foreground truncate">{q.title}</p>
                    </div>
                  </button>
                ))}
              </div>
            </div>

            <div>
              <label className="block text-[11px] font-medium text-muted-foreground mb-1">Colony Name <span className="text-primary">*</span></label>
              <input type="text" value={newColonyName}
                onChange={(e) => setNewColonyName(e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, ""))}
                placeholder="e.g. research_team" autoFocus
                className="w-full rounded-md border border-border/60 bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-primary" />
            </div>

            <div>
              <label className="block text-[11px] font-medium text-muted-foreground mb-1">Goal <span className="text-muted-foreground/40">(optional)</span></label>
              <textarea value={newColonyGoal} onChange={(e) => setNewColonyGoal(e.target.value)}
                placeholder="Describe what this colony should work on" rows={3}
                className="w-full rounded-md border border-border/60 bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-primary resize-none" />
            </div>
          </div>

          <div className="flex justify-end gap-2 pt-2">
            <button onClick={() => { setCreateColonyOpen(false); setNewColonyQueen(""); setNewColonyName(""); setNewColonyGoal(""); }}
              disabled={creatingColony}
              className="px-3 py-1.5 rounded-md text-xs font-medium text-muted-foreground hover:text-foreground hover:bg-muted/50">
              Cancel
            </button>
            <button onClick={handleCreateColony} disabled={creatingColony || !newColonyName.trim() || !newColonyQueen}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50">
              {creatingColony ? <><Loader2 className="w-3 h-3 animate-spin" /> Creating...</> : "Create"}
            </button>
          </div>
        </div>
      </div>
    )}
    </>
  );
}
