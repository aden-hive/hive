import type { GoalProgress } from "@/api/types";

export interface GoalCriterion {
  criterion_id: string;
  description: string;
  met: boolean;
  progress: number;
  evidence: string[];
}

export interface NormalizedGoalProgress {
  overall_progress: number;
  progress: number;
  criteria_status: Record<string, GoalCriterion>;
  criteria: GoalCriterion[];
  constraint_violations: Array<Record<string, unknown>>;
  metrics: Record<string, unknown>;
  recommendation: string;
  updated_at: string | null;
}

function clampProgress(value: unknown): number {
  if (typeof value !== "number" || Number.isNaN(value)) return 0;
  return Math.max(0, Math.min(1, value));
}

export function normalizeGoalProgress(payload: GoalProgress | Record<string, unknown> | null | undefined): NormalizedGoalProgress {
  const raw = (payload ?? {}) as Record<string, unknown>;
  const overallProgress = clampProgress(raw.overall_progress ?? raw.progress);
  const rawCriteriaStatus = raw.criteria_status && typeof raw.criteria_status === "object"
    ? (raw.criteria_status as Record<string, Record<string, unknown>>)
    : {};

  const criteriaFromStatus: GoalCriterion[] = Object.entries(rawCriteriaStatus).map(([criterionId, status]) => ({
    criterion_id: criterionId,
    description: typeof status.description === "string" ? status.description : criterionId,
    met: Boolean(status.met),
    progress: clampProgress(status.progress),
    evidence: Array.isArray(status.evidence) ? status.evidence.filter((item): item is string => typeof item === "string") : [],
  }));

  const rawCriteria = Array.isArray(raw.criteria) ? raw.criteria : null;
  const criteria = (rawCriteria ?? criteriaFromStatus).map((criterion, index) => {
    const item = (criterion ?? {}) as Record<string, unknown>;
    const fallbackId = criteriaFromStatus[index]?.criterion_id ?? `criterion_${index + 1}`;
    return {
      criterion_id: typeof item.criterion_id === "string" ? item.criterion_id : fallbackId,
      description: typeof item.description === "string" ? item.description : criteriaFromStatus[index]?.description ?? fallbackId,
      met: typeof item.met === "boolean" ? item.met : Boolean(criteriaFromStatus[index]?.met),
      progress: clampProgress(item.progress ?? criteriaFromStatus[index]?.progress ?? 0),
      evidence: Array.isArray(item.evidence)
        ? item.evidence.filter((entry): entry is string => typeof entry === "string")
        : (criteriaFromStatus[index]?.evidence ?? []),
    } satisfies GoalCriterion;
  });

  const criteriaStatus = criteria.reduce<Record<string, GoalCriterion>>((acc, criterion) => {
    acc[criterion.criterion_id] = criterion;
    return acc;
  }, { ...Object.fromEntries(criteriaFromStatus.map((criterion) => [criterion.criterion_id, criterion])) });

  return {
    overall_progress: overallProgress,
    progress: overallProgress,
    criteria_status: criteriaStatus,
    criteria,
    constraint_violations: Array.isArray(raw.constraint_violations)
      ? (raw.constraint_violations as Array<Record<string, unknown>>)
      : [],
    metrics: raw.metrics && typeof raw.metrics === "object"
      ? (raw.metrics as Record<string, unknown>)
      : {},
    recommendation: typeof raw.recommendation === "string" ? raw.recommendation : "continue",
    updated_at: typeof raw.updated_at === "string" ? raw.updated_at : null,
  };
}

export function goalProgressSummary(progress: NormalizedGoalProgress | null | undefined): string {
  if (!progress) return "No goal progress yet";
  if (progress.recommendation === "complete") return "Goal is essentially complete";
  if (progress.recommendation === "adjust") return "Execution may need adjustment";
  const metCount = progress.criteria.filter((criterion) => criterion.met).length;
  if (progress.criteria.length > 0) {
    return `${metCount}/${progress.criteria.length} success criteria satisfied`;
  }
  return "Tracking execution progress";
}
