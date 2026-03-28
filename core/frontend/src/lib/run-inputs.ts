import type { NodeSpec } from "@/api/types";
import type { GraphNode } from "@/components/graph-types";

const GENERIC_ENTRY_KEYS = new Set(["task", "user_request", "feedback"]);
const RUNNABLE_PHASES = new Set(["staging", "running"]);

type QueenPhase = "planning" | "building" | "staging" | "running";

function isMeaningfulValue(value: unknown): boolean {
  if (typeof value === "string") return value.trim().length > 0;
  return value !== undefined && value !== null;
}

export function getStructuredRunInputKeys(
  nodeSpecs: NodeSpec[],
  graphNodes: GraphNode[],
): string[] {
  const entryNodeId =
    graphNodes.find((node) => node.nodeType !== "trigger")?.id ?? nodeSpecs[0]?.id;
  if (!entryNodeId) return [];

  const entrySpec = nodeSpecs.find((node) => node.id === entryNodeId) ?? nodeSpecs[0];
  return (entrySpec?.input_keys ?? []).filter((key) => !GENERIC_ENTRY_KEYS.has(key));
}

export function hasAllStructuredRunInputs(
  keys: string[],
  inputData: Record<string, unknown> | null | undefined,
): inputData is Record<string, unknown> {
  if (!inputData) return false;
  return keys.every((key) => isMeaningfulValue(inputData[key]));
}

export function buildStructuredRunQuestions(keys: string[]) {
  return keys.map((key) => ({
    id: key,
    prompt: `Provide ${key} for this run.`,
  }));
}

export function trimStructuredRunInputs(
  keys: string[],
  inputData: Record<string, unknown> | null | undefined,
): Record<string, unknown> {
  if (!inputData) return {};
  return Object.fromEntries(keys.flatMap((key) => (key in inputData ? [[key, inputData[key]]] : [])));
}

export function canShowRunButton(
  sessionId: string | null | undefined,
  ready: boolean | null | undefined,
  queenPhase: QueenPhase | null | undefined,
  topologyReady: boolean,
): boolean {
  return Boolean(sessionId && ready && topologyReady && queenPhase && RUNNABLE_PHASES.has(queenPhase));
}
