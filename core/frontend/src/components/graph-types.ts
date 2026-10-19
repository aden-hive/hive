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

