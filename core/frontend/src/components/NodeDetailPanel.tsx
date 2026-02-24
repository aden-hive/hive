import { useState, useEffect, useRef } from "react";
import { X, Cpu, Zap, Clock, RotateCcw, CheckCircle2, AlertCircle, Loader2, ChevronDown, ChevronRight, Copy, Check, Terminal, Wrench, BookOpen, GitBranch, Bot } from "lucide-react";
import type { GraphNode, NodeStatus } from "./AgentGraph";
import type { NodeSpec, ToolInfo, NodeCriteria } from "../api/types";
import { graphsApi } from "../api/graphs";
import { logsApi } from "../api/logs";
import ExecutionSubGraph from "./ExecutionSubGraph";

interface Tool {
  name: string;
  description: string;
  icon: string;
  credentials?: ToolCredential[];
}

interface ToolCredential {
  key: string;
  label: string;
  connected: boolean;
  value?: string;
}

interface NodeDetailPanelProps {
  node: GraphNode | null;
  nodeSpec?: NodeSpec | null;
  agentId?: string;
  graphId?: string;
  sessionId?: string | null;
  nodeLogs?: string[];
  onClose: () => void;
}

const statusConfig: Record<NodeStatus, { label: string; color: string; Icon: React.FC<{ className?: string }> }> = {
  running: { label: "Running", color: "hsl(45,95%,58%)", Icon: ({ className }) => <Loader2 className={`${className} animate-spin`} /> },
  looping: { label: "Looping", color: "hsl(38,90%,55%)", Icon: ({ className }) => <RotateCcw className={`${className} animate-spin`} style={{ animationDuration: "2s" }} /> },
  complete: { label: "Complete", color: "hsl(43,70%,45%)", Icon: ({ className }) => <CheckCircle2 className={className} /> },
  pending: { label: "Pending", color: "hsl(220,15%,45%)", Icon: ({ className }) => <Clock className={className} /> },
  error: { label: "Error", color: "hsl(0,65%,55%)", Icon: ({ className }) => <AlertCircle className={className} /> },
};

function formatNodeId(id: string): string {
  return id.split("-").map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(" ");
}

