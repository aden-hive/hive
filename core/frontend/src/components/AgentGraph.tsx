// core/frontend/src/components/AgentGraphEnhanced.tsx

import { memo, useMemo, useState, useRef, useEffect, useCallback } from "react";
import { Play, Pause, Loader2, CheckCircle2, ZoomIn, ZoomOut, Move, Download, Search, X, Maximize2, Minimize2 } from "lucide-react";

export type NodeStatus = "running" | "complete" | "pending" | "error" | "looping";
export type NodeType = "execution" | "trigger";

export interface GraphNode {
  id: string;
  label: string;
  status: NodeStatus;
  nodeType?: NodeType;
  triggerType?: string;
  triggerConfig?: Record<string, unknown>;
  next?: string[];
  backEdges?: string[];
  iterations?: number;
  maxIterations?: number;
  statusLabel?: string;
  edgeLabels?: Record<string, string>;
}

type RunState = "idle" | "deploying" | "running";

interface AgentGraphProps {
  nodes: GraphNode[];
  title: string;
  onNodeClick?: (node: GraphNode) => void;
  onRun?: () => void;
  onPause?: () => void;
  version?: string;
  runState?: RunState;
  building?: boolean;
  queenPhase?: "planning" | "building" | "staging" | "running";
}

interface ViewState {
  scale: number;
  offsetX: number;
  offsetY: number;
}

// ============ RunButton Component ============
const RunButton = memo(function RunButton({ runState, disabled, onRun, onPause, btnRef }: { 
  runState: RunState; 
  disabled: boolean; 
  onRun: () => void; 
  onPause: () => void; 
  btnRef: React.Ref<HTMLButtonElement>;
}) {
  const [hovered, setHovered] = useState(false);
  const showPause = runState === "running" && hovered;

  return (
    <button
      ref={btnRef}
      onClick={runState === "running" ? onPause : onRun}
      disabled={runState === "deploying" || disabled}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      className={`flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[11px] font-semibold transition-all duration-200 ${
        showPause
          ? "bg-amber-500/15 text-amber-400 border border-amber-500/40 hover:bg-amber-500/25 active:scale-95 cursor-pointer"
          : runState === "running"
          ? "bg-green-500/15 text-green-400 border border-green-500/30 cursor-pointer"
          : runState === "deploying"
          ? "bg-primary/10 text-primary border border-primary/20 cursor-default"
          : disabled
          ? "bg-muted/30 text-muted-foreground/40 border border-border/20 cursor-not-allowed"
          : "bg-primary/10 text-primary border border-primary/20 hover:bg-primary/20 hover:border-primary/40 active:scale-95"
      }`}
    >
      {runState === "deploying" ? (
        <Loader2 className="w-3 h-3 animate-spin" />
      ) : showPause ? (
        <Pause className="w-3 h-3 fill-current" />
      ) : runState === "running" ? (
        <CheckCircle2 className="w-3 h-3" />
      ) : (
        <Play className="w-3 h-3 fill-current" />
      )}
      {runState === "deploying" ? "Deploying…" : showPause ? "Pause" : runState === "running" ? "Running" : "Run"}
    </button>
  );
});

