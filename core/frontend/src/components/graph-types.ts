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

export type RunState = "idle" | "deploying" | "running";

export interface RunButtonProps {
  runState: RunState;
  disabled: boolean;
  onRun: () => void;
  onPause: () => void;
  btnRef: React.Ref<HTMLButtonElement>;
}
