import { useMemo, useState, useRef, useEffect } from "react";
import ReactDOM from "react-dom";
import { Play, Loader2, CheckCircle2, GitBranch, Zap, Layers } from "lucide-react";

export type NodeStatus = "running" | "complete" | "pending" | "error" | "looping";

export interface GraphNode {
  id: string;
  label: string;
  status: NodeStatus;
  next?: string[];
  backEdges?: string[];
  iterations?: number;
  maxIterations?: number;
  statusLabel?: string;
}

type RunState = "idle" | "deploying" | "running";
type VersionBump = "major" | "minor";

interface AgentGraphProps {
  nodes: GraphNode[];
  title: string;
  onNodeClick?: (node: GraphNode) => void;
  onVersionBump?: (type: VersionBump) => void;
  version?: string;
}

const NODE_W = 180;
const NODE_H = 44;
const GAP_Y = 48;
const LEFT_X = 40;
const TOP_Y = 30;

// Unified amber/gold palette
const statusColors: Record<NodeStatus, { dot: string; bg: string; border: string; glow: string }> = {
  running: {
    dot: "hsl(45,95%,58%)",
    bg: "hsl(45,95%,58%,0.08)",
    border: "hsl(45,95%,58%,0.5)",
    glow: "hsl(45,95%,58%,0.15)",
  },
  looping: {
    dot: "hsl(38,90%,55%)",
    bg: "hsl(38,90%,55%,0.08)",
    border: "hsl(38,90%,55%,0.5)",
    glow: "hsl(38,90%,55%,0.15)",
  },
  complete: {
    dot: "hsl(43,70%,45%)",
    bg: "hsl(43,70%,45%,0.05)",
    border: "hsl(43,70%,45%,0.25)",
    glow: "none",
  },
  pending: {
    dot: "hsl(35,15%,28%)",
    bg: "hsl(35,10%,12%)",
    border: "hsl(35,10%,20%)",
    glow: "none",
  },
  error: {
    dot: "hsl(0,65%,55%)",
    bg: "hsl(0,65%,55%,0.06)",
    border: "hsl(0,65%,55%,0.3)",
    glow: "hsl(0,65%,55%,0.1)",
  },
};

