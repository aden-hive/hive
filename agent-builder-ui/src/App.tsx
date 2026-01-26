import { useCallback, useState } from 'react';
import {
  ReactFlow,
  Background,
  BackgroundVariant,
  ReactFlowProvider,
  Handle,
  Position,
  addEdge,
  applyNodeChanges,
  applyEdgeChanges,
  BaseEdge,
  EdgeLabelRenderer,
  getSmoothStepPath,
  useReactFlow,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { Brain, Wrench, GitBranch, Code, Download, Trash2, X, Copy, Check, Play, Plus, Loader2, Search, MessageSquare, ArrowRight, HelpCircle, Info, ChevronRight, ChevronDown, Layers, BookOpen, Zap, FileCode, Edit3, Flag, CircleDot, Eye, EyeOff, Key, Cpu, AlertTriangle, ZoomIn, ZoomOut, Maximize2 } from 'lucide-react';
import Prism from 'prismjs';
import 'prismjs/components/prism-python';
import 'prismjs/themes/prism-tomorrow.css';

type NodeType = 'llm_generate' | 'llm_tool_use' | 'router' | 'function';

interface NodeData {
  label: string;
  nodeType: NodeType;
  description: string;
  inputKeys: string[];
  outputKeys: string[];
  systemPrompt: string;
  tools: string[];
  isEntry?: boolean;
  isTerminal?: boolean;
  testOutput?: any;
  testStatus?: 'idle' | 'running' | 'success' | 'error';
}

const TOOLS = [
  { id: 'web_scrape', name: 'web_scrape', desc: 'Fetch content from a URL' },
  { id: 'web_search', name: 'web_search', desc: 'Search the web via DuckDuckGo' },
  { id: 'pdf_read', name: 'pdf_read', desc: 'Extract text from PDF files' },
  { id: 'view_file', name: 'view_file', desc: 'Read a local file' },
  { id: 'write_to_file', name: 'write_to_file', desc: 'Write content to a file' },
  { id: 'list_dir', name: 'list_dir', desc: 'List directory contents' },
  { id: 'grep_search', name: 'grep_search', desc: 'Search for text patterns' },
];

const nodeConfig: Record<NodeType, {
  icon: typeof Brain;
  color: string;
  label: string;
  shortDesc: string;
  fullDesc: string;
  example: string;
  useWhen: string;
}> = {
  llm_generate: {
    icon: Brain,
    color: '#7c3aed',
    label: 'LLM Node',
    shortDesc: 'AI thinking & reasoning',
    fullDesc: 'Uses AI (like GPT/Gemini) to analyze text, make decisions, or generate content. This is pure AI reasoning - no external tools.',
    example: 'Summarize a document, classify sentiment, extract key points, generate a response',
    useWhen: 'You need the AI to think, analyze, or generate text without calling external services',
  },
  llm_tool_use: {
    icon: Wrench,
    color: '#2563eb',
    label: 'Tool Node',
    shortDesc: 'AI + external tools',
    fullDesc: 'AI decides which tools to call (web search, file read, etc.) and uses the results. Combines AI reasoning with real-world actions.',
    example: 'Search the web for information, read a PDF, fetch data from a URL',
    useWhen: 'You need to fetch external data, interact with files, or call APIs',
  },
  router: {
    icon: GitBranch,
    color: '#ea580c',
    label: 'Router',
    shortDesc: 'Conditional branching',
    fullDesc: 'Routes the flow to different nodes based on conditions. Like an if/else statement - checks data and decides which path to take.',
    example: 'If urgency is "high" go to fast-track, else go to normal queue',
    useWhen: 'You need different paths based on previous outputs (e.g., handle errors differently)',
  },
  function: {
    icon: Code,
    color: '#16a34a',
    label: 'Function',
    shortDesc: 'Custom Python code',
    fullDesc: 'Runs custom Python code for data transformation, calculations, or integrations. No AI involved - just deterministic code.',
    example: 'Parse JSON, calculate totals, format dates, call a custom API',
    useWhen: 'You need precise logic, math, or custom integrations that AI shouldn\'t handle',
  },
};

function AgentNode({ data, selected }: { data: NodeData & { hasMissingInputs?: boolean }; selected?: boolean }) {
  const cfg = nodeConfig[data.nodeType];
  const Icon = cfg.icon;
  const borderColor = data.hasMissingInputs ? '#f59e0b' : (selected ? cfg.color : '#d1d5db');

  return (
    <div style={{
      background: '#ffffff',
      border: `2px solid ${borderColor}`,
      borderRadius: 8,
      width: 180,
      boxShadow: selected ? `0 0 0 3px ${cfg.color}20` : data.hasMissingInputs ? '0 0 0 2px #fef08a' : '0 1px 3px rgba(0,0,0,0.1)',
      fontFamily: 'system-ui, -apple-system, sans-serif',
      position: 'relative',
    }}>
      {data.hasMissingInputs && (
        <div style={{
          position: 'absolute',
          top: -8,
          right: -8,
          width: 20,
          height: 20,
          borderRadius: 10,
          background: '#f59e0b',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          boxShadow: '0 1px 3px rgba(0,0,0,0.2)',
        }} title="Missing input keys from connected nodes">
          <AlertTriangle size={12} color="#fff" />
        </div>
      )}
      <div style={{
        padding: '10px 12px',
        background: '#f8fafc',
        borderBottom: '1px solid #e2e8f0',
        borderRadius: '6px 6px 0 0',
        display: 'flex',
        alignItems: 'center',
        gap: 8,
      }}>
        <Icon size={16} color={cfg.color} />
        <span style={{ fontSize: 14, fontWeight: 600, color: '#1e293b', flex: 1 }}>{data.label}</span>
        {data.isEntry && <span style={{ fontSize: 10, background: '#22c55e', color: '#fff', padding: '2px 6px', borderRadius: 4, fontWeight: 600 }}>START</span>}
        {data.isTerminal && <span style={{ fontSize: 10, background: '#ef4444', color: '#fff', padding: '2px 6px', borderRadius: 4, fontWeight: 600 }}>END</span>}
      </div>
      <div style={{ padding: '8px 12px' }}>
        <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
          {data.inputKeys.map(k => (
            <span key={k} style={{ fontSize: 11, background: '#dbeafe', color: '#1e40af', padding: '2px 6px', borderRadius: 4 }}>{k}</span>
          ))}
          {data.outputKeys.map(k => (
            <span key={k} style={{ fontSize: 11, background: '#dcfce7', color: '#166534', padding: '2px 6px', borderRadius: 4 }}>{k}</span>
          ))}
        </div>
        {data.testStatus && data.testStatus !== 'idle' && (
          <div style={{ marginTop: 8, display: 'flex', alignItems: 'center', gap: 6 }}>
            <div style={{
              width: 8, height: 8, borderRadius: 4,
              background: data.testStatus === 'success' ? '#22c55e' : data.testStatus === 'error' ? '#ef4444' : '#f59e0b'
            }} />
            <span style={{ fontSize: 11, color: '#64748b' }}>
              {data.testStatus === 'running' ? 'Testing...' : data.testStatus === 'success' ? 'Passed' : 'Failed'}
            </span>
          </div>
        )}
      </div>
      <Handle type="target" position={Position.Left} style={{ background: '#64748b', width: 10, height: 10, border: '2px solid #fff' }} />
      <Handle type="source" position={Position.Right} style={{ background: '#64748b', width: 10, height: 10, border: '2px solid #fff' }} />
    </div>
  );
}

// Custom edge component showing data flow keys
function DataFlowEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  data,
  style,
}: any) {
  const [edgePath, labelX, labelY] = getSmoothStepPath({
    sourceX,
    sourceY,
    sourcePosition,
    targetX,
    targetY,
    targetPosition,
  });

  const matchingKeys: string[] = data?.matchingKeys || [];
  const hasWarning = data?.hasWarning || false;

  return (
    <>
      <BaseEdge
        id={id}
        path={edgePath}
        style={{
          ...style,
          stroke: hasWarning ? '#f59e0b' : '#64748b',
          strokeWidth: 2,
          strokeDasharray: hasWarning ? '5,5' : undefined,
        }}
      />
      {matchingKeys.length > 0 && (
        <EdgeLabelRenderer>
          <div
            style={{
              position: 'absolute',
              transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`,
              pointerEvents: 'none',
              display: 'flex',
              gap: 4,
              background: '#fff',
              padding: '4px 8px',
              borderRadius: 12,
              boxShadow: '0 1px 4px rgba(0,0,0,0.1)',
              border: '1px solid #e2e8f0',
            }}
          >
            {matchingKeys.slice(0, 3).map((key: string) => (
              <span
                key={key}
                style={{
                  fontSize: 10,
                  fontWeight: 600,
                  color: '#166534',
                  background: '#dcfce7',
                  padding: '2px 6px',
                  borderRadius: 4,
                }}
              >
                {key}
              </span>
            ))}
            {matchingKeys.length > 3 && (
              <span style={{ fontSize: 10, color: '#64748b' }}>+{matchingKeys.length - 3}</span>
            )}
          </div>
        </EdgeLabelRenderer>
      )}
      {hasWarning && matchingKeys.length === 0 && (
        <EdgeLabelRenderer>
          <div
            style={{
              position: 'absolute',
              transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`,
              pointerEvents: 'none',
              display: 'flex',
              alignItems: 'center',
              gap: 4,
              background: '#fffbeb',
              padding: '4px 8px',
              borderRadius: 12,
              boxShadow: '0 1px 4px rgba(0,0,0,0.1)',
              border: '1px solid #fef08a',
            }}
          >
            <AlertTriangle size={12} color="#f59e0b" />
            <span style={{ fontSize: 10, fontWeight: 600, color: '#92400e' }}>No matching keys</span>
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  );
}

const nodeTypes = { agentNode: AgentNode };
const edgeTypes = { dataFlow: DataFlowEdge };

// Custom zoom controls component
function CustomControls() {
  const { zoomIn, zoomOut, fitView } = useReactFlow();

  const btnStyle: React.CSSProperties = {
    width: 36,
    height: 36,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    background: '#fff',
    border: 'none',
    cursor: 'pointer',
    color: '#64748b',
    transition: 'all 0.15s',
  };

  return (
    <div style={{
      position: 'absolute',
      bottom: 20,
      left: 20,
      display: 'flex',
      flexDirection: 'column',
      background: '#fff',
      borderRadius: 10,
      boxShadow: '0 2px 8px rgba(0,0,0,0.08)',
      border: '1px solid #e2e8f0',
      overflow: 'hidden',
      zIndex: 10,
    }}>
      <button
        onClick={() => zoomIn()}
        style={{ ...btnStyle, borderBottom: '1px solid #e2e8f0' }}
        onMouseEnter={e => { e.currentTarget.style.background = '#f8fafc'; e.currentTarget.style.color = '#0f172a'; }}
        onMouseLeave={e => { e.currentTarget.style.background = '#fff'; e.currentTarget.style.color = '#64748b'; }}
        title="Zoom in"
      >
        <ZoomIn size={18} />
      </button>
      <button
        onClick={() => zoomOut()}
        style={{ ...btnStyle, borderBottom: '1px solid #e2e8f0' }}
        onMouseEnter={e => { e.currentTarget.style.background = '#f8fafc'; e.currentTarget.style.color = '#0f172a'; }}
        onMouseLeave={e => { e.currentTarget.style.background = '#fff'; e.currentTarget.style.color = '#64748b'; }}
        title="Zoom out"
      >
        <ZoomOut size={18} />
      </button>
      <button
        onClick={() => fitView({ padding: 0.2 })}
        style={btnStyle}
        onMouseEnter={e => { e.currentTarget.style.background = '#f8fafc'; e.currentTarget.style.color = '#0f172a'; }}
        onMouseLeave={e => { e.currentTarget.style.background = '#fff'; e.currentTarget.style.color = '#64748b'; }}
        title="Fit to view"
      >
        <Maximize2 size={18} />
      </button>
    </div>
  );
}

const TEMPLATES = {
  research: {
    name: 'Research Agent',
    desc: 'Searches the web, gathers information, and synthesizes findings into a summary.',
    icon: Search,
    color: '#7c3aed',
    bgColor: '#f5f3ff',
    category: 'Research',
    popular: true,
    steps: ['Analyze', 'Scrape', 'Summarize'],
    nodes: [
      { id: 'analyze', position: { x: 50, y: 100 }, data: { label: 'Analyze Query', nodeType: 'llm_generate' as NodeType, description: 'Extract search terms', inputKeys: ['query'], outputKeys: ['search_terms', 'focus'], systemPrompt: 'Extract search terms from the query.\n\nReturn JSON: {"search_terms": ["term"], "focus": "topic"}', tools: [], isEntry: true, isTerminal: false } },
      { id: 'scrape', position: { x: 300, y: 100 }, data: { label: 'Web Scrape', nodeType: 'llm_tool_use' as NodeType, description: 'Fetch web content', inputKeys: ['search_terms'], outputKeys: ['results'], systemPrompt: 'Use web_scrape to fetch relevant pages.\n\nReturn JSON: {"results": [{"url": "...", "content": "..."}]}', tools: ['web_scrape'], isEntry: false, isTerminal: false } },
      { id: 'summarize', position: { x: 550, y: 100 }, data: { label: 'Summarize', nodeType: 'llm_generate' as NodeType, description: 'Synthesize findings', inputKeys: ['results', 'focus'], outputKeys: ['summary'], systemPrompt: 'Summarize the research results.\n\nReturn JSON: {"summary": "..."}', tools: [], isEntry: false, isTerminal: true } },
    ],
    edges: [{ id: 'e1', source: 'analyze', target: 'scrape' }, { id: 'e2', source: 'scrape', target: 'summarize' }],
  },
  support: {
    name: 'Support Agent',
    desc: 'Classifies incoming tickets by category and urgency, then generates appropriate responses.',
    icon: MessageSquare,
    color: '#2563eb',
    bgColor: '#eff6ff',
    category: 'Customer Service',
    popular: true,
    steps: ['Parse', 'Respond'],
    nodes: [
      { id: 'parse', position: { x: 50, y: 100 }, data: { label: 'Parse Ticket', nodeType: 'llm_generate' as NodeType, description: 'Classify ticket', inputKeys: ['ticket'], outputKeys: ['category', 'urgency'], systemPrompt: 'Classify the ticket.\n\nReturn JSON: {"category": "billing|tech|general", "urgency": "low|med|high"}', tools: [], isEntry: true, isTerminal: false } },
      { id: 'respond', position: { x: 300, y: 100 }, data: { label: 'Generate Response', nodeType: 'llm_generate' as NodeType, description: 'Draft response', inputKeys: ['category', 'urgency', 'ticket'], outputKeys: ['response'], systemPrompt: 'Generate helpful response.\n\nReturn JSON: {"response": "..."}', tools: [], isEntry: false, isTerminal: true } },
    ],
    edges: [{ id: 'e1', source: 'parse', target: 'respond' }],
  },
  profileScraper: {
    name: 'Profile Scraper',
    desc: 'Scrapes a profile page, summarizes the person, and extracts all blog/article links.',
    icon: Search,
    color: '#8b5cf6',
    bgColor: '#f5f3ff',
    category: 'Research',
    popular: true,
    steps: ['Scrape Profile', 'Get Blog Links'],
    nodes: [
      {
        id: 'scrape_profile',
        position: { x: 50, y: 100 },
        data: {
          label: 'Scrape Profile',
          nodeType: 'llm_tool_use' as NodeType,
          description: 'Scrape URL and summarize person',
          inputKeys: ['url'],
          outputKeys: ['profile_summary', 'url'],
          systemPrompt: `You MUST call the web_scrape tool first with the URL from the input.

Step 1: Call web_scrape with url = {url}
Step 2: After getting the page content, analyze it and create a profile summary

Include in your summary:
- What they do (job title, role)
- Core skills and expertise
- Notable projects or work

Return JSON:
{"profile_summary": "your detailed summary...", "url": "{url}"}`,
          tools: ['web_scrape'],
          isEntry: true,
          isTerminal: false
        }
      },
      {
        id: 'get_blog_links',
        position: { x: 350, y: 100 },
        data: {
          label: 'Get Blog Links',
          nodeType: 'llm_tool_use' as NodeType,
          description: 'Extract blog/article links from page',
          inputKeys: ['url', 'profile_summary'],
          outputKeys: ['links', 'profile_summary'],
          systemPrompt: `You MUST call the web_scrape tool first to fetch the page.

Step 1: Call web_scrape with url = {url}
Step 2: Look through the HTML/content for any blog posts, articles, or writing links
Step 3: Extract all URLs that look like blog posts or articles

Return JSON:
{"links": ["url1", "url2"], "profile_summary": "{profile_summary}"}`,
          tools: ['web_scrape'],
          isEntry: false,
          isTerminal: true
        }
      },
    ],
    edges: [{ id: 'e1', source: 'scrape_profile', target: 'get_blog_links' }],
  },
};

function generateCode(name: string, desc: string, nodes: any[], edges: any[]) {
  const snake = name.toLowerCase().replace(/\s+/g, '_').replace(/[^a-z0-9_]/g, '');
  const cls = name.split(/\s+/).map(w => w[0].toUpperCase() + w.slice(1)).join('').replace(/[^a-zA-Z0-9]/g, '') + 'Agent';
  const entry = nodes.find(n => n.data.isEntry) || nodes[0];
  const terms = nodes.filter(n => n.data.isTerminal).map(n => `"${n.id}"`);

  const nodesCode = nodes.map(n => {
    const v = n.id.replace(/-/g, '_');
    return `${v} = NodeSpec(id="${n.id}", name="${n.data.label}", description="${n.data.description || ''}", node_type="${n.data.nodeType}", input_keys=${JSON.stringify(n.data.inputKeys || [])}, output_keys=${JSON.stringify(n.data.outputKeys || [])}, system_prompt="""${n.data.systemPrompt || ''}""", tools=${JSON.stringify(n.data.tools || [])}, max_retries=3)`;
  }).join('\n\n');

  const edgesCode = edges.map(e => `    EdgeSpec(id="${e.id}", source="${e.source}", target="${e.target}", condition=EdgeCondition.ON_SUCCESS, priority=1)`).join(',\n');

  return `"""
${name}

${desc}

Generated by Hive Agent Builder
"""

from framework.graph import NodeSpec, EdgeSpec, EdgeCondition, Goal, SuccessCriterion
from framework.graph.edge import GraphSpec
from framework.graph.executor import ExecutionResult
from framework.runtime.agent_runtime import create_agent_runtime
from framework.runtime.execution_stream import EntryPointSpec
from framework.llm import LiteLLMProvider
from framework.runner.tool_registry import ToolRegistry
from dataclasses import dataclass
from pathlib import Path
import json

@dataclass
class RuntimeConfig:
    model: str = "gemini/gemini-2.0-flash"
    temperature: float = 0.7
    max_tokens: int = 4096

default_config = RuntimeConfig()

goal = Goal(
    id="${snake}-goal",
    name="${name} Goal",
    description="${desc}",
    success_criteria=[
        SuccessCriterion(id="complete", description="Complete task", metric="completion", target="100%", weight=1.0)
    ],
    constraints=[]
)

${nodesCode}

nodes = [${nodes.map(n => n.id.replace(/-/g, '_')).join(', ')}]

edges = [
${edgesCode}
]

entry_node = "${entry?.id || ''}"
entry_points = {"start": "${entry?.id || ''}"}
terminal_nodes = [${terms.join(', ')}]

class ${cls}:
    def __init__(self, config=None):
        self.config = config or default_config
        self.goal = goal
        self.nodes = nodes
        self.edges = edges
        self.entry_node = entry_node
        self.entry_points = entry_points
        self.terminal_nodes = terminal_nodes
        self._runtime = None

    def _create_runtime(self, mock=False):
        storage = Path.home() / ".hive" / "${snake}"
        storage.mkdir(parents=True, exist_ok=True)

        registry = ToolRegistry()
        if not mock:
            cfg_path = Path(__file__).parent / "mcp_servers.json"
            if cfg_path.exists():
                for name, cfg in json.load(open(cfg_path)).items():
                    cfg["name"] = name
                    if "cwd" in cfg and not Path(cfg["cwd"]).is_absolute():
                        cfg["cwd"] = str(Path(__file__).parent / cfg["cwd"])
                    registry.register_mcp_server(cfg)

        llm = None if mock else LiteLLMProvider(model=self.config.model)

        graph = GraphSpec(
            id="${snake}-graph",
            goal_id=self.goal.id,
            version="1.0.0",
            entry_node=self.entry_node,
            entry_points=self.entry_points,
            terminal_nodes=self.terminal_nodes,
            pause_nodes=[],
            nodes=self.nodes,
            edges=self.edges,
            default_model=self.config.model,
            max_tokens=self.config.max_tokens
        )

        self._runtime = create_agent_runtime(
            graph=graph,
            goal=self.goal,
            storage_path=storage,
            entry_points=[
                EntryPointSpec(id=k, name=k.title(), entry_node=v, trigger_type="manual", isolation_level="shared")
                for k, v in self.entry_points.items()
            ],
            llm=llm,
            tools=list(registry.get_tools().values()),
            tool_executor=registry.get_executor()
        )
        return self._runtime

    async def run(self, ctx: dict, mock=False):
        if not self._runtime:
            self._create_runtime(mock)
        await self._runtime.start()
        try:
            result = await self._runtime.trigger_and_wait("start", ctx)
            return result or ExecutionResult(success=False, error="Timeout")
        finally:
            await self._runtime.stop()

    def info(self):
        return {"name": "${name}", "nodes": [n.id for n in self.nodes], "entry": self.entry_node}

    def validate(self):
        errs = []
        ids = {n.id for n in self.nodes}
        for e in self.edges:
            if e.source not in ids:
                errs.append(f"Edge {e.id}: source not found")
            if e.target not in ids:
                errs.append(f"Edge {e.id}: target not found")
        return {"valid": not errs, "errors": errs}

default_agent = ${cls}()

if __name__ == "__main__":
    import asyncio
    import sys

    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "info":
            print(json.dumps(default_agent.info(), indent=2))
        elif cmd == "validate":
            result = default_agent.validate()
            print("Valid" if result["valid"] else result["errors"])
        elif cmd == "run":
            ctx = json.loads(sys.argv[2] if len(sys.argv) > 2 else "{}")
            r = asyncio.run(default_agent.run(ctx))
            print(json.dumps({"success": r.success, "output": r.output}, indent=2, default=str))
    else:
        print("Usage: python agent.py [info|validate|run]")
`;
}

export default function App() {
  const [nodes, setNodes] = useState<any[]>([]);
  const [edges, setEdges] = useState<any[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [name, setName] = useState('My Agent');
  const [desc, setDesc] = useState('');
  const [modal, setModal] = useState<'template' | 'export' | 'result' | 'help' | 'run-input' | null>('template');
  const [runInput, setRunInput] = useState<Record<string, string>>({});

  // Settings state - load from localStorage
  const [settings, setSettings] = useState(() => {
    const saved = localStorage.getItem('hive-agent-builder-settings');
    if (saved) {
      try { return JSON.parse(saved); } catch { /* ignore */ }
    }
    return { model: 'gemini/gemini-2.0-flash', apiKey: '', provider: 'gemini' };
  });
  const [showApiKey, setShowApiKey] = useState(false);

  // Collapsible sidebar sections
  const [expandedSections, setExpandedSections] = useState<Record<string, boolean>>(() => {
    // If no API key, expand settings by default
    const saved = localStorage.getItem('hive-agent-builder-settings');
    const hasApiKey = saved ? JSON.parse(saved).apiKey : false;
    return {
      settings: !hasApiKey,
      agent: true,
      nodes: true,
    };
  });

  const toggleSection = (section: string) => {
    setExpandedSections(prev => ({ ...prev, [section]: !prev[section] }));
  };

  // Save settings to localStorage when they change
  const updateSettings = (newSettings: typeof settings) => {
    setSettings(newSettings);
    localStorage.setItem('hive-agent-builder-settings', JSON.stringify(newSettings));
  };
  const [copied, setCopied] = useState(false);
  const [nodeTestInput, setNodeTestInput] = useState<Record<string, string>>({});
  const [runResult, setRunResult] = useState<{ success: boolean; output?: any; error?: string; nodesExecuted?: number } | null>(null);
  const [isRunning, setIsRunning] = useState(false);
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number; nodeId: string } | null>(null);

  // Helper: compute matching keys between two nodes
  const computeMatchingKeys = (sourceNode: any, targetNode: any): string[] => {
    if (!sourceNode || !targetNode) return [];
    const sourceOutputs = sourceNode.data.outputKeys || [];
    const targetInputs = targetNode.data.inputKeys || [];
    return sourceOutputs.filter((k: string) => targetInputs.includes(k));
  };

  // Helper: get available keys from source nodes (for suggestions)
  const getAvailableKeysForNode = (nodeId: string): string[] => {
    const incomingEdges = edges.filter(e => e.target === nodeId);
    const availableKeys: string[] = [];
    incomingEdges.forEach(edge => {
      const sourceNode = nodes.find(n => n.id === edge.source);
      if (sourceNode) {
        sourceNode.data.outputKeys.forEach((k: string) => {
          if (!availableKeys.includes(k)) availableKeys.push(k);
        });
      }
    });
    return availableKeys;
  };

  // Helper: check if node has missing inputs
  const nodeHasMissingInputs = (nodeId: string): boolean => {
    const node = nodes.find(n => n.id === nodeId);
    if (!node || node.data.isEntry) return false;
    const availableKeys = getAvailableKeysForNode(nodeId);
    const requiredKeys = node.data.inputKeys || [];
    return requiredKeys.some((k: string) => !availableKeys.includes(k));
  };

  // Update edges with matching keys data
  const updateEdgeData = (currentEdges: any[], currentNodes: any[]) => {
    return currentEdges.map(edge => {
      const sourceNode = currentNodes.find(n => n.id === edge.source);
      const targetNode = currentNodes.find(n => n.id === edge.target);
      const matchingKeys = computeMatchingKeys(sourceNode, targetNode);
      const hasWarning = matchingKeys.length === 0 && (targetNode?.data.inputKeys?.length > 0);
      return {
        ...edge,
        type: 'dataFlow',
        animated: true,
        data: { matchingKeys, hasWarning },
      };
    });
  };

  const loadTemplate = (key: keyof typeof TEMPLATES) => {
    const t = TEMPLATES[key];
    setName(t.name);
    setDesc(t.desc);
    const newNodes = t.nodes.map(n => ({ ...n, type: 'agentNode' }));
    setNodes(newNodes);
    const newEdges = updateEdgeData(t.edges.map(e => ({ ...e, type: 'dataFlow', animated: true })), newNodes);
    setEdges(newEdges);
    setModal(null);
  };

  const startFromScratch = () => {
    setName('My Agent');
    setDesc('');
    setNodes([]);
    setEdges([]);
    setSelected(null);
    setModal(null);
  };

  const onNodesChange = useCallback((c: any) => setNodes(n => applyNodeChanges(c, n)), []);
  const onEdgesChange = useCallback((c: any) => setEdges(e => applyEdgeChanges(c, e)), []);
  const onConnect = useCallback((c: any) => {
    setEdges(currentEdges => {
      const newEdge = { ...c, animated: true, type: 'dataFlow' };
      const updatedEdges = addEdge(newEdge, currentEdges);
      // Recompute edge data after adding the new edge
      return updatedEdges.map(edge => {
        if (edge.source === c.source && edge.target === c.target) {
          // This is the new edge, compute its data
          setNodes(currentNodes => {
            const sourceNode = currentNodes.find((n: any) => n.id === c.source);
            const targetNode = currentNodes.find((n: any) => n.id === c.target);
            const matchingKeys = sourceNode && targetNode
              ? (sourceNode.data.outputKeys || []).filter((k: string) =>
                  (targetNode.data.inputKeys || []).includes(k)
                )
              : [];
            const hasWarning = matchingKeys.length === 0 && (targetNode?.data.inputKeys?.length > 0);
            edge.data = { matchingKeys, hasWarning };
            return currentNodes;
          });
        }
        return edge;
      });
    });
  }, []);

  const addNode = (type: NodeType) => {
    const id = `node-${Date.now()}`;
    setNodes(n => [...n, {
      id,
      type: 'agentNode',
      position: { x: 100 + n.length * 50, y: 100 + (n.length % 2) * 50 },
      data: { label: nodeConfig[type].label, nodeType: type, description: '', inputKeys: [], outputKeys: [], systemPrompt: '', tools: [], isEntry: n.length === 0, isTerminal: false },
    }]);
    setSelected(id);
  };

  const updateNode = (id: string, data: Partial<NodeData>) => {
    setNodes(currentNodes => {
      const updatedNodes = currentNodes.map(x => x.id === id ? { ...x, data: { ...x.data, ...data } } : x);
      // If inputKeys or outputKeys changed, recompute edge data
      if (data.inputKeys || data.outputKeys) {
        setEdges(currentEdges => updateEdgeData(currentEdges, updatedNodes));
      }
      return updatedNodes;
    });
  };

  const deleteNode = (id: string) => {
    setNodes(prevNodes => prevNodes.filter(x => x.id !== id));
    setEdges(prevEdges => prevEdges.filter(x => x.source !== id && x.target !== id));
    setSelected(prev => prev === id ? null : prev);
    setContextMenu(null);
  };

  const duplicateNode = (id: string) => {
    const node = nodes.find(n => n.id === id);
    if (!node) return;
    const newId = `node-${Date.now()}`;
    setNodes(n => [...n, {
      ...node,
      id: newId,
      position: { x: node.position.x + 50, y: node.position.y + 50 },
      data: { ...node.data, label: `${node.data.label} (copy)`, isEntry: false },
    }]);
    setSelected(newId);
    setContextMenu(null);
  };

  const setAsEntry = (id: string) => {
    setNodes(n => n.map(x => ({ ...x, data: { ...x.data, isEntry: x.id === id } })));
    setContextMenu(null);
  };

  const setAsTerminal = (id: string) => {
    setNodes(n => n.map(x => x.id === id ? { ...x, data: { ...x.data, isTerminal: !x.data.isTerminal } } : x));
    setContextMenu(null);
  };

  const handleNodeContextMenu = (event: React.MouseEvent, nodeId: string) => {
    event.preventDefault();
    event.stopPropagation();
    setContextMenu({ x: event.clientX, y: event.clientY, nodeId });
  };

  const testNode = async (id: string) => {
    const node = nodes.find(n => n.id === id);
    if (!node) return;

    updateNode(id, { testStatus: 'running', testOutput: null });

    try {
      const input: Record<string, string> = {};
      node.data.inputKeys.forEach((k: string) => {
        input[k] = k === 'query' ? 'What is React?' : `sample ${k}`;
      });
      const inputData = JSON.parse(nodeTestInput[id] || JSON.stringify(input));

      // Check if API key is configured
      if (!settings.apiKey) {
        updateNode(id, { testStatus: 'error', testOutput: { error: 'API key not configured. Click Settings to add your API key.' } });
        return;
      }

      const res = await fetch('http://localhost:8000/api/test-node', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          node: {
            id: node.id,
            name: node.data.label,
            description: node.data.description,
            node_type: node.data.nodeType,
            input_keys: node.data.inputKeys,
            output_keys: node.data.outputKeys,
            system_prompt: node.data.systemPrompt,
            tools: node.data.tools || []
          },
          input_data: inputData,
          model: settings.model,
          api_key: settings.apiKey,
        }),
      });
      const data = await res.json();
      updateNode(id, { testStatus: data.success ? 'success' : 'error', testOutput: data });
    } catch (e) {
      updateNode(id, { testStatus: 'error', testOutput: { error: String(e) } });
    }
  };

  const showRunModal = () => {
    const entry = nodes.find(n => n.data.isEntry) || nodes[0];
    if (!entry) return;

    // Initialize run input from test input values (if available) or empty
    const initialInput: Record<string, string> = {};
    const testInput = nodeTestInput[entry.id] || {};

    // Try to parse test input if it's a JSON string
    let parsedTestInput: Record<string, string> = {};
    if (typeof testInput === 'string') {
      try {
        parsedTestInput = JSON.parse(testInput);
      } catch {
        // Not JSON, ignore
      }
    } else if (typeof testInput === 'object') {
      parsedTestInput = testInput as Record<string, string>;
    }

    entry.data.inputKeys.forEach((k: string) => {
      // Use test input value if available, otherwise empty
      initialInput[k] = parsedTestInput[k] || '';
    });
    setRunInput(initialInput);
    setModal('run-input');
  };

  const executeAgent = async () => {
    const entry = nodes.find(n => n.data.isEntry) || nodes[0];
    if (!entry) return;

    // Check if API key is configured - expand settings section instead of modal
    if (!settings.apiKey) {
      setExpandedSections(prev => ({ ...prev, settings: true }));
      setModal(null);
      return;
    }

    // Keep modal open during execution - show loading state inside modal
    setIsRunning(true);
    setRunResult(null);

    try {
      const res = await fetch('http://localhost:8000/api/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          agent_config: {
            name,
            description: desc,
            nodes: nodes.map(n => ({
              id: n.id,
              name: n.data.label,
              description: n.data.description,
              node_type: n.data.nodeType,
              input_keys: n.data.inputKeys,
              output_keys: n.data.outputKeys,
              system_prompt: n.data.systemPrompt,
              tools: n.data.tools,
              is_entry: n.data.isEntry,
              is_terminal: n.data.isTerminal
            })),
            edges: edges.map(e => ({ id: e.id, source: e.source, target: e.target })),
          },
          input: runInput,
          model: settings.model,
          api_key: settings.apiKey,
        }),
      });
      const data = await res.json();
      setRunResult({
        success: data.success,
        output: data.output,
        error: data.error,
        nodesExecuted: data.steps_executed || nodes.length,
      });
      setModal('result');
    } catch (e) {
      setRunResult({ success: false, error: String(e) });
      setModal('result');
    } finally {
      setIsRunning(false);
    }
  };

  const selNode = nodes.find(n => n.id === selected);
  const code = generateCode(name, desc, nodes, edges);

  const inputStyle = {
    width: '100%',
    padding: '10px 12px',
    border: '1px solid #d1d5db',
    borderRadius: 6,
    fontSize: 14,
    color: '#1e293b',
    background: '#fff',
    outline: 'none',
  };

  const labelStyle = {
    display: 'block',
    fontSize: 12,
    fontWeight: 600,
    color: '#64748b',
    marginBottom: 6,
    textTransform: 'uppercase' as const,
    letterSpacing: '0.5px',
  };

  const btnPrimary = {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    padding: '10px 16px',
    background: '#2563eb',
    border: 'none',
    borderRadius: 6,
    color: '#fff',
    fontSize: 14,
    fontWeight: 600,
    cursor: 'pointer',
  };

  const btnSecondary = {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    padding: '10px 16px',
    background: '#fff',
    border: '1px solid #d1d5db',
    borderRadius: 6,
    color: '#374151',
    fontSize: 14,
    fontWeight: 600,
    cursor: 'pointer',
  };

  return (
    <div style={{ display: 'flex', height: '100vh', fontFamily: 'system-ui, -apple-system, sans-serif', background: '#f1f5f9' }}>
      <style>{`
        input:focus, textarea:focus { border-color: #2563eb !important; box-shadow: 0 0 0 3px rgba(37,99,235,0.15) !important; }
        @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
        @keyframes pulse { 0%, 100% { opacity: 0.3; transform: scale(0.8); } 50% { opacity: 1; transform: scale(1.2); } }
      `}</style>

      {/* Left Sidebar - Unified Config Panel */}
      <div style={{ width: 320, background: '#fff', borderRight: '1px solid #e2e8f0', display: 'flex', flexDirection: 'column' }}>
        {/* Header */}
        <div style={{ padding: '14px 16px', borderBottom: '1px solid #e2e8f0', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <div style={{ width: 32, height: 32, borderRadius: 8, background: '#7c3aed', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <Layers size={18} color="#fff" />
            </div>
            <div>
              <h1 style={{ fontSize: 15, fontWeight: 700, color: '#0f172a', margin: 0 }}>Hive Agent Builder</h1>
              <p style={{ fontSize: 10, color: '#64748b', margin: 0 }}>Visual workflow designer</p>
            </div>
          </div>
          <button
            onClick={() => setModal('help')}
            style={{ padding: 6, background: '#f1f5f9', border: 'none', borderRadius: 5, cursor: 'pointer' }}
            title="Learn how to use this tool"
          >
            <BookOpen size={14} color="#64748b" />
          </button>
        </div>

        {/* Scrollable Content */}
        <div style={{ flex: 1, overflow: 'auto' }}>
          {/* Section: Settings (LLM Config) */}
          <div style={{ borderBottom: '1px solid #e2e8f0' }}>
            <button
              onClick={() => toggleSection('settings')}
              style={{
                width: '100%',
                padding: '10px 16px',
                background: !settings.apiKey ? '#fef2f2' : expandedSections.settings ? '#f8fafc' : '#fff',
                border: 'none',
                borderLeft: !settings.apiKey ? '3px solid #ef4444' : expandedSections.settings ? '3px solid #2563eb' : '3px solid transparent',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                textAlign: 'left',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                {expandedSections.settings ? <ChevronDown size={14} color="#64748b" /> : <ChevronRight size={14} color="#64748b" />}
                <Key size={14} color={!settings.apiKey ? '#ef4444' : '#64748b'} />
                <span style={{ fontSize: 12, fontWeight: 600, color: !settings.apiKey ? '#dc2626' : '#374151' }}>
                  LLM Settings
                </span>
                {!settings.apiKey && (
                  <span style={{ fontSize: 10, background: '#fee2e2', color: '#dc2626', padding: '2px 6px', borderRadius: 4, fontWeight: 600 }}>
                    Required
                  </span>
                )}
              </div>
              {settings.apiKey && (
                <span style={{ fontSize: 10, color: '#16a34a', fontWeight: 500 }}>✓ Configured</span>
              )}
            </button>
            {expandedSections.settings && (
              <div style={{ padding: '12px 16px', background: '#fafafa' }}>
                {/* Provider Selection */}
                <div style={{ marginBottom: 12 }}>
                  <label style={{ ...labelStyle, fontSize: 10 }}>Provider</label>
                  <div style={{ display: 'flex', gap: 4 }}>
                    {[
                      { id: 'gemini', name: 'Gemini', model: 'gemini/gemini-2.0-flash' },
                      { id: 'openai', name: 'OpenAI', model: 'gpt-4o-mini' },
                      { id: 'anthropic', name: 'Anthropic', model: 'claude-3-haiku-20240307' },
                    ].map(p => (
                      <button
                        key={p.id}
                        onClick={() => updateSettings({ ...settings, provider: p.id, model: p.model })}
                        style={{
                          flex: 1,
                          padding: '6px 8px',
                          background: settings.provider === p.id ? '#eff6ff' : '#fff',
                          border: `1px solid ${settings.provider === p.id ? '#2563eb' : '#e2e8f0'}`,
                          borderRadius: 4,
                          fontSize: 10,
                          fontWeight: 600,
                          color: settings.provider === p.id ? '#2563eb' : '#64748b',
                          cursor: 'pointer',
                        }}
                      >
                        {p.name}
                      </button>
                    ))}
                  </div>
                </div>

                {/* Model Selection */}
                <div style={{ marginBottom: 12 }}>
                  <label style={{ ...labelStyle, fontSize: 10 }}>Model</label>
                  <select
                    value={settings.model}
                    onChange={e => updateSettings({ ...settings, model: e.target.value })}
                    style={{ ...inputStyle, padding: '6px 10px', fontSize: 12, cursor: 'pointer' }}
                  >
                    {settings.provider === 'gemini' && (
                      <>
                        <option value="gemini/gemini-2.0-flash">Gemini 2.0 Flash (Fast)</option>
                        <option value="gemini/gemini-1.5-pro">Gemini 1.5 Pro</option>
                        <option value="gemini/gemini-1.5-flash">Gemini 1.5 Flash</option>
                      </>
                    )}
                    {settings.provider === 'openai' && (
                      <>
                        <option value="gpt-4o-mini">GPT-4o Mini (Fast)</option>
                        <option value="gpt-4o">GPT-4o</option>
                        <option value="gpt-4-turbo">GPT-4 Turbo</option>
                      </>
                    )}
                    {settings.provider === 'anthropic' && (
                      <>
                        <option value="claude-3-haiku-20240307">Claude 3 Haiku (Fast)</option>
                        <option value="claude-3-sonnet-20240229">Claude 3 Sonnet</option>
                        <option value="claude-3-opus-20240229">Claude 3 Opus</option>
                      </>
                    )}
                  </select>
                </div>

                {/* API Key */}
                <div>
                  <label style={{ ...labelStyle, fontSize: 10 }}>API Key</label>
                  <div style={{ position: 'relative' }}>
                    <input
                      type={showApiKey ? 'text' : 'password'}
                      value={settings.apiKey}
                      onChange={e => updateSettings({ ...settings, apiKey: e.target.value })}
                      placeholder={`Enter ${settings.provider} API key`}
                      style={{ ...inputStyle, padding: '6px 10px', paddingRight: 36, fontSize: 12 }}
                    />
                    <button
                      type="button"
                      onClick={() => setShowApiKey(!showApiKey)}
                      style={{
                        position: 'absolute',
                        right: 6,
                        top: '50%',
                        transform: 'translateY(-50%)',
                        padding: 4,
                        background: 'transparent',
                        border: 'none',
                        cursor: 'pointer',
                      }}
                    >
                      {showApiKey ? <EyeOff size={14} color="#64748b" /> : <Eye size={14} color="#64748b" />}
                    </button>
                  </div>
                  <div style={{ display: 'flex', gap: 8, marginTop: 6 }}>
                    <a
                      href={settings.provider === 'gemini' ? 'https://aistudio.google.com/app/apikey' : settings.provider === 'openai' ? 'https://platform.openai.com/api-keys' : 'https://console.anthropic.com/settings/keys'}
                      target="_blank"
                      rel="noopener noreferrer"
                      style={{ fontSize: 10, color: '#2563eb', textDecoration: 'none' }}
                    >
                      Get API Key →
                    </a>
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* Section: Agent Info */}
          <div style={{ borderBottom: '1px solid #e2e8f0' }}>
            <button
              onClick={() => toggleSection('agent')}
              style={{
                width: '100%',
                padding: '10px 16px',
                background: expandedSections.agent ? '#f8fafc' : '#fff',
                border: 'none',
                borderLeft: expandedSections.agent ? '3px solid #7c3aed' : '3px solid transparent',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                textAlign: 'left',
              }}
            >
              {expandedSections.agent ? <ChevronDown size={14} color="#64748b" /> : <ChevronRight size={14} color="#64748b" />}
              <Cpu size={14} color="#7c3aed" />
              <span style={{ fontSize: 12, fontWeight: 600, color: '#374151' }}>Agent Config</span>
              {name !== 'My Agent' && (
                <span style={{ fontSize: 10, color: '#64748b', marginLeft: 'auto' }}>{name}</span>
              )}
            </button>
            {expandedSections.agent && (
              <div style={{ padding: '12px 16px', background: '#fafafa' }}>
                <div style={{ marginBottom: 10 }}>
                  <label style={{ ...labelStyle, fontSize: 10 }}>Agent Name</label>
                  <input value={name} onChange={e => setName(e.target.value)} style={{ ...inputStyle, padding: '6px 10px', fontSize: 12 }} placeholder="My Research Agent" />
                </div>
                <div>
                  <label style={{ ...labelStyle, fontSize: 10 }}>Goal Description</label>
                  <textarea
                    value={desc}
                    onChange={e => setDesc(e.target.value)}
                    rows={2}
                    placeholder="What should this agent accomplish?"
                    style={{ ...inputStyle, resize: 'none', fontSize: 11, padding: '6px 10px' }}
                  />
                </div>
              </div>
            )}
          </div>

          {/* Section: Node Palette */}
          <div style={{ borderBottom: '1px solid #e2e8f0' }}>
            <button
              onClick={() => toggleSection('nodes')}
              style={{
                width: '100%',
                padding: '10px 16px',
                background: expandedSections.nodes ? '#f8fafc' : '#fff',
                border: 'none',
                borderLeft: expandedSections.nodes ? '3px solid #16a34a' : '3px solid transparent',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                textAlign: 'left',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                {expandedSections.nodes ? <ChevronDown size={14} color="#64748b" /> : <ChevronRight size={14} color="#64748b" />}
                <Layers size={14} color="#16a34a" />
                <span style={{ fontSize: 12, fontWeight: 600, color: '#374151' }}>Add Nodes</span>
              </div>
              {nodes.length > 0 && (
                <span style={{ fontSize: 10, background: '#dcfce7', color: '#166534', padding: '2px 6px', borderRadius: 4, fontWeight: 600 }}>
                  {nodes.length} node{nodes.length !== 1 ? 's' : ''}
                </span>
              )}
            </button>
            {expandedSections.nodes && (
              <div style={{ padding: '8px 12px', background: '#fafafa' }}>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                  {Object.entries(nodeConfig).map(([type, cfg]) => {
                    const Icon = cfg.icon;
                    return (
                      <button
                        key={type}
                        onClick={() => addNode(type as NodeType)}
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          gap: 8,
                          padding: '8px 10px',
                          background: '#fff',
                          border: '1px solid #e2e8f0',
                          borderRadius: 6,
                          cursor: 'pointer',
                          textAlign: 'left',
                          transition: 'all 0.15s',
                        }}
                        onMouseEnter={e => { e.currentTarget.style.borderColor = cfg.color; e.currentTarget.style.background = '#fff'; }}
                        onMouseLeave={e => { e.currentTarget.style.borderColor = '#e2e8f0'; e.currentTarget.style.background = '#fff'; }}
                      >
                        <div style={{ width: 26, height: 26, borderRadius: 5, background: `${cfg.color}15`, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                          <Icon size={13} color={cfg.color} />
                        </div>
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div style={{ fontSize: 11, fontWeight: 600, color: '#1e293b' }}>{cfg.label}</div>
                          <div style={{ fontSize: 10, color: '#64748b' }}>{cfg.shortDesc}</div>
                        </div>
                        <Plus size={14} color="#94a3b8" style={{ flexShrink: 0 }} />
                      </button>
                    );
                  })}
                </div>
                <button
                  onClick={() => setModal('help')}
                  style={{ marginTop: 8, width: '100%', background: 'none', border: 'none', color: '#2563eb', fontSize: 10, fontWeight: 600, cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 4 }}
                >
                  <HelpCircle size={10} /> What are these nodes?
                </button>
              </div>
            )}
          </div>

          {/* Graph Stats (when has nodes) */}
          {nodes.length > 0 && (
            <div style={{ padding: 12, borderBottom: '1px solid #e2e8f0' }}>
              <div style={{ display: 'flex', gap: 8 }}>
                <div style={{ flex: 1, background: '#f8fafc', borderRadius: 6, padding: 8, textAlign: 'center' }}>
                  <div style={{ fontSize: 18, fontWeight: 700, color: '#0f172a' }}>{nodes.length}</div>
                  <div style={{ fontSize: 10, color: '#64748b' }}>Nodes</div>
                </div>
                <div style={{ flex: 1, background: '#f8fafc', borderRadius: 6, padding: 8, textAlign: 'center' }}>
                  <div style={{ fontSize: 18, fontWeight: 700, color: '#0f172a' }}>{edges.length}</div>
                  <div style={{ fontSize: 10, color: '#64748b' }}>Edges</div>
                </div>
              </div>
            </div>
          )}

          {/* Quick Start (when no nodes) */}
          {nodes.length === 0 && (
            <div style={{ padding: 12, background: '#fffbeb', borderBottom: '1px solid #fef08a' }}>
              <div style={{ fontSize: 11, fontWeight: 600, color: '#92400e', marginBottom: 8, display: 'flex', alignItems: 'center', gap: 6 }}>
                <Zap size={12} color="#f59e0b" /> Quick Start
              </div>
              <div style={{ fontSize: 10, color: '#78350f', lineHeight: 1.5 }}>
                <div style={{ marginBottom: 4 }}>1. Configure your API key above</div>
                <div style={{ marginBottom: 4 }}>2. Add nodes from the palette</div>
                <div>3. Connect nodes & run!</div>
              </div>
            </div>
          )}
        </div>

        {/* Actions - Fixed at bottom */}
        <div style={{ padding: 12, borderTop: '1px solid #e2e8f0', background: '#fff' }}>
          <button
            onClick={showRunModal}
            disabled={!nodes.length || isRunning || !settings.apiKey}
            style={{
              ...btnPrimary,
              background: nodes.length && !isRunning && settings.apiKey ? '#16a34a' : '#9ca3af',
              width: '100%',
              padding: '10px 14px',
              fontSize: 13,
            }}
            title={!settings.apiKey ? 'Configure API key first' : 'Run the agent with test input'}
          >
            {isRunning ? <Loader2 size={14} style={{ animation: 'spin 1s linear infinite' }} /> : <Play size={14} />}
            {isRunning ? 'Running...' : 'Execute Agent'}
          </button>
          <button
            onClick={() => setModal('export')}
            disabled={!nodes.length}
            style={{ ...btnSecondary, opacity: nodes.length ? 1 : 0.5, width: '100%', marginTop: 6, padding: '8px 14px', fontSize: 12 }}
            title="Export as Python code for use with Hive Framework"
          >
            <FileCode size={14} /> Export Python Code
          </button>
        </div>
      </div>

      {/* Canvas */}
      <div style={{ flex: 1, position: 'relative' }}>
        <ReactFlowProvider>
          <ReactFlow
            nodes={nodes.map(n => ({
              ...n,
              data: { ...n.data, hasMissingInputs: nodeHasMissingInputs(n.id) }
            }))}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            onNodeClick={(_, n) => { setSelected(n.id); setContextMenu(null); }}
            onNodeContextMenu={(e, n) => handleNodeContextMenu(e, n.id)}
            onPaneClick={() => { setSelected(null); setContextMenu(null); }}
            nodeTypes={nodeTypes}
            edgeTypes={edgeTypes}
            fitView
            fitViewOptions={{ padding: 0.3, maxZoom: 1 }}
            minZoom={0.3}
            maxZoom={1.5}
            snapToGrid
            snapGrid={[20, 20]}
            defaultEdgeOptions={{ type: 'dataFlow', animated: true, style: { stroke: '#64748b', strokeWidth: 2 } }}
            proOptions={{ hideAttribution: true }}
            style={{ background: '#f1f5f9' }}
          >
            <Background variant={BackgroundVariant.Dots} gap={24} size={1} color="#cbd5e1" />
            <CustomControls />
          </ReactFlow>
        </ReactFlowProvider>

        {/* Context Menu */}
        {contextMenu && (
          <div
            style={{
              position: 'fixed',
              top: contextMenu.y,
              left: contextMenu.x,
              background: '#fff',
              borderRadius: 8,
              boxShadow: '0 4px 20px rgba(0,0,0,0.15)',
              border: '1px solid #e2e8f0',
              padding: 6,
              zIndex: 1000,
              minWidth: 180,
            }}
            onClick={e => e.stopPropagation()}
          >
            {(() => {
              const node = nodes.find(n => n.id === contextMenu.nodeId);
              if (!node) return null;
              return (
                <>
                  <button
                    onClick={() => { setSelected(contextMenu.nodeId); setContextMenu(null); }}
                    style={{
                      display: 'flex', alignItems: 'center', gap: 10, width: '100%',
                      padding: '10px 12px', background: 'transparent', border: 'none',
                      borderRadius: 6, cursor: 'pointer', fontSize: 13, color: '#334155',
                      textAlign: 'left',
                    }}
                    onMouseEnter={e => e.currentTarget.style.background = '#f1f5f9'}
                    onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
                  >
                    <Edit3 size={14} color="#64748b" /> Edit Node
                  </button>
                  <button
                    onClick={() => duplicateNode(contextMenu.nodeId)}
                    style={{
                      display: 'flex', alignItems: 'center', gap: 10, width: '100%',
                      padding: '10px 12px', background: 'transparent', border: 'none',
                      borderRadius: 6, cursor: 'pointer', fontSize: 13, color: '#334155',
                      textAlign: 'left',
                    }}
                    onMouseEnter={e => e.currentTarget.style.background = '#f1f5f9'}
                    onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
                  >
                    <Copy size={14} color="#64748b" /> Duplicate
                  </button>
                  <div style={{ height: 1, background: '#e2e8f0', margin: '6px 0' }} />
                  <button
                    onClick={() => setAsEntry(contextMenu.nodeId)}
                    style={{
                      display: 'flex', alignItems: 'center', gap: 10, width: '100%',
                      padding: '10px 12px', background: 'transparent', border: 'none',
                      borderRadius: 6, cursor: 'pointer', fontSize: 13,
                      color: node.data.isEntry ? '#16a34a' : '#334155',
                      textAlign: 'left',
                    }}
                    onMouseEnter={e => e.currentTarget.style.background = '#f1f5f9'}
                    onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
                  >
                    <Flag size={14} color={node.data.isEntry ? '#16a34a' : '#64748b'} />
                    {node.data.isEntry ? '✓ Start Node' : 'Set as Start'}
                  </button>
                  <button
                    onClick={() => setAsTerminal(contextMenu.nodeId)}
                    style={{
                      display: 'flex', alignItems: 'center', gap: 10, width: '100%',
                      padding: '10px 12px', background: 'transparent', border: 'none',
                      borderRadius: 6, cursor: 'pointer', fontSize: 13,
                      color: node.data.isTerminal ? '#dc2626' : '#334155',
                      textAlign: 'left',
                    }}
                    onMouseEnter={e => e.currentTarget.style.background = '#f1f5f9'}
                    onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
                  >
                    <CircleDot size={14} color={node.data.isTerminal ? '#dc2626' : '#64748b'} />
                    {node.data.isTerminal ? '✓ End Node' : 'Set as End'}
                  </button>
                  <div style={{ height: 1, background: '#e2e8f0', margin: '6px 0' }} />
                  <button
                    onClick={() => setModal('help')}
                    style={{
                      display: 'flex', alignItems: 'center', gap: 10, width: '100%',
                      padding: '10px 12px', background: 'transparent', border: 'none',
                      borderRadius: 6, cursor: 'pointer', fontSize: 13, color: '#334155',
                      textAlign: 'left',
                    }}
                    onMouseEnter={e => e.currentTarget.style.background = '#f1f5f9'}
                    onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
                  >
                    <HelpCircle size={14} color="#64748b" /> Help
                  </button>
                  <div style={{ height: 1, background: '#e2e8f0', margin: '6px 0' }} />
                  <button
                    onClick={() => deleteNode(contextMenu.nodeId)}
                    style={{
                      display: 'flex', alignItems: 'center', gap: 10, width: '100%',
                      padding: '10px 12px', background: 'transparent', border: 'none',
                      borderRadius: 6, cursor: 'pointer', fontSize: 13, color: '#dc2626',
                      textAlign: 'left',
                    }}
                    onMouseEnter={e => e.currentTarget.style.background = '#fef2f2'}
                    onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
                  >
                    <Trash2 size={14} color="#dc2626" /> Delete Node
                  </button>
                </>
              );
            })()}
          </div>
        )}

        {/* Empty State */}
        {!nodes.length && (
          <div style={{ position: 'absolute', top: '50%', left: '50%', transform: 'translate(-50%, -50%)', textAlign: 'center', maxWidth: 480 }}>
            <div style={{ width: 72, height: 72, borderRadius: 20, background: '#fff', border: '1px solid #e2e8f0', display: 'flex', alignItems: 'center', justifyContent: 'center', margin: '0 auto 20px', boxShadow: '0 4px 12px rgba(0,0,0,0.05)' }}>
              <Layers size={36} color="#7c3aed" />
            </div>
            <h2 style={{ fontSize: 24, fontWeight: 700, color: '#0f172a', margin: '0 0 12px 0' }}>Start Building</h2>
            <p style={{ fontSize: 15, color: '#64748b', margin: '0 0 24px 0', lineHeight: 1.6 }}>
              Add your first node or pick a template to get started.
            </p>
            <div style={{ display: 'flex', gap: 8, justifyContent: 'center', flexWrap: 'wrap', marginBottom: 20 }}>
              {Object.entries(nodeConfig).map(([type, config]) => (
                <button
                  key={type}
                  onClick={() => addNode(type as NodeType)}
                  style={{
                    padding: '10px 16px',
                    background: '#fff',
                    border: `1px solid ${config.color}30`,
                    borderRadius: 8,
                    cursor: 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    gap: 6,
                    fontSize: 13,
                    fontWeight: 500,
                    color: config.color,
                    transition: 'all 0.15s',
                  }}
                  onMouseEnter={e => { e.currentTarget.style.background = `${config.color}10`; e.currentTarget.style.borderColor = config.color; }}
                  onMouseLeave={e => { e.currentTarget.style.background = '#fff'; e.currentTarget.style.borderColor = `${config.color}30`; }}
                >
                  <config.icon size={16} /> {config.label}
                </button>
              ))}
            </div>
            <button
              onClick={() => setModal('template')}
              style={{
                padding: '10px 20px',
                background: '#f8fafc',
                border: '1px solid #e2e8f0',
                borderRadius: 8,
                cursor: 'pointer',
                fontSize: 13,
                fontWeight: 500,
                color: '#64748b',
                transition: 'all 0.15s',
              }}
              onMouseEnter={e => { e.currentTarget.style.background = '#f1f5f9'; e.currentTarget.style.color = '#475569'; }}
              onMouseLeave={e => { e.currentTarget.style.background = '#f8fafc'; e.currentTarget.style.color = '#64748b'; }}
            >
              <Layers size={14} style={{ display: 'inline', verticalAlign: 'middle', marginRight: 6 }} />
              Browse Templates
            </button>
          </div>
        )}
      </div>

      {/* Right Panel - Node Properties */}
      {selNode && (() => {
        const availableKeys = getAvailableKeysForNode(selected!);
        const unusedAvailableKeys = availableKeys.filter(k => !selNode.data.inputKeys.includes(k));
        const missingInputKeys = selNode.data.inputKeys.filter((k: string) => !availableKeys.includes(k) && !selNode.data.isEntry);

        return (
        <div style={{ width: 360, background: '#fff', borderLeft: '1px solid #e2e8f0', display: 'flex', flexDirection: 'column' }}>
          {/* Header */}
          <div style={{ padding: '12px 16px', borderBottom: '1px solid #e2e8f0', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              {(() => { const nt = selNode.data.nodeType as NodeType; const Icon = nodeConfig[nt].icon; return <Icon size={16} color={nodeConfig[nt].color} />; })()}
              <span style={{ fontSize: 14, fontWeight: 600, color: '#0f172a' }}>Configure Node</span>
            </div>
            <button onClick={() => setSelected(null)} style={{ padding: 6, background: '#f1f5f9', border: 'none', borderRadius: 5, cursor: 'pointer' }} title="Close panel">
              <X size={14} color="#64748b" />
            </button>
          </div>

          {/* Node Type Info */}
          <div style={{ padding: '12px 16px', background: '#f8fafc', borderBottom: '1px solid #e2e8f0' }}>
            <div style={{ fontSize: 11, fontWeight: 600, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: 4 }}>Node Type</div>
            <div style={{ fontSize: 13, color: '#0f172a', fontWeight: 600, marginBottom: 4 }}>{nodeConfig[selNode.data.nodeType as NodeType].label}</div>
            <div style={{ fontSize: 12, color: '#64748b', lineHeight: 1.5 }}>{nodeConfig[selNode.data.nodeType as NodeType].fullDesc}</div>
          </div>

          <div style={{ flex: 1, overflow: 'auto', padding: 16 }}>
            {/* Section 1: Node Identity */}
            <div style={{ marginBottom: 20 }}>
              <label style={labelStyle}>Node Name</label>
              <input value={selNode.data.label} onChange={e => updateNode(selected!, { label: e.target.value })} style={inputStyle} />
            </div>

            {/* Section 2: Data Flow (prominent) */}
            <div style={{
              marginBottom: 20,
              background: '#f8fafc',
              borderRadius: 8,
              padding: 14,
              border: '1px solid #e2e8f0',
              borderLeft: '3px solid #2563eb'
            }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: '#1e40af', marginBottom: 12, display: 'flex', alignItems: 'center', gap: 6 }}>
                <ArrowRight size={14} /> Data Flow
              </div>

              {/* Input Keys with Suggestions */}
              <div style={{ marginBottom: 14 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                  <label style={{ ...labelStyle, margin: 0, color: '#1e40af' }}>Input Keys</label>
                  <button
                    onClick={() => updateNode(selected!, { inputKeys: [...selNode.data.inputKeys, `input${selNode.data.inputKeys.length + 1}`] })}
                    style={{ background: 'none', border: 'none', color: '#2563eb', fontSize: 11, fontWeight: 600, cursor: 'pointer' }}
                  >
                    + Add
                  </button>
                </div>

                {/* Key Suggestions from connected nodes */}
                {unusedAvailableKeys.length > 0 && (
                  <div style={{ marginBottom: 8 }}>
                    <div style={{ fontSize: 10, color: '#64748b', marginBottom: 4 }}>Available from connected nodes:</div>
                    <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                      {unusedAvailableKeys.map(k => (
                        <button
                          key={k}
                          onClick={() => updateNode(selected!, { inputKeys: [...selNode.data.inputKeys, k] })}
                          style={{
                            fontSize: 11,
                            fontWeight: 600,
                            color: '#2563eb',
                            background: '#dbeafe',
                            padding: '3px 8px',
                            borderRadius: 4,
                            border: '1px dashed #93c5fd',
                            cursor: 'pointer',
                            display: 'flex',
                            alignItems: 'center',
                            gap: 4,
                          }}
                          title={`Add "${k}" from connected node`}
                        >
                          <Plus size={10} /> {k}
                        </button>
                      ))}
                    </div>
                  </div>
                )}

                {selNode.data.inputKeys.length === 0 && unusedAvailableKeys.length === 0 && (
                  <p style={{ fontSize: 11, color: '#94a3b8', margin: 0, background: '#fff', padding: 8, borderRadius: 4, border: '1px solid #e2e8f0' }}>
                    {selNode.data.isEntry ? 'Entry node - define what data the agent receives' : 'Connect a source node or add keys manually'}
                  </p>
                )}

                {selNode.data.inputKeys.map((k: string, i: number) => {
                  const isMissing = missingInputKeys.includes(k);
                  return (
                    <div key={i} style={{ display: 'flex', gap: 6, marginBottom: 6 }}>
                      <div style={{ position: 'relative', flex: 1 }}>
                        <input
                          value={k}
                          onChange={e => {
                            const keys = [...selNode.data.inputKeys];
                            keys[i] = e.target.value;
                            updateNode(selected!, { inputKeys: keys });
                          }}
                          style={{
                            ...inputStyle,
                            padding: '6px 10px',
                            fontSize: 13,
                            background: '#fff',
                            borderColor: isMissing ? '#f59e0b' : '#d1d5db',
                          }}
                        />
                        {isMissing && (
                          <div style={{ position: 'absolute', right: 8, top: '50%', transform: 'translateY(-50%)' }} title="Key not provided by connected nodes">
                            <AlertTriangle size={14} color="#f59e0b" />
                          </div>
                        )}
                      </div>
                      <button
                        onClick={() => updateNode(selected!, { inputKeys: selNode.data.inputKeys.filter((_: any, j: number) => j !== i) })}
                        style={{ padding: '0 10px', background: '#fef2f2', border: 'none', borderRadius: 5, cursor: 'pointer' }}
                      >
                        <X size={14} color="#dc2626" />
                      </button>
                    </div>
                  );
                })}
              </div>

              {/* Output Keys */}
              <div>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                  <label style={{ ...labelStyle, margin: 0, color: '#166534' }}>Output Keys</label>
                  <button
                    onClick={() => updateNode(selected!, { outputKeys: [...selNode.data.outputKeys, `output${selNode.data.outputKeys.length + 1}`] })}
                    style={{ background: 'none', border: 'none', color: '#16a34a', fontSize: 11, fontWeight: 600, cursor: 'pointer' }}
                  >
                    + Add
                  </button>
                </div>
                {selNode.data.outputKeys.length === 0 && (
                  <p style={{ fontSize: 11, color: '#94a3b8', margin: 0, background: '#fff', padding: 8, borderRadius: 4, border: '1px solid #e2e8f0' }}>
                    Define what data this node produces
                  </p>
                )}
                {selNode.data.outputKeys.map((k: string, i: number) => (
                  <div key={i} style={{ display: 'flex', gap: 6, marginBottom: 6 }}>
                    <input
                      value={k}
                      onChange={e => {
                        const keys = [...selNode.data.outputKeys];
                        keys[i] = e.target.value;
                        updateNode(selected!, { outputKeys: keys });
                      }}
                      style={{ ...inputStyle, padding: '6px 10px', fontSize: 13, background: '#fff' }}
                    />
                    <button
                      onClick={() => updateNode(selected!, { outputKeys: selNode.data.outputKeys.filter((_: any, j: number) => j !== i) })}
                      style={{ padding: '0 10px', background: '#fef2f2', border: 'none', borderRadius: 5, cursor: 'pointer' }}
                    >
                      <X size={14} color="#dc2626" />
                    </button>
                  </div>
                ))}
              </div>

              {/* Data Flow Tip */}
              <div style={{ marginTop: 10, fontSize: 10, color: '#64748b', background: '#fff', padding: 8, borderRadius: 4, border: '1px solid #e2e8f0' }}>
                <strong>Tip:</strong> Output keys from source nodes become available as input keys for connected target nodes.
              </div>
            </div>

            {/* Section 3: Behavior */}
            <div style={{ marginBottom: 20 }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: '#374151', marginBottom: 12, display: 'flex', alignItems: 'center', gap: 6 }}>
                <Brain size={14} /> Behavior
              </div>

              {/* System Prompt */}
              <div style={{ marginBottom: 12 }}>
                <label style={{ ...labelStyle, fontSize: 10 }}>System Prompt</label>
                <textarea
                  value={selNode.data.systemPrompt}
                  onChange={e => updateNode(selected!, { systemPrompt: e.target.value })}
                  rows={4}
                  placeholder="Tell the AI what to do. Include output format (e.g., Return JSON: {...})"
                  style={{ ...inputStyle, fontFamily: 'monospace', fontSize: 11, resize: 'vertical' }}
                />
              </div>

              {/* Tools (for tool nodes) */}
              {selNode.data.nodeType === 'llm_tool_use' && (
                <div>
                  <label style={{ ...labelStyle, fontSize: 10 }}>Available Tools</label>
                  <div style={{ background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: 6, padding: 8, maxHeight: 150, overflow: 'auto' }}>
                    {TOOLS.map(t => (
                      <label key={t.id} style={{ display: 'flex', alignItems: 'flex-start', gap: 8, padding: '5px 0', fontSize: 11, cursor: 'pointer', color: '#334155' }}>
                        <input
                          type="checkbox"
                          checked={selNode.data.tools?.includes(t.id)}
                          onChange={e => updateNode(selected!, {
                            tools: e.target.checked
                              ? [...(selNode.data.tools || []), t.id]
                              : selNode.data.tools.filter((x: string) => x !== t.id)
                          })}
                          style={{ width: 14, height: 14, accentColor: '#2563eb', marginTop: 1 }}
                        />
                        <div>
                          <div style={{ fontWeight: 600, fontSize: 11 }}>{t.name}</div>
                          <div style={{ fontSize: 10, color: '#64748b' }}>{t.desc}</div>
                        </div>
                      </label>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {/* Section 4: Test (grouped) */}
            <div style={{
              marginBottom: 20,
              background: '#f0fdf4',
              borderRadius: 8,
              padding: 14,
              border: '1px solid #bbf7d0',
              borderLeft: '3px solid #16a34a'
            }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: '#166534', marginBottom: 12, display: 'flex', alignItems: 'center', gap: 6 }}>
                <Play size={14} /> Test Node
              </div>

              <label style={{ ...labelStyle, fontSize: 10, color: '#166534' }}>Test Input (JSON)</label>
              <textarea
                value={nodeTestInput[selected!] || JSON.stringify(
                  Object.fromEntries(selNode.data.inputKeys.map((k: string) => [k, k === 'query' ? 'What is React?' : `sample`])),
                  null, 2
                )}
                onChange={e => setNodeTestInput(p => ({ ...p, [selected!]: e.target.value }))}
                rows={3}
                style={{ ...inputStyle, fontFamily: 'monospace', fontSize: 11, resize: 'vertical', marginBottom: 10, background: '#fff' }}
              />

              <button
                onClick={() => testNode(selected!)}
                disabled={selNode.data.testStatus === 'running'}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  gap: 6,
                  width: '100%',
                  padding: '10px 16px',
                  background: selNode.data.testStatus === 'running' ? '#9ca3af' : '#16a34a',
                  border: 'none',
                  borderRadius: 6,
                  color: '#fff',
                  fontSize: 13,
                  fontWeight: 600,
                  cursor: selNode.data.testStatus === 'running' ? 'wait' : 'pointer',
                }}
              >
                {selNode.data.testStatus === 'running' ? <Loader2 size={14} style={{ animation: 'spin 1s linear infinite' }} /> : <Play size={14} />}
                {selNode.data.testStatus === 'running' ? 'Testing...' : 'Run Test'}
              </button>

              {selNode.data.testOutput && (
                <div style={{
                  marginTop: 12,
                  background: selNode.data.testStatus === 'success' ? '#fff' : '#fef2f2',
                  border: `1px solid ${selNode.data.testStatus === 'success' ? '#bbf7d0' : '#fecaca'}`,
                  borderRadius: 6,
                  padding: 10,
                }}>
                  <div style={{
                    fontSize: 11,
                    fontWeight: 700,
                    color: selNode.data.testStatus === 'success' ? '#166534' : '#991b1b',
                    marginBottom: 6,
                  }}>
                    {selNode.data.testStatus === 'success' ? '✓ Test Passed' : '✗ Test Failed'}
                  </div>
                  <pre style={{
                    margin: 0,
                    fontSize: 10,
                    fontFamily: 'monospace',
                    color: '#334155',
                    whiteSpace: 'pre-wrap',
                    maxHeight: 100,
                    overflow: 'auto',
                  }}>
                    {JSON.stringify(selNode.data.testOutput.output || selNode.data.testOutput.error, null, 2)}
                  </pre>
                </div>
              )}
            </div>

            {/* Section 5: Execution Settings */}
            <div style={{ marginBottom: 20 }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: '#374151', marginBottom: 10, display: 'flex', alignItems: 'center', gap: 6 }}>
                <Flag size={14} /> Execution Role
              </div>
              <div style={{ display: 'flex', gap: 8 }}>
                <button
                  onClick={() => setNodes(n => n.map(x => ({ ...x, data: { ...x.data, isEntry: x.id === selected } })))}
                  style={{
                    flex: 1,
                    padding: 10,
                    background: selNode.data.isEntry ? '#dcfce7' : '#f8fafc',
                    border: `1px solid ${selNode.data.isEntry ? '#22c55e' : '#e2e8f0'}`,
                    borderRadius: 6,
                    fontSize: 11,
                    fontWeight: 600,
                    color: selNode.data.isEntry ? '#166534' : '#64748b',
                    cursor: 'pointer',
                  }}
                >
                  {selNode.data.isEntry && '✓ '}Start Node
                </button>
                <button
                  onClick={() => updateNode(selected!, { isTerminal: !selNode.data.isTerminal })}
                  style={{
                    flex: 1,
                    padding: 10,
                    background: selNode.data.isTerminal ? '#fee2e2' : '#f8fafc',
                    border: `1px solid ${selNode.data.isTerminal ? '#ef4444' : '#e2e8f0'}`,
                    borderRadius: 6,
                    fontSize: 11,
                    fontWeight: 600,
                    color: selNode.data.isTerminal ? '#991b1b' : '#64748b',
                    cursor: 'pointer',
                  }}
                >
                  {selNode.data.isTerminal && '✓ '}End Node
                </button>
              </div>
            </div>

            {/* Section 6: Danger Zone */}
            <div style={{ borderTop: '1px solid #fecaca', paddingTop: 16 }}>
              <button
                onClick={() => {
                  if (window.confirm(`Delete "${selNode.data.label}"? This cannot be undone.`)) {
                    deleteNode(selected!);
                  }
                }}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  gap: 8,
                  width: '100%',
                  padding: '10px 16px',
                  background: '#fef2f2',
                  border: '1px solid #fecaca',
                  borderRadius: 6,
                  color: '#dc2626',
                  fontSize: 12,
                  fontWeight: 600,
                  cursor: 'pointer',
                }}
                onMouseEnter={e => { e.currentTarget.style.background = '#fee2e2'; }}
                onMouseLeave={e => { e.currentTarget.style.background = '#fef2f2'; }}
              >
                <Trash2 size={14} /> Delete Node
              </button>
            </div>
          </div>
        </div>
      );
      })()}

      {/* Help Modal */}
      {modal === 'help' && (
        <div
          style={{ position: 'fixed', inset: 0, background: 'rgba(15,23,42,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100 }}
          onClick={() => setModal(null)}
        >
          <div
            style={{ background: '#fff', borderRadius: 12, width: 720, maxWidth: '95%', maxHeight: '90vh', overflow: 'hidden', boxShadow: '0 25px 50px rgba(0,0,0,0.25)' }}
            onClick={e => e.stopPropagation()}
          >
            <div style={{ padding: '24px 28px', borderBottom: '1px solid #e2e8f0', display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
              <div>
                <h2 style={{ fontSize: 20, fontWeight: 700, color: '#0f172a', margin: '0 0 6px 0' }}>How Hive Agent Builder Works</h2>
                <p style={{ fontSize: 14, color: '#64748b', margin: 0 }}>Build AI agents by connecting nodes into a workflow</p>
              </div>
              <button onClick={() => setModal(null)} style={{ padding: 8, background: '#f1f5f9', border: 'none', borderRadius: 6, cursor: 'pointer' }}>
                <X size={18} color="#64748b" />
              </button>
            </div>

            <div style={{ padding: 24, maxHeight: 'calc(90vh - 100px)', overflow: 'auto' }}>
              {/* Overview */}
              <div style={{ marginBottom: 28 }}>
                <h3 style={{ fontSize: 16, fontWeight: 700, color: '#0f172a', margin: '0 0 12px 0', display: 'flex', alignItems: 'center', gap: 8 }}>
                  <Zap size={18} color="#f59e0b" /> The Big Picture
                </h3>
                <div style={{ background: '#f8fafc', borderRadius: 8, padding: 16, fontSize: 14, color: '#475569', lineHeight: 1.7 }}>
                  <p style={{ margin: '0 0 12px 0' }}>
                    <strong>Agents</strong> are AI-powered workflows that process data through a series of steps (nodes).
                  </p>
                  <p style={{ margin: '0 0 12px 0' }}>
                    Think of it like a factory assembly line: data enters at the <strong style={{ color: '#22c55e' }}>START</strong> node, gets processed by each node along the way, and exits at the <strong style={{ color: '#ef4444' }}>END</strong> node with the final result.
                  </p>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, justifyContent: 'center', padding: '12px 0' }}>
                    <span style={{ background: '#dcfce7', padding: '4px 12px', borderRadius: 6, fontSize: 12, fontWeight: 600, color: '#166534' }}>Input</span>
                    <ArrowRight size={16} color="#94a3b8" />
                    <span style={{ background: '#e0e7ff', padding: '4px 12px', borderRadius: 6, fontSize: 12, fontWeight: 600, color: '#3730a3' }}>Node 1</span>
                    <ArrowRight size={16} color="#94a3b8" />
                    <span style={{ background: '#e0e7ff', padding: '4px 12px', borderRadius: 6, fontSize: 12, fontWeight: 600, color: '#3730a3' }}>Node 2</span>
                    <ArrowRight size={16} color="#94a3b8" />
                    <span style={{ background: '#fee2e2', padding: '4px 12px', borderRadius: 6, fontSize: 12, fontWeight: 600, color: '#991b1b' }}>Output</span>
                  </div>
                </div>
              </div>

              {/* Node Types */}
              <div style={{ marginBottom: 28 }}>
                <h3 style={{ fontSize: 16, fontWeight: 700, color: '#0f172a', margin: '0 0 16px 0', display: 'flex', alignItems: 'center', gap: 8 }}>
                  <Layers size={18} color="#7c3aed" /> Node Types Explained
                </h3>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                  {Object.entries(nodeConfig).map(([type, cfg]) => {
                    const Icon = cfg.icon;
                    return (
                      <div key={type} style={{ background: '#fff', border: '1px solid #e2e8f0', borderRadius: 8, padding: 16 }}>
                        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12 }}>
                          <div style={{ width: 40, height: 40, borderRadius: 10, background: `${cfg.color}15`, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                            <Icon size={20} color={cfg.color} />
                          </div>
                          <div style={{ flex: 1 }}>
                            <div style={{ fontSize: 14, fontWeight: 700, color: '#0f172a', marginBottom: 4 }}>{cfg.label}</div>
                            <div style={{ fontSize: 13, color: '#475569', marginBottom: 8, lineHeight: 1.5 }}>{cfg.fullDesc}</div>
                            <div style={{ fontSize: 12, marginBottom: 6 }}>
                              <span style={{ fontWeight: 600, color: '#64748b' }}>Example: </span>
                              <span style={{ color: '#475569' }}>{cfg.example}</span>
                            </div>
                            <div style={{ fontSize: 12, background: '#f8fafc', padding: '8px 10px', borderRadius: 6, color: '#64748b' }}>
                              <span style={{ fontWeight: 600 }}>Use when: </span>{cfg.useWhen}
                            </div>
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>

              {/* Export Section */}
              <div style={{ marginBottom: 28 }}>
                <h3 style={{ fontSize: 16, fontWeight: 700, color: '#0f172a', margin: '0 0 12px 0', display: 'flex', alignItems: 'center', gap: 8 }}>
                  <FileCode size={18} color="#2563eb" /> Exporting Your Agent
                </h3>
                <div style={{ background: '#eff6ff', borderRadius: 8, padding: 16, fontSize: 14, color: '#1e40af', lineHeight: 1.7 }}>
                  <p style={{ margin: '0 0 8px 0' }}>
                    Click <strong>"Export Python Code"</strong> in the sidebar to download a <code>.py</code> file that runs with the Hive Framework.
                  </p>
                  <p style={{ margin: 0 }}>
                    You can then run it with: <code style={{ background: '#dbeafe', padding: '2px 6px', borderRadius: 4 }}>python my_agent.py run '{"{\"query\": \"...\"}'"}</code>
                  </p>
                </div>
              </div>

              {/* Tips */}
              <div>
                <h3 style={{ fontSize: 16, fontWeight: 700, color: '#0f172a', margin: '0 0 12px 0', display: 'flex', alignItems: 'center', gap: 8 }}>
                  <Info size={18} color="#16a34a" /> Pro Tips
                </h3>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 12 }}>
                  <div style={{ background: '#f0fdf4', borderRadius: 8, padding: 14 }}>
                    <div style={{ fontSize: 13, fontWeight: 600, color: '#166534', marginBottom: 6 }}>Always specify output format</div>
                    <div style={{ fontSize: 12, color: '#15803d', lineHeight: 1.5 }}>
                      In your system prompt, tell the AI exactly what JSON to return: <code>Return JSON: {"{"}"key": "value"{"}"}</code>
                    </div>
                  </div>
                  <div style={{ background: '#f0fdf4', borderRadius: 8, padding: 14 }}>
                    <div style={{ fontSize: 13, fontWeight: 600, color: '#166534', marginBottom: 6 }}>Test individual nodes</div>
                    <div style={{ fontSize: 12, color: '#15803d', lineHeight: 1.5 }}>
                      Click a node and use the "Test" button to verify it works before running the full agent.
                    </div>
                  </div>
                  <div style={{ background: '#f0fdf4', borderRadius: 8, padding: 14 }}>
                    <div style={{ fontSize: 13, fontWeight: 600, color: '#166534', marginBottom: 6 }}>Match input/output keys</div>
                    <div style={{ fontSize: 12, color: '#15803d', lineHeight: 1.5 }}>
                      Node B's input keys should match Node A's output keys for data to flow correctly.
                    </div>
                  </div>
                  <div style={{ background: '#f0fdf4', borderRadius: 8, padding: 14 }}>
                    <div style={{ fontSize: 13, fontWeight: 600, color: '#166534', marginBottom: 6 }}>Start with templates</div>
                    <div style={{ fontSize: 12, color: '#15803d', lineHeight: 1.5 }}>
                      Templates show best practices. Study them before building custom agents.
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Template Modal */}
      {modal === 'template' && (
        <div
          style={{ position: 'fixed', inset: 0, background: 'rgba(15,23,42,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100 }}
          onClick={() => setModal(null)}
        >
          <div
            style={{ background: '#fff', borderRadius: 12, width: 720, maxWidth: '95%', maxHeight: '90vh', overflow: 'hidden', boxShadow: '0 25px 50px rgba(0,0,0,0.25)' }}
            onClick={e => e.stopPropagation()}
          >
            {/* Header */}
            <div style={{ padding: '24px 28px', borderBottom: '1px solid #e2e8f0' }}>
              <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between' }}>
                <div>
                  <h2 style={{ fontSize: 20, fontWeight: 700, color: '#0f172a', margin: '0 0 6px 0' }}>Choose a Starting Template</h2>
                  <p style={{ fontSize: 14, color: '#64748b', margin: 0 }}>
                    Templates are pre-built agent workflows you can customize.
                  </p>
                </div>
                <button onClick={() => setModal(null)} style={{ padding: 8, background: '#f1f5f9', border: 'none', borderRadius: 6, cursor: 'pointer' }}>
                  <X size={18} color="#64748b" />
                </button>
              </div>
            </div>

            {/* Info Banner */}
            <div style={{ padding: '12px 28px', background: '#fefce8', borderBottom: '1px solid #fef08a', display: 'flex', alignItems: 'center', gap: 10 }}>
              <Info size={16} color="#ca8a04" />
              <span style={{ fontSize: 13, color: '#854d0e' }}>
                New to agents? Click <strong>"Learn How It Works"</strong> below to understand node types first.
              </span>
            </div>

            {/* Template Grid */}
            <div style={{ padding: 20, maxHeight: 'calc(90vh - 220px)', overflow: 'auto' }}>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 12 }}>
                {Object.entries(TEMPLATES).map(([k, t]) => {
                  const Icon = t.icon;
                  return (
                    <button
                      key={k}
                      onClick={() => loadTemplate(k as keyof typeof TEMPLATES)}
                      style={{
                        display: 'flex',
                        flexDirection: 'column',
                        padding: 0,
                        background: '#fff',
                        border: '1px solid #e2e8f0',
                        borderRadius: 10,
                        cursor: 'pointer',
                        textAlign: 'left',
                        overflow: 'hidden',
                        transition: 'all 0.15s',
                      }}
                      onMouseEnter={e => {
                        e.currentTarget.style.borderColor = t.color;
                        e.currentTarget.style.boxShadow = `0 4px 12px ${t.color}15`;
                      }}
                      onMouseLeave={e => {
                        e.currentTarget.style.borderColor = '#e2e8f0';
                        e.currentTarget.style.boxShadow = 'none';
                      }}
                    >
                      <div style={{ padding: 16 }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
                          <div style={{ width: 36, height: 36, borderRadius: 8, background: t.bgColor, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                            <Icon size={18} color={t.color} />
                          </div>
                          <div style={{ flex: 1 }}>
                            <div style={{ fontSize: 14, fontWeight: 600, color: '#0f172a' }}>{t.name}</div>
                            <div style={{ fontSize: 11, color: '#64748b' }}>{t.category}</div>
                          </div>
                          {t.popular && (
                            <span style={{ fontSize: 10, fontWeight: 600, color: '#16a34a', background: '#dcfce7', padding: '3px 8px', borderRadius: 20 }}>
                              Popular
                            </span>
                          )}
                        </div>
                        <p style={{ fontSize: 12, color: '#475569', margin: '0 0 12px 0', lineHeight: 1.5 }}>{t.desc}</p>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                          {t.steps.map((step, i) => (
                            <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                              <span style={{ fontSize: 11, color: '#64748b', background: '#f1f5f9', padding: '3px 8px', borderRadius: 4 }}>{step}</span>
                              {i < t.steps.length - 1 && <ArrowRight size={10} color="#94a3b8" />}
                            </div>
                          ))}
                        </div>
                      </div>
                      <div style={{ padding: '10px 16px', borderTop: '1px solid #f1f5f9', display: 'flex', alignItems: 'center', justifyContent: 'space-between', background: '#fafafa' }}>
                        <span style={{ fontSize: 11, color: '#94a3b8' }}>{t.nodes.length} nodes</span>
                        <span style={{ fontSize: 12, fontWeight: 600, color: t.color, display: 'flex', alignItems: 'center', gap: 4 }}>
                          Use Template <ChevronRight size={14} />
                        </span>
                      </div>
                    </button>
                  );
                })}
              </div>

              {/* Bottom Actions */}
              <div style={{ display: 'flex', gap: 12, marginTop: 16 }}>
                <button
                  onClick={startFromScratch}
                  style={{
                    flex: 1,
                    padding: 14,
                    background: '#fff',
                    border: '2px dashed #d1d5db',
                    borderRadius: 10,
                    cursor: 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    gap: 8,
                    fontSize: 14,
                    fontWeight: 600,
                    color: '#475569',
                    transition: 'all 0.15s',
                  }}
                  onMouseEnter={e => { e.currentTarget.style.borderColor = '#2563eb'; e.currentTarget.style.color = '#2563eb'; }}
                  onMouseLeave={e => { e.currentTarget.style.borderColor = '#d1d5db'; e.currentTarget.style.color = '#475569'; }}
                >
                  <Plus size={18} /> Start from Scratch
                </button>
                <button
                  onClick={() => setModal('help')}
                  style={{
                    flex: 1,
                    padding: 14,
                    background: '#f8fafc',
                    border: '1px solid #e2e8f0',
                    borderRadius: 10,
                    cursor: 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    gap: 8,
                    fontSize: 14,
                    fontWeight: 600,
                    color: '#475569',
                    transition: 'all 0.15s',
                  }}
                  onMouseEnter={e => { e.currentTarget.style.background = '#fff'; }}
                  onMouseLeave={e => { e.currentTarget.style.background = '#f8fafc'; }}
                >
                  <BookOpen size={18} /> Learn How It Works
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Run Input Modal */}
      {modal === 'run-input' && (() => {
        const entry = nodes.find(n => n.data.isEntry) || nodes[0];
        if (!entry) return null;

        // Build execution flow
        const getExecutionFlow = () => {
          const flow: string[] = [entry.id];
          const visited = new Set([entry.id]);
          let current = entry.id;

          while (true) {
            const outEdge = edges.find(e => e.source === current);
            if (!outEdge || visited.has(outEdge.target)) break;
            flow.push(outEdge.target);
            visited.add(outEdge.target);
            current = outEdge.target;
          }
          return flow;
        };

        const executionFlow = getExecutionFlow();

        return (
          <div
            style={{ position: 'fixed', inset: 0, background: 'rgba(15,23,42,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100 }}
            onClick={() => !isRunning && setModal(null)}
          >
            <div
              style={{ background: '#fff', borderRadius: 12, width: 600, maxWidth: '95%', maxHeight: '90vh', overflow: 'hidden', boxShadow: '0 25px 50px rgba(0,0,0,0.25)' }}
              onClick={e => e.stopPropagation()}
            >
              <div style={{ padding: '20px 24px', borderBottom: '1px solid #e2e8f0' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                  <div>
                    <h2 style={{ fontSize: 18, fontWeight: 700, color: '#0f172a', margin: '0 0 4px 0' }}>
                      {isRunning ? 'Running Agent...' : `Run ${name}`}
                    </h2>
                    <p style={{ fontSize: 13, color: '#64748b', margin: 0 }}>
                      {isRunning ? 'Processing your request, please wait...' : 'Provide input data for the agent to process'}
                    </p>
                  </div>
                  {!isRunning && (
                    <button onClick={() => setModal(null)} style={{ padding: 8, background: '#f1f5f9', border: 'none', borderRadius: 6, cursor: 'pointer' }}>
                      <X size={18} color="#64748b" />
                    </button>
                  )}
                </div>
              </div>

              <div style={{ padding: 20, maxHeight: 'calc(90vh - 180px)', overflow: 'auto' }}>
                {/* Execution Flow Preview */}
                <div style={{ marginBottom: 20 }}>
                  <div style={{ fontSize: 12, fontWeight: 600, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: 10 }}>
                    Execution Flow
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', background: '#f8fafc', padding: 12, borderRadius: 8 }}>
                    {executionFlow.map((nodeId, i) => {
                      const node = nodes.find(n => n.id === nodeId);
                      if (!node) return null;
                      const cfg = nodeConfig[node.data.nodeType as NodeType];
                      const Icon = cfg.icon;
                      return (
                        <div key={nodeId} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                          <div style={{
                            display: 'flex', alignItems: 'center', gap: 6,
                            background: '#fff', border: '1px solid #e2e8f0', borderRadius: 6, padding: '6px 10px',
                          }}>
                            <Icon size={14} color={cfg.color} />
                            <span style={{ fontSize: 12, color: '#334155', fontWeight: 500 }}>{node.data.label}</span>
                          </div>
                          {i < executionFlow.length - 1 && <ArrowRight size={14} color="#94a3b8" />}
                        </div>
                      );
                    })}
                  </div>
                </div>

                {/* Input Fields */}
                <div>
                  <div style={{ fontSize: 12, fontWeight: 600, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: 10 }}>
                    Input Data for "{entry.data.label}"
                  </div>

                  {entry.data.inputKeys.length === 0 ? (
                    <div style={{ background: '#fefce8', border: '1px solid #fef08a', borderRadius: 8, padding: 14, fontSize: 13, color: '#854d0e' }}>
                      <strong>No input keys defined.</strong> Click the start node and add input keys to specify what data this agent needs.
                    </div>
                  ) : (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                      {entry.data.inputKeys.map((key: string) => (
                        <div key={key}>
                          <label style={{ display: 'block', fontSize: 13, fontWeight: 600, color: '#334155', marginBottom: 6 }}>
                            {key}
                          </label>
                          <textarea
                            value={runInput[key] || ''}
                            onChange={e => setRunInput(prev => ({ ...prev, [key]: e.target.value }))}
                            placeholder={key === 'url' ? 'https://www.koushith.in' : `Enter ${key}...`}
                            rows={key.includes('content') || key.includes('text') || key.includes('ticket') ? 4 : 2}
                            style={{
                              width: '100%',
                              padding: '10px 12px',
                              border: '1px solid #d1d5db',
                              borderRadius: 6,
                              fontSize: 14,
                              color: '#1e293b',
                              background: '#fff',
                              resize: 'vertical',
                              fontFamily: 'inherit',
                            }}
                          />
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                {/* What happens next */}
                <div style={{ marginTop: 20, background: '#f0f9ff', border: '1px solid #bae6fd', borderRadius: 8, padding: 14 }}>
                  <div style={{ fontSize: 12, fontWeight: 600, color: '#0369a1', marginBottom: 6 }}>What happens when you run:</div>
                  <ol style={{ margin: 0, paddingLeft: 20, fontSize: 12, color: '#0c4a6e', lineHeight: 1.6 }}>
                    <li>Your input is sent to <strong>"{entry.data.label}"</strong></li>
                    <li>Each node processes data and passes results to the next</li>
                    <li>The final output comes from the END node</li>
                  </ol>
                </div>
              </div>

              {/* Loading Overlay */}
              {isRunning && (
                <div style={{
                  padding: 40,
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'center',
                  justifyContent: 'center',
                  gap: 16,
                  background: '#f8fafc',
                  borderTop: '1px solid #e2e8f0',
                }}>
                  <Loader2 size={40} color="#16a34a" style={{ animation: 'spin 1s linear infinite' }} />
                  <div style={{ textAlign: 'center' }}>
                    <div style={{ fontSize: 16, fontWeight: 600, color: '#0f172a', marginBottom: 6 }}>Executing Agent</div>
                    <div style={{ fontSize: 13, color: '#64748b' }}>Processing {executionFlow.length} nodes...</div>
                  </div>
                  <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
                    {executionFlow.map((nodeId, i) => {
                      const node = nodes.find(n => n.id === nodeId);
                      if (!node) return null;
                      const cfg = nodeConfig[node.data.nodeType as NodeType];
                      return (
                        <div
                          key={nodeId}
                          style={{
                            width: 8,
                            height: 8,
                            borderRadius: 4,
                            background: cfg.color,
                            animation: `pulse 1.5s ease-in-out ${i * 0.2}s infinite`,
                          }}
                        />
                      );
                    })}
                  </div>
                </div>
              )}

              <div style={{ padding: '16px 20px', borderTop: '1px solid #e2e8f0', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontSize: 12, color: '#94a3b8' }}>
                  {isRunning ? 'Please wait...' : `${executionFlow.length} nodes will execute`}
                </span>
                <div style={{ display: 'flex', gap: 10 }}>
                  <button
                    onClick={() => setModal(null)}
                    disabled={isRunning}
                    style={{ ...btnSecondary, opacity: isRunning ? 0.5 : 1, cursor: isRunning ? 'not-allowed' : 'pointer' }}
                  >
                    Cancel
                  </button>
                  <button
                    onClick={executeAgent}
                    disabled={isRunning || (entry.data.inputKeys.length > 0 && Object.values(runInput).some(v => !v.trim()))}
                    style={{
                      ...btnPrimary,
                      background: isRunning ? '#9ca3af' : (entry.data.inputKeys.length > 0 && Object.values(runInput).some(v => !v.trim()) ? '#9ca3af' : '#16a34a'),
                      cursor: isRunning ? 'not-allowed' : 'pointer',
                    }}
                  >
                    {isRunning ? (
                      <>
                        <Loader2 size={16} style={{ animation: 'spin 1s linear infinite' }} /> Running...
                      </>
                    ) : (
                      <>
                        <Play size={16} /> Run Agent
                      </>
                    )}
                  </button>
                </div>
              </div>
            </div>
          </div>
        );
      })()}

      {/* Export Modal */}
      {modal === 'export' && (
        <div
          style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100 }}
          onClick={() => setModal(null)}
        >
          <div
            style={{ background: '#fff', borderRadius: 12, width: 750, maxWidth: '90%', maxHeight: '85vh', display: 'flex', flexDirection: 'column', boxShadow: '0 25px 50px rgba(0,0,0,0.25)' }}
            onClick={e => e.stopPropagation()}
          >
            <div style={{ padding: '20px 24px', borderBottom: '1px solid #e2e8f0' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                <div>
                  <h2 style={{ fontSize: 18, fontWeight: 700, color: '#0f172a', margin: 0 }}>Export Python Code</h2>
                  <p style={{ fontSize: 13, color: '#64748b', margin: '4px 0 0 0' }}>Ready to run with Hive Framework</p>
                </div>
                <button onClick={() => setModal(null)} style={{ padding: 8, background: '#f1f5f9', border: 'none', borderRadius: 6, cursor: 'pointer' }}>
                  <X size={18} color="#64748b" />
                </button>
              </div>
            </div>

            {/* Usage Instructions */}
            <div style={{ padding: '12px 24px', background: '#f8fafc', borderBottom: '1px solid #e2e8f0' }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: '#64748b', marginBottom: 6 }}>How to use this code:</div>
              <div style={{ display: 'flex', gap: 20, fontSize: 12, color: '#475569' }}>
                <div><span style={{ fontWeight: 600 }}>1.</span> Save as <code style={{ background: '#e2e8f0', padding: '1px 4px', borderRadius: 3 }}>{name.toLowerCase().replace(/\s+/g, '_')}_agent.py</code></div>
                <div><span style={{ fontWeight: 600 }}>2.</span> Run: <code style={{ background: '#e2e8f0', padding: '1px 4px', borderRadius: 3 }}>python {name.toLowerCase().replace(/\s+/g, '_')}_agent.py run '{"{...}"}'</code></div>
              </div>
            </div>

            <div style={{ flex: 1, overflow: 'auto', padding: 20 }}>
              <pre
                className="language-python"
                style={{
                  background: '#1d1f21',
                  borderRadius: 8,
                  padding: 20,
                  fontSize: 12,
                  fontFamily: "'Fira Code', 'JetBrains Mono', Menlo, Monaco, 'Courier New', monospace",
                  whiteSpace: 'pre-wrap',
                  margin: 0,
                  lineHeight: 1.6,
                  overflow: 'auto',
                }}
              >
                <code
                  className="language-python"
                  dangerouslySetInnerHTML={{ __html: Prism.highlight(code, Prism.languages.python, 'python') }}
                />
              </pre>
            </div>
            <div style={{ padding: '16px 24px', borderTop: '1px solid #e2e8f0', display: 'flex', justifyContent: 'flex-end', gap: 12 }}>
              <button
                onClick={() => { navigator.clipboard.writeText(code); setCopied(true); setTimeout(() => setCopied(false), 2000); }}
                style={btnSecondary}
              >
                {copied ? <Check size={16} /> : <Copy size={16} />}
                {copied ? 'Copied!' : 'Copy Code'}
              </button>
              <button
                onClick={() => {
                  const b = new Blob([code], { type: 'text/plain' });
                  const a = document.createElement('a');
                  a.href = URL.createObjectURL(b);
                  a.download = `${name.toLowerCase().replace(/\s+/g, '_')}_agent.py`;
                  a.click();
                }}
                style={btnPrimary}
              >
                <Download size={16} /> Download .py File
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Result Modal */}
      {modal === 'result' && runResult && (
        <div
          style={{ position: 'fixed', inset: 0, background: 'rgba(15,23,42,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100 }}
          onClick={() => setModal(null)}
        >
          <div
            style={{ background: '#fff', borderRadius: 12, width: 520, maxWidth: '95%', maxHeight: '85vh', overflow: 'hidden', boxShadow: '0 25px 50px rgba(0,0,0,0.25)' }}
            onClick={e => e.stopPropagation()}
          >
            <div style={{
              padding: '20px 24px',
              background: runResult.success ? '#f0fdf4' : '#fef2f2',
              borderBottom: `1px solid ${runResult.success ? '#bbf7d0' : '#fecaca'}`,
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <div style={{
                  width: 40,
                  height: 40,
                  borderRadius: 10,
                  background: runResult.success ? '#22c55e' : '#ef4444',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                }}>
                  {runResult.success ? <Check size={20} color="#fff" /> : <X size={20} color="#fff" />}
                </div>
                <div>
                  <h2 style={{ fontSize: 18, fontWeight: 700, color: '#0f172a', margin: 0 }}>
                    {runResult.success ? 'Agent Execution Complete' : 'Execution Failed'}
                  </h2>
                  <p style={{ fontSize: 13, color: '#64748b', margin: '2px 0 0 0' }}>
                    {runResult.success
                      ? `${runResult.nodesExecuted || nodes.length} nodes executed successfully`
                      : 'An error occurred during execution'
                    }
                  </p>
                </div>
              </div>
            </div>

            <div style={{ padding: 20, maxHeight: 'calc(85vh - 180px)', overflow: 'auto' }}>
              {runResult.success && runResult.output && (
                <div>
                  <label style={{ ...labelStyle, marginBottom: 8 }}>Final Output</label>
                  <pre style={{
                    background: '#1e293b',
                    color: '#e2e8f0',
                    borderRadius: 8,
                    padding: 16,
                    fontSize: 12,
                    fontFamily: 'monospace',
                    whiteSpace: 'pre-wrap',
                    margin: 0,
                    maxHeight: 280,
                    overflow: 'auto',
                  }}>
                    {JSON.stringify(runResult.output, null, 2)}
                  </pre>
                </div>
              )}

              {runResult.error && (
                <div>
                  <label style={{ ...labelStyle, marginBottom: 8, color: '#991b1b' }}>Error Details</label>
                  <div style={{ background: '#fef2f2', border: '1px solid #fecaca', borderRadius: 8, padding: 14 }}>
                    <pre style={{ margin: 0, fontSize: 12, fontFamily: 'monospace', color: '#991b1b', whiteSpace: 'pre-wrap' }}>
                      {runResult.error}
                    </pre>
                  </div>
                </div>
              )}

              {/* What's Next */}
              {runResult.success && (
                <div style={{ marginTop: 16, background: '#f0f9ff', border: '1px solid #bae6fd', borderRadius: 8, padding: 14 }}>
                  <div style={{ fontSize: 12, fontWeight: 600, color: '#0369a1', marginBottom: 8 }}>What's Next?</div>
                  <div style={{ fontSize: 12, color: '#0c4a6e', lineHeight: 1.6 }}>
                    Your agent works! Export it as Python code to run it anywhere, or run again with different input.
                  </div>
                </div>
              )}
            </div>

            <div style={{ padding: '14px 20px', borderTop: '1px solid #e2e8f0', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <button onClick={() => setModal(null)} style={{ ...btnSecondary, padding: '8px 12px', fontSize: 13 }}>
                Close
              </button>
              <div style={{ display: 'flex', gap: 10 }}>
                <button onClick={() => showRunModal()} style={btnSecondary}>
                  <Play size={14} /> Run Again
                </button>
                <button onClick={() => setModal('export')} style={btnPrimary}>
                  <FileCode size={14} /> Export Agent
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
