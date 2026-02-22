import { api } from "./client";
import type { NodeSpec, NodeDetail, NodeCriteria } from "./types";

export const graphsApi = {
  nodes: (agentId: string, graphId: string, sessionId?: string) =>
    api.get<{ nodes: NodeSpec[] }>(
      `/agents/${agentId}/graphs/${graphId}/nodes${sessionId ? `?session_id=${sessionId}` : ""}`,
    ),

  node: (agentId: string, graphId: string, nodeId: string) =>
    api.get<NodeDetail>(
      `/agents/${agentId}/graphs/${graphId}/nodes/${nodeId}`,
    ),

  nodeCriteria: (
    agentId: string,
    graphId: string,
    nodeId: string,
    sessionId?: string,
  ) =>
    api.get<NodeCriteria>(
      `/agents/${agentId}/graphs/${graphId}/nodes/${nodeId}/criteria${sessionId ? `?session_id=${sessionId}` : ""}`,
    ),
};