function CredentialRow({ cred }: { cred: ToolCredential }) {
  return (
    <div className="flex items-center justify-between px-3 py-2 rounded-lg bg-background/60 border border-border/30 mt-1.5">
      <div className="flex items-center gap-2 min-w-0">
        <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${cred.connected ? "bg-primary" : "bg-muted-foreground/40"}`} />
        <span className="text-[11px] text-muted-foreground font-medium truncate">{cred.label}</span>
      </div>
      {cred.connected ? (
        <span className="text-[10px] text-primary/80 font-medium flex-shrink-0 ml-2">Connected</span>
      ) : (
        <button className="text-[10px] px-2 py-0.5 rounded-md bg-primary/15 text-primary border border-primary/25 font-semibold hover:bg-primary/25 transition-colors flex-shrink-0 ml-2">
          Connect
        </button>
      )}
    </div>
  );
}

function ToolRow({ tool }: { tool: Tool }) {
  const [expanded, setExpanded] = useState(false);
  const hasCreds = tool.credentials && tool.credentials.length > 0;

  return (
    <div className="rounded-xl border border-border/20 overflow-hidden">
      <button
        onClick={() => hasCreds && setExpanded(v => !v)}
        className={`w-full flex items-start gap-3 p-3 bg-muted/30 hover:bg-muted/50 transition-colors text-left ${!hasCreds ? "cursor-default" : ""}`}
      >
        <span className="text-base leading-none mt-0.5 flex-shrink-0">{tool.icon}</span>
        <div className="min-w-0 flex-1">
          <p className="text-xs font-medium text-foreground">{tool.name}</p>
          <p className="text-[11px] text-muted-foreground mt-0.5 leading-relaxed">{tool.description}</p>
        </div>
        {hasCreds && (
          <span className="flex-shrink-0 mt-0.5">
            {expanded
              ? <ChevronDown className="w-3 h-3 text-muted-foreground" />
              : <ChevronRight className="w-3 h-3 text-muted-foreground" />
            }
          </span>
        )}
      </button>
      {expanded && hasCreds && (
        <div className="px-3 pb-3 bg-muted/20 border-t border-border/15">
          <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider mt-2 mb-1">Credentials</p>
          {tool.credentials!.map(cred => (
            <CredentialRow key={cred.key} cred={cred} />
          ))}
        </div>
      )}
    </div>
  );
}

function LogsTab({ nodeId, isActive: _isActive, agentId, graphId, sessionId, nodeLogs }: { nodeId: string; isActive: boolean; agentId?: string; graphId?: string; sessionId?: string | null; nodeLogs?: string[] }) {
  const [historicalLines, setHistoricalLines] = useState<string[]>([]);
  const bottomRef = useRef<HTMLDivElement>(null);

  // Fetch historical logs when session is available (post-execution viewing)
  useEffect(() => {
    if (agentId && graphId && sessionId) {
      logsApi.nodeLogs(agentId, graphId, nodeId, sessionId)
        .then(r => {
          const realLines: string[] = [];
          if (r.details) {
            for (const d of r.details) {
              realLines.push(`[LOG] ${d.node_name} — ${d.success ? "SUCCESS" : "FAILED"}${d.error ? ` (${d.error})` : ""} — ${d.total_steps} steps`);
            }
          }
          if (r.tool_logs) {
            for (const s of r.tool_logs) {
              realLines.push(`[STEP ${s.step_index}] ${s.llm_text.slice(0, 120)}${s.llm_text.length > 120 ? "..." : ""}`);
            }
          }
          if (realLines.length > 0) {
            setHistoricalLines(realLines);
          }
        })
        .catch(() => { /* keep fallback on error */ });
    }
  }, [agentId, graphId, nodeId, sessionId]);

  // Resolve which lines to display: live SSE logs > historical > default
  const lines = (nodeLogs && nodeLogs.length > 0)
    ? nodeLogs
    : historicalLines.length > 0
      ? historicalLines
      : ["[--:--:--] INFO  Awaiting execution..."];

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [lines]);

  return (
    <div className="flex-1 overflow-auto bg-background/80 rounded-xl border border-border/20 font-mono text-[10.5px] leading-relaxed p-3">
      {lines.map((line, i) => {
        const isWarn = line.includes(" WARN ");
        const isErr = line.includes(" ERROR ");
        const isDebug = line.includes(" DEBUG ");
        return (
          <div
            key={i}
            className={isErr ? "text-red-400" : isWarn ? "text-yellow-400/80" : isDebug ? "text-muted-foreground/50" : "text-green-400/70"}
          >
            {line}
          </div>
        );
      })}
      <div ref={bottomRef} />
    </div>
  );
}

function SystemPromptTab({ systemPrompt }: { systemPrompt?: string }) {
  const prompt = systemPrompt || "";
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    navigator.clipboard.writeText(prompt);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  if (!prompt) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <p className="text-xs text-muted-foreground/60 italic text-center">No system prompt configured</p>
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-auto flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">System Prompt</p>
        <button
          onClick={handleCopy}
          className="flex items-center gap-1 text-[10px] text-muted-foreground hover:text-foreground transition-colors"
        >
          {copied ? <Check className="w-3 h-3 text-primary" /> : <Copy className="w-3 h-3" />}
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <textarea
        readOnly
        value={prompt}
        className="flex-1 min-h-[240px] w-full rounded-xl bg-muted/30 border border-border/20 text-[11px] text-muted-foreground leading-relaxed p-3 font-mono resize-none focus:outline-none focus:border-border/40"
      />
    </div>
  );
}

function SubagentsTab() {
  return (
    <div className="flex-1 flex items-center justify-center">
      <p className="text-xs text-muted-foreground/60 italic text-center">No subagents assigned to this node.</p>
    </div>
  );
}

type Tab = "overview" | "tools" | "logs" | "prompt" | "subagents";

const tabs: { id: Tab; label: string; Icon: React.FC<{ className?: string }> }[] = [
  { id: "overview", label: "Overview", Icon: ({ className }) => <GitBranch className={className} /> },
  { id: "tools", label: "Tools", Icon: ({ className }) => <Wrench className={className} /> },
  { id: "logs", label: "Logs", Icon: ({ className }) => <Terminal className={className} /> },
  { id: "prompt", label: "Prompt", Icon: ({ className }) => <BookOpen className={className} /> },
  { id: "subagents", label: "Subagents", Icon: ({ className }) => <Bot className={className} /> },
];

export default function NodeDetailPanel({ node, nodeSpec, agentId, graphId, sessionId, nodeLogs, onClose }: NodeDetailPanelProps) {
  const [activeTab, setActiveTab] = useState<Tab>("overview");
  const [realTools, setRealTools] = useState<ToolInfo[] | null>(null);
  const [realCriteria, setRealCriteria] = useState<NodeCriteria | null>(null);

  useEffect(() => {
    setActiveTab("overview");
    setRealTools(null);
    setRealCriteria(null);
  }, [node?.id]);

  // Fetch real tool descriptions when Tools tab is active and agent is loaded
  useEffect(() => {
    if (activeTab === "tools" && agentId && graphId && node) {
      graphsApi.nodeTools(agentId, graphId, node.id)
        .then(r => setRealTools(r.tools))
        .catch(() => setRealTools(null));
    }
  }, [activeTab, agentId, graphId, node?.id]);

  // Fetch real criteria when Overview tab is active and agent is loaded
  useEffect(() => {
    if (activeTab === "overview" && agentId && graphId && node) {
      graphsApi.nodeCriteria(agentId, graphId, node.id, sessionId || undefined)
        .then(r => setRealCriteria(r))
        .catch(() => setRealCriteria(null));
    }
  }, [activeTab, agentId, graphId, node?.id, sessionId]);

  if (!node) return null;

  const status = statusConfig[node.status];
  const StatusIcon = status.Icon;
  const isActive = node.status === "running" || node.status === "looping";

  return (
    <div className="flex flex-col h-full border-l border-border/40 bg-card/20 animate-in slide-in-from-right">
      {/* Header */}
      <div className="px-4 pt-4 pb-3 border-b border-border/30 flex items-start justify-between gap-2 flex-shrink-0">
        <div className="flex items-start gap-3 min-w-0">
          <div
            className="w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0 mt-0.5"
            style={{ backgroundColor: `${status.color}18`, border: `1.5px solid ${status.color}35` }}
          >
            <Cpu className="w-3.5 h-3.5" style={{ color: status.color }} />
          </div>
          <div className="min-w-0">
            <h3 className="text-sm font-semibold text-foreground leading-tight">{formatNodeId(node.id)}</h3>
            <div className="flex items-center gap-1.5 mt-1">
              <span style={{ color: status.color }}><StatusIcon className="w-3 h-3 flex-shrink-0" /></span>
              <span className="text-[11px] font-medium" style={{ color: status.color }}>{status.label}</span>
              {node.iterations !== undefined && node.iterations > 0 && (
                <>
                  <span className="text-muted-foreground/40 text-[10px]">&middot;</span>
                  <span className="text-[11px] text-muted-foreground">
                    {node.iterations}{node.maxIterations ? `/${node.maxIterations}` : ""} iterations
                  </span>
                </>
              )}
            </div>
          </div>
        </div>
        <button
          onClick={onClose}
          className="p-1 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors flex-shrink-0"
        >
          <X className="w-3.5 h-3.5" />
        </button>
      </div>

      {/* Status label */}
      {node.statusLabel && (
        <div className="px-4 py-2 border-b border-border/20 flex-shrink-0">
          <div className="flex items-center gap-2 text-[11px] text-muted-foreground bg-muted/40 rounded-lg px-3 py-2">
            <Zap className="w-3 h-3 text-primary flex-shrink-0" />
            <span className="italic">{node.statusLabel}</span>
          </div>
        </div>
      )}

      {/* Tab bar */}
      <div className="flex border-b border-border/30 flex-shrink-0 px-2 pt-1 overflow-x-auto scrollbar-hide">
        {tabs.map(tab => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`flex items-center gap-1.5 px-3 py-2 text-[11px] font-medium border-b-2 transition-colors -mb-px ${
              activeTab === tab.id
                ? "border-primary text-primary"
                : "border-transparent text-muted-foreground hover:text-foreground"
            }`}
          >
            <tab.Icon className="w-3 h-3" />
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="flex-1 overflow-auto px-4 py-4 flex flex-col gap-3">
        {activeTab === "overview" && (
          <>
            <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">Internal Steps</p>
            {nodeSpec?.subgraph_steps?.length ? (
              <ExecutionSubGraph steps={nodeSpec.subgraph_steps} status={node.status} />
            ) : (
              <div className="flex items-center justify-center py-6">
                <p className="text-[11px] text-muted-foreground/50 italic">No workflow steps extracted</p>
              </div>
            )}
            {(() => {
              if (realCriteria && realCriteria.success_criteria) {
                const criteriaLines = realCriteria.success_criteria.split("\n").filter(l => l.trim());
                const passed = realCriteria.last_execution?.success ?? null;
                return (
                  <div className="mt-1">
                    <div className="flex items-center justify-between mb-2">
                      <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">Judge Criteria</p>
                      {passed !== null && (
                        <span className={`text-[10px] font-medium px-2 py-0.5 rounded-full ${passed ? "bg-[hsl(43,70%,45%)]/15 text-[hsl(43,70%,45%)]" : "bg-red-500/15 text-red-400"}`}>
                          {passed ? "Passed" : "Failed"}
                        </span>
                      )}
                    </div>
                    <div className="flex flex-col gap-1.5">
                      {criteriaLines.map((line, i) => (
                        <div key={i} className="flex items-start gap-2">
                          <div className={`mt-0.5 w-3.5 h-3.5 rounded-full flex-shrink-0 flex items-center justify-center border ${passed ? "border-transparent bg-[hsl(43,70%,45%)]" : "border-border/40 bg-muted/30"}`}>
                            {passed && (
                              <svg viewBox="0 0 8 8" className="w-2 h-2" fill="none">
                                <path d="M1.5 4l2 2 3-3" stroke="white" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round"/>
                              </svg>
                            )}
                          </div>
                          <span className={`text-[11px] leading-relaxed ${passed ? "text-foreground/70" : "text-foreground/80"}`}>{line}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                );
              }
              return null;
            })()}
            {node.next && node.next.length > 0 && (
              <div className="mt-2">
                <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider mb-2">Sends to</p>
                <div className="flex flex-wrap gap-1.5">
                  {node.next.map((n) => (
                    <span key={n} className="text-[11px] px-2.5 py-1 rounded-full bg-primary/10 text-primary border border-primary/20 font-medium">
                      {formatNodeId(n)}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </>
        )}

        {activeTab === "tools" && (
          <div className="space-y-2">
            <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider mb-1">Tools & Integrations</p>
            {realTools && realTools.length > 0
              ? realTools.map((t, i) => (
                  <ToolRow key={i} tool={{ name: t.name, description: t.description || "No description available", icon: "\ud83d\udd27" }} />
                ))
              : (
                <div className="flex items-center justify-center py-6">
                  <p className="text-[11px] text-muted-foreground/50 italic">No tools available</p>
                </div>
              )
            }
          </div>
        )}

        {activeTab === "logs" && (
          <LogsTab nodeId={node.id} isActive={isActive} agentId={agentId} graphId={graphId} sessionId={sessionId} nodeLogs={nodeLogs} />
        )}

        {activeTab === "prompt" && (
          <SystemPromptTab systemPrompt={nodeSpec?.system_prompt} />
        )}

        {activeTab === "subagents" && (
          <SubagentsTab />
        )}
      </div>
    </div>
  );
}
