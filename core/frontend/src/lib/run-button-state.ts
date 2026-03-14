export type QueenPhase = "planning" | "building" | "staging" | "running";

export function isRunButtonDisabled(
  nodeCount: number,
  queenPhase?: QueenPhase,
): boolean {
  return (
    nodeCount === 0
    || queenPhase === "planning"
    || queenPhase === "building"
  );
}
