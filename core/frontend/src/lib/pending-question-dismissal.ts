export interface PendingQuestion {
  id: string;
  prompt: string;
  options?: string[];
}

const dismissedQuestionSetBySession = new Map<string, string>();

function questionSetKey(questions: PendingQuestion[]): string {
  return JSON.stringify(
    questions.map((question) => question.id || question.prompt).sort(),
  );
}

export function rememberDismissedQuestions(
  sessionId: string | null,
  questions: PendingQuestion[] | null,
): void {
  if (!sessionId || !questions || questions.length === 0) return;
  dismissedQuestionSetBySession.set(sessionId, questionSetKey(questions));
}

export function isQuestionSetDismissed(
  sessionId: string | null,
  questions: PendingQuestion[] | null,
): boolean {
  if (!sessionId || !questions || questions.length === 0) return false;
  return dismissedQuestionSetBySession.get(sessionId) === questionSetKey(questions);
}

export function clearDismissedQuestions(sessionId: string | null): void {
  if (!sessionId) return;
  dismissedQuestionSetBySession.delete(sessionId);
}
