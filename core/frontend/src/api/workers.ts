import { api } from "./client";
import type { GraphTopology, NodeDetail, NodeCriteria, ToolInfo } from "./types";

export const workersApi = {
  nodes: (sessionId: string, colonyId: string, workerSessionId?: string) =>
    api.get<GraphTopology>(
      `/sessions/${sessionId}/colonies/${colonyId}/nodes${workerSessionId ? `?session_id=${workerSessionId}` : ""}`,
    ),

  node: (sessionId: string, colonyId: string, nodeId: string) =>
    api.get<NodeDetail>(
      `/sessions/${sessionId}/colonies/${colonyId}/nodes/${nodeId}`,
    ),

  nodeCriteria: (
    sessionId: string,
    colonyId: string,
    nodeId: string,
    workerSessionId?: string,
  ) =>
    api.get<NodeCriteria>(
      `/sessions/${sessionId}/colonies/${colonyId}/nodes/${nodeId}/criteria${workerSessionId ? `?session_id=${workerSessionId}` : ""}`,
    ),

  nodeTools: (sessionId: string, colonyId: string, nodeId: string) =>
    api.get<{ tools: ToolInfo[] }>(
      `/sessions/${sessionId}/colonies/${colonyId}/nodes/${nodeId}/tools`,
    ),
};
