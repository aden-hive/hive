import { api } from "./client";
import type { GraphTopology, NodeDetail, NodeCriteria, ToolInfo } from "./types";

export const graphsApi = {
  nodes: (sessionId: string, graphId: string, workerSessionId?: string) =>
    api.get<GraphTopology>(
      `/sessions/${sessionId}/graphs/${graphId}/nodes${workerSessionId ? `?session_id=${workerSessionId}` : ""}`,
    ),

  node: (sessionId: string, graphId: string, nodeId: string) =>
    api.get<NodeDetail>(
      `/sessions/${sessionId}/graphs/${graphId}/nodes/${nodeId}`,
    ),

  nodeCriteria: (
    sessionId: string,
    graphId: string,
    nodeId: string,
    workerSessionId?: string,
  ) =>
    api.get<NodeCriteria>(
      `/sessions/${sessionId}/graphs/${graphId}/nodes/${nodeId}/criteria${workerSessionId ? `?session_id=${workerSessionId}` : ""}`,
    ),

  nodeTools: (sessionId: string, graphId: string, nodeId: string) =>
    api.get<{ tools: ToolInfo[] }>(
      `/sessions/${sessionId}/graphs/${graphId}/nodes/${nodeId}/tools`,
    ),
};