// ============ GraphControls Component ============
function GraphControls({ 
  scale, onZoomIn, onZoomOut, onResetView, onExport, 
  searchActive, onSearchToggle, searchTerm, onSearchChange,
  searchResultCount, currentResultIndex, onNextResult, onPrevResult, onClearSearch,
  title, version, runButton, building, isFullscreen, onToggleFullscreen
}: any) {
  const [showExportMenu, setShowExportMenu] = useState(false);
  const exportMenuRef = useRef<HTMLDivElement>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (exportMenuRef.current && !exportMenuRef.current.contains(event.target as Node)) {
        setShowExportMenu(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  useEffect(() => {
    if (searchActive && searchInputRef.current) {
      searchInputRef.current.focus();
    }
  }, [searchActive]);

  return (
    <div className="relative px-5 pt-4 pb-2 flex items-center justify-between">
      <div className="flex items-center gap-2">
        <p className="text-[11px] text-muted-foreground font-medium uppercase tracking-wider">{title || "Pipeline"}</p>
        {version && <span className="text-[10px] font-mono font-medium text-muted-foreground/60 border border-border/30 rounded px-1 py-0.5 leading-none">{version}</span>}
        {building && <span className="text-[10px] text-primary/60 animate-pulse">Building...</span>}
      </div>
      <div className="flex items-center gap-1">
        {onSearchToggle && (
          <button onClick={onSearchToggle} className={`p-1.5 rounded-md transition-colors ${searchActive ? "bg-primary/20 text-primary" : "text-muted-foreground hover:text-foreground hover:bg-muted/50"}`}>
            <Search className="w-3.5 h-3.5" />
          </button>
        )}
        <button onClick={onZoomOut} className="p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/50">
          <ZoomOut className="w-3.5 h-3.5" />
        </button>
        <span className="text-[10px] text-muted-foreground min-w-[40px] text-center">{Math.round(scale * 100)}%</span>
        <button onClick={onZoomIn} className="p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/50">
          <ZoomIn className="w-3.5 h-3.5" />
        </button>
        <button onClick={onResetView} className="p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/50">
          <Move className="w-3.5 h-3.5" />
        </button>
        <button onClick={onToggleFullscreen} className="p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/50">
          {isFullscreen ? <Minimize2 className="w-3.5 h-3.5" /> : <Maximize2 className="w-3.5 h-3.5" />}
        </button>
        <div className="relative" ref={exportMenuRef}>
          <button onClick={() => setShowExportMenu(!showExportMenu)} className="p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/50">
            <Download className="w-3.5 h-3.5" />
          </button>
          {showExportMenu && (
            <div className="absolute right-0 top-full mt-1 bg-card border border-border rounded-md shadow-lg z-10 py-1 min-w-[120px]">
              <button onClick={() => onExport("png")} className="block w-full text-left px-3 py-1.5 text-xs hover:bg-muted/50">Export as PNG</button>
              <button onClick={() => onExport("svg")} className="block w-full text-left px-3 py-1.5 text-xs hover:bg-muted/50">Export as SVG</button>
            </div>
          )}
        </div>
        {runButton}
      </div>
      {searchActive && onSearchChange && (
        <div className="absolute top-12 left-5 right-5 z-20 animate-in fade-in slide-in-from-top-2 duration-200">
          <div className="bg-card border border-primary/30 rounded-lg shadow-lg">
            <div className="flex items-center gap-2 px-3 py-2">
              <Search className="w-4 h-4 text-muted-foreground flex-shrink-0" />
              <input ref={searchInputRef} type="text" value={searchTerm} onChange={(e) => onSearchChange(e.target.value)} placeholder="Search nodes by name or ID..." className="flex-1 bg-transparent text-sm outline-none" />
              {searchResultCount > 0 && (
                <div className="flex items-center gap-1">
                  <span className="text-xs text-muted-foreground">{currentResultIndex + 1}/{searchResultCount}</span>
                  <button onClick={onPrevResult} className="p-1 rounded hover:bg-muted/50">←</button>
                  <button onClick={onNextResult} className="p-1 rounded hover:bg-muted/50">→</button>
                </div>
              )}
              <button onClick={onClearSearch} className="p-1 rounded hover:bg-muted/50"><X className="w-4 h-4" /></button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ============ Constants ============
const NODE_W_MAX = 180;
const NODE_H = 44;
const GAP_Y = 48;
const TOP_Y = 30;
const MARGIN_LEFT = 20;
const MARGIN_RIGHT = 50;
const SVG_BASE_W = 320;
const GAP_X = 12;
const BACK_EDGE_BASE_OFFSET = 28;
const BACK_EDGE_INCREMENT = 18;

const statusColors: Record<NodeStatus, { dot: string; bg: string; border: string; glow: string }> = {
  running: { dot: "hsl(45,95%,58%)", bg: "hsl(45,95%,58%,0.08)", border: "hsl(45,95%,58%,0.5)", glow: "hsl(45,95%,58%,0.15)" },
  looping: { dot: "hsl(38,90%,55%)", bg: "hsl(38,90%,55%,0.08)", border: "hsl(38,90%,55%,0.5)", glow: "hsl(38,90%,55%,0.15)" },
  complete: { dot: "hsl(43,70%,45%)", bg: "hsl(43,70%,45%,0.05)", border: "hsl(43,70%,45%,0.25)", glow: "none" },
  pending: { dot: "hsl(35,15%,28%)", bg: "hsl(35,10%,12%)", border: "hsl(35,10%,20%)", glow: "none" },
  error: { dot: "hsl(0,65%,55%)", bg: "hsl(0,65%,55%,0.06)", border: "hsl(0,65%,55%,0.3)", glow: "hsl(0,65%,55%,0.1)" },
};

const triggerColors = { bg: "hsl(210,25%,14%)", border: "hsl(210,30%,30%)", text: "hsl(210,30%,65%)", icon: "hsl(210,40%,55%)" };
const triggerIcons: Record<string, string> = { webhook: "⚡", timer: "⏱", api: "→", event: "∿" };

function truncateLabel(label: string, availablePx: number, fontSize: number): string {
  const avgCharW = fontSize * 0.58;
  const maxChars = Math.floor(availablePx / avgCharW);
  if (label.length <= maxChars) return label;
  return label.slice(0, Math.max(maxChars - 1, 1)) + "…";
}

// Real export functions (replace with actual implementation)
async function exportAsPNG(svgElement: SVGSVGElement, filename: string): Promise<void> {
  try {
    // Clone the SVG to avoid modifying the original
    const clone = svgElement.cloneNode(true) as SVGSVGElement;
    
    // Get the current transform and apply it to the clone
    const transform = svgElement.style.transform;
    if (transform) {
      clone.style.transform = transform;
    }
    
    // Use html2canvas or similar library here
    // For now, we'll use a simple approach
    const serializer = new XMLSerializer();
    const svgString = serializer.serializeToString(clone);
    const blob = new Blob([svgString], { type: "image/svg+xml" });
    const url = URL.createObjectURL(blob);
    
    const img = new Image();
    img.onload = () => {
      const canvas = document.createElement("canvas");
      canvas.width = svgElement.clientWidth;
      canvas.height = svgElement.clientHeight;
      const ctx = canvas.getContext("2d");
      if (ctx) {
        ctx.drawImage(img, 0, 0);
        canvas.toBlob((blob) => {
          if (blob) {
            const pngUrl = URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = pngUrl;
            a.download = filename;
            a.click();
            URL.revokeObjectURL(pngUrl);
          }
        });
      }
      URL.revokeObjectURL(url);
    };
    img.src = url;
  } catch (error) {
    console.error("Export PNG failed:", error);
    throw error;
  }
}

function exportAsSVG(svgElement: SVGSVGElement, filename: string): void {
  try {
    // Clone the SVG to avoid modifying the original
    const clone = svgElement.cloneNode(true) as SVGSVGElement;
    
    // Apply current transform to the clone
    const transform = svgElement.style.transform;
    if (transform) {
      clone.style.transform = transform;
    }
    
    const serializer = new XMLSerializer();
    const svgString = serializer.serializeToString(clone);
    const blob = new Blob([svgString], { type: "image/svg+xml" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  } catch (error) {
    console.error("Export SVG failed:", error);
    throw error;
  }
}

// ============ Main Component ============
export default function AgentGraphEnhanced({ nodes, title, onNodeClick, onRun, onPause, version, runState: externalRunState, building, queenPhase }: AgentGraphProps) {
  const [localRunState, setLocalRunState] = useState<RunState>("idle");
  const runState = externalRunState ?? localRunState;
  const runBtnRef = useRef<HTMLButtonElement>(null);
  const svgContainerRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const graphContainerRef = useRef<HTMLDivElement>(null);
  
  const [viewState, setViewState] = useState<ViewState>({ scale: 1, offsetX: 0, offsetY: 0 });
  const [isPanning, setIsPanning] = useState(false);
  const [panStart, setPanStart] = useState({ x: 0, y: 0 });
  const [searchTerm, setSearchTerm] = useState("");
  const [highlightedNodeId, setHighlightedNodeId] = useState<string | null>(null);
  const [searchResults, setSearchResults] = useState<string[]>([]);
  const [currentSearchIndex, setCurrentSearchIndex] = useState(0);
  const [showSearch, setShowSearch] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);

  // Fullscreen handlers
  const toggleFullscreen = useCallback(async () => {
    if (!graphContainerRef.current) return;
    
    try {
      if (!isFullscreen) {
        await graphContainerRef.current.requestFullscreen();
      } else {
        await document.exitFullscreen();
      }
    } catch (error) {
      console.error("Fullscreen error:", error);
    }
  }, [isFullscreen]);

  // Listen for fullscreen changes
  useEffect(() => {
    const handleFullscreenChange = () => {
      setIsFullscreen(!!document.fullscreenElement);
    };
    
    document.addEventListener("fullscreenchange", handleFullscreenChange);
    return () => document.removeEventListener("fullscreenchange", handleFullscreenChange);
  }, []);

  const handleRun = () => {
    if (runState !== "idle") return;
    if (onRun) onRun();
    else {
      setLocalRunState("deploying");
      setTimeout(() => setLocalRunState("running"), 1800);
      setTimeout(() => setLocalRunState("idle"), 5000);
    }
  };

  const handleZoomIn = () => setViewState(prev => ({ ...prev, scale: Math.min(prev.scale * 1.2, 3) }));
  const handleZoomOut = () => setViewState(prev => ({ ...prev, scale: Math.max(prev.scale / 1.2, 0.3) }));
  const handleResetView = () => setViewState({ scale: 1, offsetX: 0, offsetY: 0 });

  const handlePanStart = (e: React.MouseEvent) => {
    if (e.button !== 0) return;
    setIsPanning(true);
    setPanStart({ x: e.clientX - viewState.offsetX, y: e.clientY - viewState.offsetY });
  };
  const handlePanMove = (e: React.MouseEvent) => {
    if (!isPanning) return;
    setViewState(prev => ({ ...prev, offsetX: e.clientX - panStart.x, offsetY: e.clientY - panStart.y }));
  };
  const handlePanEnd = () => setIsPanning(false);
  const handleWheel = (e: React.WheelEvent) => {
    if (e.ctrlKey || e.metaKey) {
      e.preventDefault();
      const delta = e.deltaY > 0 ? 0.9 : 1.1;
      setViewState(prev => ({ ...prev, scale: Math.min(Math.max(prev.scale * delta, 0.3), 3) }));
    }
  };

  // Search handlers - now using node IDs instead of indexes
  const handleSearch = useCallback((term: string) => {
    setSearchTerm(term);
    if (!term.trim()) { 
      setSearchResults([]); 
      setHighlightedNodeId(null); 
      return; 
    }
    const results: string[] = [];
    nodes.forEach((node) => {
      if (node.label.toLowerCase().includes(term.toLowerCase()) || 
          node.id.toLowerCase().includes(term.toLowerCase())) {
        results.push(node.id);
      }
    });
    setSearchResults(results);
    setCurrentSearchIndex(0);
    setHighlightedNodeId(results.length > 0 ? results[0] : null);
  }, [nodes]);

  const handleNextResult = useCallback(() => {
    if (searchResults.length === 0) return;
    const nextIndex = (currentSearchIndex + 1) % searchResults.length;
    setCurrentSearchIndex(nextIndex);
    setHighlightedNodeId(searchResults[nextIndex]);
    
    // Scroll to highlighted node if needed
    const highlightedElement = document.getElementById(`node-${searchResults[nextIndex]}`);
    if (highlightedElement) {
      highlightedElement.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, [searchResults, currentSearchIndex]);

  const handlePrevResult = useCallback(() => {
    if (searchResults.length === 0) return;
    const prevIndex = (currentSearchIndex - 1 + searchResults.length) % searchResults.length;
    setCurrentSearchIndex(prevIndex);
    setHighlightedNodeId(searchResults[prevIndex]);
    
    const highlightedElement = document.getElementById(`node-${searchResults[prevIndex]}`);
    if (highlightedElement) {
      highlightedElement.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, [searchResults, currentSearchIndex]);

  const clearSearch = useCallback(() => { 
    setSearchTerm(""); 
    setSearchResults([]); 
    setHighlightedNodeId(null); 
    setShowSearch(false); 
  }, []);

  // Clean up stale search results when nodes change
  useEffect(() => {
    if (searchResults.length > 0) {
      const validResults = searchResults.filter(id => 
        nodes.some(node => node.id === id)
      );
      if (validResults.length !== searchResults.length) {
        setSearchResults(validResults);
        if (highlightedNodeId && !validResults.includes(highlightedNodeId)) {
          setHighlightedNodeId(validResults[0] || null);
          setCurrentSearchIndex(0);
        }
      }
    }
  }, [nodes, searchResults, highlightedNodeId]);

  const handleExportPNG = useCallback(async () => {
    if (!svgRef.current) return;
    
    const originalScale = viewState.scale;
    const originalOffsetX = viewState.offsetX;
    const originalOffsetY = viewState.offsetY;
    
    try {
      // Reset view for export
      setViewState({ scale: 1, offsetX: 0, offsetY: 0 });
      await new Promise(resolve => setTimeout(resolve, 100));
      await exportAsPNG(svgRef.current, `${title || "graph"}_${Date.now()}`);
    } catch (error) {
      console.error("Export failed:", error);
    } finally {
      // Always restore view state
      setViewState({ scale: originalScale, offsetX: originalOffsetX, offsetY: originalOffsetY });
    }
  }, [title, viewState]);

  const handleExportSVG = useCallback(() => {
    if (!svgRef.current) return;
    try {
      exportAsSVG(svgRef.current, `${title || "graph"}_${Date.now()}`);
    } catch (error) {
      console.error("Export failed:", error);
    }
  }, [title]);

  // Layout computation
  const idxMap = useMemo(() => Object.fromEntries(nodes.map((n, i) => [n.id, i])), [nodes]);
  const backEdges = useMemo(() => {
    const edges: { fromIdx: number; toIdx: number }[] = [];
    nodes.forEach((n, i) => {
      (n.next || []).forEach((toId) => {
        const toIdx = idxMap[toId];
        if (toIdx !== undefined && toIdx <= i) edges.push({ fromIdx: i, toIdx });
      });
      (n.backEdges || []).forEach((toId) => {
        const toIdx = idxMap[toId];
        if (toIdx !== undefined) edges.push({ fromIdx: i, toIdx });
      });
    });
    return edges;
  }, [nodes, idxMap]);

  const forwardEdges = useMemo(() => {
    const edges: { fromIdx: number; toIdx: number; fanCount: number; fanIndex: number; label?: string }[] = [];
    nodes.forEach((n, i) => {
      const targets = (n.next || [])
        .map((toId) => ({ toId, toIdx: idxMap[toId] }))
        .filter((t): t is { toId: string; toIdx: number } => t.toIdx !== undefined && t.toIdx > i);
      targets.forEach(({ toId, toIdx }, fi) => {
        edges.push({ fromIdx: i, toIdx, fanCount: targets.length, fanIndex: fi, label: n.edgeLabels?.[toId] });
      });
    });
    return edges;
  }, [nodes, idxMap]);

  const layout = useMemo(() => {
    if (nodes.length === 0) return { layers: [] as number[], cols: [] as number[], maxCols: 1, nodeW: NODE_W_MAX, colSpacing: 0, firstColX: MARGIN_LEFT };
    const parents = new Map<number, number[]>();
    nodes.forEach((_, i) => parents.set(i, []));
    forwardEdges.forEach((e) => { parents.get(e.toIdx)!.push(e.fromIdx); });
    const layers = new Array(nodes.length).fill(0);
    for (let i = 0; i < nodes.length; i++) {
      const pars = parents.get(i) || [];
      if (pars.length > 0) layers[i] = Math.max(...pars.map((p) => layers[p])) + 1;
    }
    const layerGroups = new Map<number, number[]>();
    layers.forEach((l, i) => { const group = layerGroups.get(l) || []; group.push(i); layerGroups.set(l, group); });
    let maxCols = 1;
    layerGroups.forEach((group) => { maxCols = Math.max(maxCols, group.length); });
    const usableW = SVG_BASE_W - MARGIN_LEFT - MARGIN_RIGHT;
    const nodeW = Math.min(NODE_W_MAX, Math.floor((usableW - (maxCols - 1) * GAP_X) / maxCols));
    const colSpacing = nodeW + GAP_X;
    const totalNodesW = maxCols * nodeW + (maxCols - 1) * GAP_X;
    const firstColX = MARGIN_LEFT + (usableW - totalNodesW) / 2;
    const cols = new Array(nodes.length).fill(0);
    layerGroups.forEach((group) => {
      if (group.length === 1) cols[group[0]] = (maxCols - 1) / 2;
      else {
        const sorted = [...group].sort((a, b) => {
          const aParents = parents.get(a) || [];
          const bParents = parents.get(b) || [];
          const aAvg = aParents.length > 0 ? aParents.reduce((s, p) => s + cols[p], 0) / aParents.length : 0;
          const bAvg = bParents.length > 0 ? bParents.reduce((s, p) => s + cols[p], 0) / bParents.length : 0;
          return aAvg - bAvg;
        });
        const offset = (maxCols - group.length) / 2;
        sorted.forEach((nodeIdx, i) => { cols[nodeIdx] = offset + i; });
      }
    });
    return { layers, cols, maxCols, nodeW, colSpacing, firstColX };
  }, [nodes, forwardEdges]);

  const nodePos = (i: number) => ({ x: layout.firstColX + layout.cols[i] * layout.colSpacing, y: TOP_Y + layout.layers[i] * (NODE_H + GAP_Y) });

  const hasCollision = (fromLayer: number, toLayer: number, fromX: number, toX: number): boolean => {
    const minX = Math.min(fromX, toX);
    const maxX = Math.max(fromX, toX) + layout.nodeW;
    for (let i = 0; i < nodes.length; i++) {
      const l = layout.layers[i];
      if (l > fromLayer && l < toLayer) {
        const nx = layout.firstColX + layout.cols[i] * layout.colSpacing;
        if (nx < maxX && nx + layout.nodeW > minX) return true;
      }
    }
    return false;
  };

  const renderForwardEdge = (edge: { fromIdx: number; toIdx: number; fanCount: number; fanIndex: number; label?: string }, i: number) => {
    const from = nodePos(edge.fromIdx);
    const to = nodePos(edge.toIdx);
    const fromCenterX = from.x + layout.nodeW / 2;
    const toCenterX = to.x + layout.nodeW / 2;
    const y1 = from.y + NODE_H;
    const y2 = to.y;
    let startX = fromCenterX;
    if (edge.fanCount > 1) {
      const spread = layout.nodeW * 0.5;
      const step = edge.fanCount > 1 ? spread / (edge.fanCount - 1) : 0;
      startX = fromCenterX - spread / 2 + edge.fanIndex * step;
    }
    const midY = (y1 + y2) / 2;
    const fromLayer = layout.layers[edge.fromIdx];
    const toLayer = layout.layers[edge.toIdx];
    const skipsLayers = toLayer - fromLayer > 1;
    let d: string;
    if (skipsLayers && hasCollision(fromLayer, toLayer, from.x, to.x)) {
      const detourX = Math.min(from.x, to.x) - layout.nodeW * 0.4;
      d = `M ${startX} ${y1} C ${startX} ${y1 + 20}, ${detourX} ${y1 + 20}, ${detourX} ${midY} S ${toCenterX} ${y2 - 20} ${toCenterX} ${y2}`;
    } else {
      d = `M ${startX} ${y1} C ${startX} ${midY}, ${toCenterX} ${midY}, ${toCenterX} ${y2}`;
    }
    const fromNode = nodes[edge.fromIdx];
    const isActive = fromNode.status === "complete" || fromNode.status === "running" || fromNode.status === "looping";
    const strokeColor = isActive ? "hsl(43,70%,45%,0.35)" : "hsl(35,10%,20%)";
    const arrowColor = isActive ? "hsl(43,70%,45%,0.5)" : "hsl(35,10%,22%)";
    return (
      <g key={`fwd-${i}`}>
        <path d={d} fill="none" stroke={strokeColor} strokeWidth={1.5} />
        <polygon points={`${toCenterX - 4},${y2 - 6} ${toCenterX + 4},${y2 - 6} ${toCenterX},${y2 - 1}`} fill={arrowColor} />
        {edge.label && <text x={(startX + toCenterX) / 2 + 8} y={midY - 2} fill="hsl(35,15%,40%)" fontSize={9} fontStyle="italic">{edge.label}</text>}
      </g>
    );
  };

  const renderBackEdge = (edge: { fromIdx: number; toIdx: number }, i: number) => {
    const from = nodePos(edge.fromIdx);
    const to = nodePos(edge.toIdx);
    const rightX = Math.max(from.x, to.x) + layout.nodeW;
    const rightOffset = BACK_EDGE_BASE_OFFSET + i * BACK_EDGE_INCREMENT;
    const startX = from.x + layout.nodeW;
    const startY = from.y + NODE_H / 2;
    const endX = to.x + layout.nodeW;
    const endY = to.y + NODE_H / 2;
    const curveX = rightX + rightOffset;
    const fromNode = nodes[edge.fromIdx];
    const isActive = fromNode.status === "complete" || fromNode.status === "running" || fromNode.status === "looping";
    const color = isActive ? "hsl(38,80%,50%,0.3)" : "hsl(35,10%,20%)";
    const path = `M ${startX} ${startY} C ${startX + 12} ${startY}, ${curveX} ${startY}, ${curveX} ${startY - 12} L ${curveX} ${endY + 12} C ${curveX} ${endY}, ${endX + 12} ${endY}, ${endX + 6} ${endY}`;
    return (
      <g key={`back-${i}`}>
        <path d={path} fill="none" stroke={color} strokeWidth={1.5} strokeDasharray="4 3" />
        <polygon points={`${endX + 6},${endY - 3} ${endX + 6},${endY + 3} ${endX},${endY}`} fill={isActive ? "hsl(38,80%,50%,0.45)" : "hsl(35,10%,22%)"} />
      </g>
    );
  };

  const renderTriggerNode = (node: GraphNode, i: number) => {
    const pos = nodePos(i);
    const icon = triggerIcons[node.triggerType || ""] || "⚡";
    const triggerFontSize = layout.nodeW < 140 ? 10.5 : 11.5;
    const triggerAvailW = layout.nodeW - 38;
    const triggerDisplayLabel = truncateLabel(node.label, triggerAvailW, triggerFontSize);
    const nextFireIn = node.triggerConfig?.next_fire_in as number | undefined;
    let countdownLabel: string | null = null;
    if (nextFireIn != null && nextFireIn > 0) {
      const h = Math.floor(nextFireIn / 3600);
      const m = Math.floor((nextFireIn % 3600) / 60);
      const s = Math.floor(nextFireIn % 60);
      countdownLabel = h > 0 ? `next in ${h}h ${String(m).padStart(2, "0")}m` : `next in ${m}m ${String(s).padStart(2, "0")}s`;
    }
    const isHighlighted = highlightedNodeId === node.id;
    return (
      <g key={node.id} id={`node-${node.id}`} onClick={() => onNodeClick?.(node)} style={{ cursor: onNodeClick ? "pointer" : "default" }}>
        {isHighlighted && <rect x={pos.x - 4} y={pos.y - 4} width={layout.nodeW + 8} height={NODE_H + 8} rx={NODE_H / 2 + 4} fill="none" stroke="hsl(210,100%,60%)" strokeWidth={2} strokeDasharray="4 2" />}
        <rect x={pos.x} y={pos.y} width={layout.nodeW} height={NODE_H} rx={NODE_H / 2} fill={triggerColors.bg} stroke={triggerColors.border} strokeWidth={1} strokeDasharray="4 2" />
        <text x={pos.x + 18} y={pos.y + NODE_H / 2} fill={triggerColors.icon} fontSize={13} textAnchor="middle" dominantBaseline="middle">{icon}</text>
        <text x={pos.x + 32} y={pos.y + NODE_H / 2} fill={triggerColors.text} fontSize={triggerFontSize} fontWeight={500} dominantBaseline="middle" letterSpacing="0.01em">{triggerDisplayLabel}</text>
        {countdownLabel && <text x={pos.x + layout.nodeW / 2} y={pos.y + NODE_H + 13} fill="hsl(210,30%,50%)" fontSize={9.5} textAnchor="middle" fontStyle="italic" opacity={0.7}>{countdownLabel}</text>}
      </g>
    );
  };

  const renderNode = (node: GraphNode, i: number) => {
    if (node.nodeType === "trigger") return renderTriggerNode(node, i);
    const pos = nodePos(i);
    const isActive = node.status === "running" || node.status === "looping";
    const isDone = node.status === "complete";
    const colors = statusColors[node.status];
    const fontSize = layout.nodeW < 140 ? 10.5 : 12.5;
    const labelAvailW = layout.nodeW - 38;
    const displayLabel = truncateLabel(node.label, labelAvailW, fontSize);
    const isHighlighted = highlightedNodeId === node.id;
    return (
      <g key={node.id} id={`node-${node.id}`} onClick={() => onNodeClick?.(node)} style={{ cursor: onNodeClick ? "pointer" : "default" }}>
        {isHighlighted && <rect x={pos.x - 4} y={pos.y - 4} width={layout.nodeW + 8} height={NODE_H + 8} rx={16} fill="none" stroke="hsl(210,100%,60%)" strokeWidth={2} strokeDasharray="4 2" />}
        {isActive && (
          <>
            <rect x={pos.x - 4} y={pos.y - 4} width={layout.nodeW + 8} height={NODE_H + 8} rx={16} fill={colors.glow} />
            <rect x={pos.x - 2} y={pos.y - 2} width={layout.nodeW + 4} height={NODE_H + 4} rx={14} fill="none" stroke={colors.dot} strokeWidth={1} opacity={0.25} style={{ animation: "pulse-ring 2.5s ease-out infinite" }} />
          </>
        )}
        <rect x={pos.x} y={pos.y} width={layout.nodeW} height={NODE_H} rx={12} fill={colors.bg} stroke={colors.border} strokeWidth={isActive ? 1.5 : 1} />
        <circle cx={pos.x + 18} cy={pos.y + NODE_H / 2} r={4.5} fill={colors.dot} />
        {isActive && <circle cx={pos.x + 18} cy={pos.y + NODE_H / 2} r={7} fill="none" stroke={colors.dot} strokeWidth={1} opacity={0.3}><animate attributeName="r" values="7;11;7" dur="2s" repeatCount="indefinite" /><animate attributeName="opacity" values="0.3;0;0.3" dur="2s" repeatCount="indefinite" /></circle>}
        {isDone && <text x={pos.x + 18} y={pos.y + NODE_H / 2 + 1} fill={colors.dot} fontSize={8} fontWeight={700} textAnchor="middle" dominantBaseline="middle">✓</text>}
        <text x={pos.x + 32} y={pos.y + NODE_H / 2} fill={isActive ? "hsl(45,90%,85%)" : isDone ? "hsl(40,20%,75%)" : "hsl(35,10%,45%)"} fontSize={fontSize} fontWeight={isActive ? 600 : isDone ? 500 : 400} dominantBaseline="middle" letterSpacing="0.01em">{displayLabel}</text>
        {node.statusLabel && isActive && <text x={pos.x + layout.nodeW + 10} y={pos.y + NODE_H / 2} fill="hsl(45,80%,60%)" fontSize={10.5} fontStyle="italic" dominantBaseline="middle" opacity={0.8}>{node.statusLabel}</text>}
        {node.iterations !== undefined && node.iterations > 0 && (
          <g>
            <rect x={pos.x + layout.nodeW - 36} y={pos.y + NODE_H / 2 - 8} width={26} height={16} rx={8} fill={colors.dot} opacity={0.15} />
            <text x={pos.x + layout.nodeW - 23} y={pos.y + NODE_H / 2} fill={colors.dot} fontSize={9} fontWeight={600} textAnchor="middle" dominantBaseline="middle" opacity={0.8}>{node.iterations}{node.maxIterations ? `/${node.maxIterations}` : "×"}</text>
          </g>
        )}
      </g>
    );
  };

  if (nodes.length === 0) {
    const isQueenBusy = queenPhase === "building" || queenPhase === "planning";
    return (
      <div className="flex flex-col h-full">
        <div className="px-5 pt-4 pb-2 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <p className="text-[11px] text-muted-foreground font-medium uppercase tracking-wider">Pipeline</p>
            {version && <span className="text-[10px] font-mono font-medium text-muted-foreground/60 border border-border/30 rounded px-1 py-0.5 leading-none">{version}</span>}
          </div>
          <RunButton runState={runState} disabled={nodes.length === 0 || isQueenBusy} onRun={handleRun} onPause={onPause ?? (() => {})} btnRef={runBtnRef} />
        </div>
        <div className="flex-1 flex items-center justify-center px-5">
          {building ? (
            <div className="flex flex-col items-center gap-3"><Loader2 className="w-6 h-6 animate-spin text-primary/60" /><p className="text-xs text-muted-foreground/80 text-center">Building agent...</p></div>
          ) : (
            <p className="text-xs text-muted-foreground/60 text-center italic">No pipeline configured yet.<br/>Chat with the Queen to get started.</p>
          )}
        </div>
      </div>
    );
  }

  const maxLayer = nodes.length > 0 ? Math.max(...layout.layers) : 0;
  const svgHeight = TOP_Y * 2 + (maxLayer + 1) * NODE_H + maxLayer * GAP_Y + 10;
  
  // Calculate SVG width including back edge offsets
  const maxBackEdgeOffset = backEdges.length > 0 
    ? BACK_EDGE_BASE_OFFSET + (backEdges.length - 1) * BACK_EDGE_INCREMENT + 30
    : 0;
  const svgWidth = Math.max(
    SVG_BASE_W + maxBackEdgeOffset,
    layout.firstColX + layout.maxCols * layout.nodeW + (layout.maxCols - 1) * GAP_X + MARGIN_RIGHT + maxBackEdgeOffset
  );
  
  const transformStyle = { transform: `translate(${viewState.offsetX}px, ${viewState.offsetY}px) scale(${viewState.scale})`, transformOrigin: "0 0", transition: isPanning ? "none" : "transform 0.1s ease", cursor: isPanning ? "grabbing" : "grab" };
  const isQueenBusy = queenPhase === "building" || queenPhase === "planning";

  return (
    <div className="flex flex-col h-full" ref={graphContainerRef}>
      <GraphControls
        scale={viewState.scale}
        onZoomIn={handleZoomIn}
        onZoomOut={handleZoomOut}
        onResetView={handleResetView}
        onExport={(format: string) => { if (format === "png") handleExportPNG(); else handleExportSVG(); }}
        searchActive={showSearch}
        onSearchToggle={() => setShowSearch(!showSearch)}
        searchTerm={searchTerm}
        onSearchChange={handleSearch}
        searchResultCount={searchResults.length}
        currentResultIndex={currentSearchIndex}
        onNextResult={handleNextResult}
        onPrevResult={handlePrevResult}
        onClearSearch={clearSearch}
        title={title}
        version={version}
        building={building}
        isFullscreen={isFullscreen}
        onToggleFullscreen={toggleFullscreen}
        runButton={<RunButton runState={runState} disabled={nodes.length === 0 || isQueenBusy} onRun={handleRun} onPause={onPause ?? (() => {})} btnRef={runBtnRef} />}
      />
      <div ref={svgContainerRef} className="flex-1 overflow-hidden relative" onMouseDown={handlePanStart} onMouseMove={handlePanMove} onMouseUp={handlePanEnd} onMouseLeave={handlePanEnd} onWheel={handleWheel} style={{ cursor: isPanning ? "grabbing" : "grab" }}>
        <div style={transformStyle}>
          <svg ref={svgRef} width={svgWidth} height={svgHeight} viewBox={`0 0 ${svgWidth} ${svgHeight}`} className={`select-none${building ? " opacity-30" : ""}`} style={{ fontFamily: "'Inter', system-ui, sans-serif" }}>
            {forwardEdges.map((e, i) => renderForwardEdge(e, i))}
            {backEdges.map((e, i) => renderBackEdge(e, i))}
            {nodes.map((n, i) => renderNode(n, i))}
          </svg>
        </div>
      </div>
      {building && (
        <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
          <div className="flex flex-col items-center gap-3 bg-background/80 backdrop-blur-sm p-4 rounded-lg">
            <Loader2 className="w-6 h-6 animate-spin text-primary/60" />
            <p className="text-xs text-muted-foreground/80">Rebuilding agent...</p>
          </div>
        </div>
      )}
    </div>
  );
}