function formatLabel(id: string): string {
  return id
    .split("-")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

export default function AgentGraph({ nodes, title, onNodeClick, onVersionBump, version }: AgentGraphProps) {
  const [runState, setRunState] = useState<RunState>("idle");
  const [versionPopover, setVersionPopover] = useState<"hidden" | "confirm" | "pick">("hidden");
  const [popoverPos, setPopoverPos] = useState<{ top: number; left: number } | null>(null);
  const runBtnRef = useRef<HTMLButtonElement>(null);
  const popoverRef = useRef<HTMLDivElement>(null);

  // Close popover on outside click
  useEffect(() => {
    if (versionPopover === "hidden") return;
    const handler = (e: MouseEvent) => {
      if (
        popoverRef.current && !popoverRef.current.contains(e.target as Node) &&
        runBtnRef.current && !runBtnRef.current.contains(e.target as Node)
      ) setVersionPopover("hidden");
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [versionPopover]);

  const handleRun = () => {
    if (runState !== "idle") return;
    if (runBtnRef.current) {
      const rect = runBtnRef.current.getBoundingClientRect();
      setPopoverPos({ top: rect.bottom + 6, left: rect.right });
    }
    setVersionPopover("confirm");
  };

  const startRun = () => {
    setVersionPopover("hidden");
    setRunState("deploying");
    setTimeout(() => setRunState("running"), 1800);
    setTimeout(() => setRunState("idle"), 5000);
  };

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
    const edges: { fromIdx: number; toIdx: number }[] = [];
    nodes.forEach((n, i) => {
      (n.next || []).forEach((toId) => {
        const toIdx = idxMap[toId];
        if (toIdx !== undefined && toIdx > i) edges.push({ fromIdx: i, toIdx });
      });
    });
    return edges;
  }, [nodes, idxMap]);

  const RunButton = () => (
    <button
      ref={runBtnRef}
      onClick={handleRun}
      disabled={runState !== "idle" || nodes.length === 0}
      className={`flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[11px] font-semibold transition-all duration-200 ${
        runState === "running"
          ? "bg-green-500/15 text-green-400 border border-green-500/30 cursor-default"
          : runState === "deploying"
          ? "bg-primary/10 text-primary border border-primary/20 cursor-default"
          : nodes.length === 0
          ? "bg-muted/30 text-muted-foreground/40 border border-border/20 cursor-not-allowed"
          : "bg-primary/10 text-primary border border-primary/20 hover:bg-primary/20 hover:border-primary/40 active:scale-95"
      }`}
    >
      {runState === "deploying" ? (
        <Loader2 className="w-3 h-3 animate-spin" />
      ) : runState === "running" ? (
        <CheckCircle2 className="w-3 h-3" />
      ) : (
        <Play className="w-3 h-3 fill-current" />
      )}
      {runState === "deploying" ? "Deploying\u2026" : runState === "running" ? "Running" : "Run"}
    </button>
  );

  // Version bump popover (portalled)
  const VersionPopover = () => {
    if (versionPopover === "hidden" || !popoverPos) return null;
    return ReactDOM.createPortal(
      <div
        ref={popoverRef}
        style={{ position: "fixed", top: popoverPos.top, right: window.innerWidth - popoverPos.left, zIndex: 9999 }}
        className="w-64 rounded-xl border border-border/60 bg-card shadow-xl shadow-black/30 overflow-hidden"
      >
        {versionPopover === "confirm" && (
          <>
            <div className="px-3.5 py-3 border-b border-border/40">
              <div className="flex items-center gap-2 mb-1">
                <GitBranch className="w-3.5 h-3.5 text-primary" />
                <span className="text-xs font-semibold text-foreground">Changes Detected</span>
              </div>
              <p className="text-[11px] text-muted-foreground leading-relaxed">
                The pipeline has been modified since the last run. Would you like to save this as a new version?
              </p>
            </div>
            <div className="p-1.5 flex flex-col gap-0.5">
              <button
                onClick={() => setVersionPopover("pick")}
                className="flex items-center gap-2.5 w-full px-3 py-2 rounded-lg text-sm text-left transition-colors hover:bg-muted/60 text-foreground font-medium"
              >
                Yes, create new version
              </button>
              <button
                onClick={startRun}
                className="flex items-center gap-2.5 w-full px-3 py-2 rounded-lg text-sm text-left transition-colors hover:bg-muted/60 text-muted-foreground"
              >
                No, run as-is
              </button>
            </div>
          </>
        )}
        {versionPopover === "pick" && (
          <>
            <div className="px-3.5 py-3 border-b border-border/40">
              <span className="text-xs font-semibold text-foreground">Select Change Type</span>
              {version && (
                <p className="text-[11px] text-muted-foreground mt-0.5">Current version: <span className="text-foreground font-medium">{version}</span></p>
              )}
            </div>
            <div className="p-1.5 flex flex-col gap-0.5">
              <button
                onClick={() => { onVersionBump?.("major"); startRun(); }}
                className="flex items-center gap-2.5 w-full px-3 py-2 rounded-lg text-left transition-colors hover:bg-muted/60"
              >
                <div className="w-7 h-7 rounded-md bg-primary/10 flex items-center justify-center flex-shrink-0">
                  <Zap className="w-3.5 h-3.5 text-primary" />
                </div>
                <div>
                  <div className="text-sm font-medium text-foreground">Major change</div>
                  <div className="text-[11px] text-muted-foreground">Resets minor (e.g. v2.3 &rarr; v3.0)</div>
                </div>
              </button>
              <button
                onClick={() => { onVersionBump?.("minor"); startRun(); }}
                className="flex items-center gap-2.5 w-full px-3 py-2 rounded-lg text-left transition-colors hover:bg-muted/60"
              >
                <div className="w-7 h-7 rounded-md bg-muted/60 flex items-center justify-center flex-shrink-0">
                  <Layers className="w-3.5 h-3.5 text-muted-foreground" />
                </div>
                <div>
                  <div className="text-sm font-medium text-foreground">Minor change</div>
                  <div className="text-[11px] text-muted-foreground">Increments patch (e.g. v2.3 &rarr; v2.4)</div>
                </div>
              </button>
            </div>
          </>
        )}
      </div>,
      document.body
    );
  };

  if (nodes.length === 0) {
    return (
      <div className="flex flex-col h-full">
        <div className="px-5 pt-4 pb-2 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <p className="text-[11px] text-muted-foreground font-medium uppercase tracking-wider">Pipeline</p>
            {version && (
              <span className="text-[10px] font-mono font-medium text-muted-foreground/60 border border-border/30 rounded px-1 py-0.5 leading-none">
                {version}
              </span>
            )}
          </div>
          <RunButton />
        </div>
        <VersionPopover />
        <div className="flex-1 flex items-center justify-center px-5">
          <p className="text-xs text-muted-foreground/60 text-center italic">No pipeline configured yet.<br/>Chat with the Queen to get started.</p>
        </div>
      </div>
    );
  }

  const nodePos = (i: number) => ({
    x: LEFT_X,
    y: TOP_Y + i * (NODE_H + GAP_Y),
  });

  const svgHeight = TOP_Y * 2 + nodes.length * NODE_H + (nodes.length - 1) * GAP_Y + 10;

  const renderForwardEdge = (edge: { fromIdx: number; toIdx: number }, i: number) => {
    const from = nodePos(edge.fromIdx);
    const to = nodePos(edge.toIdx);
    const x = from.x + NODE_W / 2;
    const y1 = from.y + NODE_H;
    const y2 = to.y;
    const midY = (y1 + y2) / 2;

    const fromNode = nodes[edge.fromIdx];
    const isActive = fromNode.status === "complete" || fromNode.status === "running" || fromNode.status === "looping";

    return (
      <g key={`fwd-${i}`}>
        <path
          d={`M ${x} ${y1} C ${x} ${midY}, ${x} ${midY}, ${x} ${y2}`}
          fill="none"
          stroke={isActive ? "hsl(43,70%,45%,0.35)" : "hsl(35,10%,20%)"}
          strokeWidth={1.5}
        />
        <polygon
          points={`${x - 4},${y2 - 6} ${x + 4},${y2 - 6} ${x},${y2 - 1}`}
          fill={isActive ? "hsl(43,70%,45%,0.5)" : "hsl(35,10%,22%)"}
        />
      </g>
    );
  };

  const renderBackEdge = (edge: { fromIdx: number; toIdx: number }, i: number) => {
    const from = nodePos(edge.fromIdx);
    const to = nodePos(edge.toIdx);

    const rightOffset = NODE_W + 28 + i * 18;
    const startX = from.x + NODE_W;
    const startY = from.y + NODE_H / 2;
    const endX = to.x + NODE_W;
    const endY = to.y + NODE_H / 2;
    const curveX = from.x + rightOffset;
    const r = 12;

    const fromNode = nodes[edge.fromIdx];
    const isActive = fromNode.status === "complete" || fromNode.status === "running" || fromNode.status === "looping";
    const color = isActive ? "hsl(38,80%,50%,0.3)" : "hsl(35,10%,20%)";

    // Bezier curve with rounded corners
    const path = `M ${startX} ${startY} C ${startX + r} ${startY}, ${curveX} ${startY}, ${curveX} ${startY - r} L ${curveX} ${endY + r} C ${curveX} ${endY}, ${endX + r} ${endY}, ${endX + 6} ${endY}`;

    return (
      <g key={`back-${i}`}>
        <path d={path} fill="none" stroke={color} strokeWidth={1.5} strokeDasharray="4 3" />
        <polygon
          points={`${endX + 6},${endY - 3} ${endX + 6},${endY + 3} ${endX},${endY}`}
          fill={isActive ? "hsl(38,80%,50%,0.45)" : "hsl(35,10%,22%)"}
        />
      </g>
    );
  };

  const renderNode = (node: GraphNode, i: number) => {
    const pos = nodePos(i);
    const isActive = node.status === "running" || node.status === "looping";
    const isDone = node.status === "complete";
    const colors = statusColors[node.status];

    return (
      <g key={node.id} onClick={() => onNodeClick?.(node)} style={{ cursor: onNodeClick ? "pointer" : "default" }}>
        {/* Ambient glow for active nodes */}
        {isActive && (
          <>
            <rect
              x={pos.x - 4} y={pos.y - 4}
              width={NODE_W + 8} height={NODE_H + 8}
              rx={16} fill={colors.glow}
            />
            <rect
              x={pos.x - 2} y={pos.y - 2}
              width={NODE_W + 4} height={NODE_H + 4}
              rx={14} fill="none" stroke={colors.dot} strokeWidth={1} opacity={0.25}
              style={{ animation: "pulse-ring 2.5s ease-out infinite" }}
            />
          </>
        )}

        {/* Node background */}
        <rect
          x={pos.x} y={pos.y}
          width={NODE_W} height={NODE_H}
          rx={12}
          fill={colors.bg}
          stroke={colors.border}
          strokeWidth={isActive ? 1.5 : 1}
        />

        {/* Status dot */}
        <circle cx={pos.x + 18} cy={pos.y + NODE_H / 2} r={4.5} fill={colors.dot} />
        {isActive && (
          <circle cx={pos.x + 18} cy={pos.y + NODE_H / 2} r={7} fill="none" stroke={colors.dot} strokeWidth={1} opacity={0.3}>
            <animate attributeName="r" values="7;11;7" dur="2s" repeatCount="indefinite" />
            <animate attributeName="opacity" values="0.3;0;0.3" dur="2s" repeatCount="indefinite" />
          </circle>
        )}

        {/* Check mark for complete */}
        {isDone && (
          <text
            x={pos.x + 18} y={pos.y + NODE_H / 2 + 1}
            fill={colors.dot} fontSize={8} fontWeight={700}
            textAnchor="middle" dominantBaseline="middle"
          >
            &#x2713;
          </text>
        )}

        {/* Label -- properly capitalized */}
        <text
          x={pos.x + 32} y={pos.y + NODE_H / 2}
          fill={isActive ? "hsl(45,90%,85%)" : isDone ? "hsl(40,20%,75%)" : "hsl(35,10%,45%)"}
          fontSize={12.5}
          fontWeight={isActive ? 600 : isDone ? 500 : 400}
          dominantBaseline="middle"
          letterSpacing="0.01em"
        >
          {formatLabel(node.id)}
        </text>

        {/* Status label for active nodes */}
        {node.statusLabel && isActive && (
          <text
            x={pos.x + NODE_W + 10} y={pos.y + NODE_H / 2}
            fill="hsl(45,80%,60%)" fontSize={10.5} fontStyle="italic"
            dominantBaseline="middle" opacity={0.8}
          >
            {node.statusLabel}
          </text>
        )}

        {/* Iteration badge */}
        {node.iterations !== undefined && node.iterations > 0 && (
          <g>
            <rect
              x={pos.x + NODE_W - 36} y={pos.y + NODE_H / 2 - 8}
              width={26} height={16} rx={8}
              fill={colors.dot} opacity={0.15}
            />
            <text
              x={pos.x + NODE_W - 23} y={pos.y + NODE_H / 2}
              fill={colors.dot} fontSize={9} fontWeight={600}
              textAnchor="middle" dominantBaseline="middle" opacity={0.8}
            >
              {node.iterations}{node.maxIterations ? `/${node.maxIterations}` : "\u00d7"}
            </text>
          </g>
        )}
      </g>
    );
  };

  const _runningNode = nodes.find((n) => n.status === "running" || n.status === "looping");
  const _formattedTitle = title.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  // Suppress unused warnings — these are available for future use
  void _runningNode;
  void _formattedTitle;

  return (
    <div className="flex flex-col h-full">
      {/* Compact sub-label */}
      <div className="px-5 pt-4 pb-2 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <p className="text-[11px] text-muted-foreground font-medium uppercase tracking-wider">Pipeline</p>
          {version && (
            <span className="text-[10px] font-mono font-medium text-muted-foreground/60 border border-border/30 rounded px-1 py-0.5 leading-none">
              {version}
            </span>
          )}
        </div>
        <RunButton />
      </div>
      <VersionPopover />

      {/* Graph */}
      <div className="flex-1 overflow-auto px-3 pb-5">
        <svg
          width={LEFT_X + NODE_W + 100}
          height={svgHeight}
          viewBox={`0 0 ${LEFT_X + NODE_W + 100} ${svgHeight}`}
          className="select-none"
          style={{ fontFamily: "'Inter', system-ui, sans-serif" }}
        >
          {forwardEdges.map((e, i) => renderForwardEdge(e, i))}
          {backEdges.map((e, i) => renderBackEdge(e, i))}
          {nodes.map((n, i) => renderNode(n, i))}
        </svg>
      </div>
    </div>
  );
}
