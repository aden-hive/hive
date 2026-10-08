/**
 * A composer draft handed from one screen to another across an in-app
 * navigation.
 *
 * **Why this exists.** Attachment uploads are session-scoped
 * (`uploadAttachment(sessionId, …)`), so a screen that has something to say
 * *before* a session exists — the CRM configure dialog, which navigates to the
 * page that creates the session — has nowhere to put a file. Rather than
 * teaching that screen to create sessions, upload, and send (three flows it
 * would then own a second copy of), it stages the draft here and the
 * destination sends it through the composer it already has, once its session is
 * live. No new API, one implementation of upload/send.
 *
 * **Why module state and not `userStorage.session`.** The payload carries real
 * `File` objects, which don't survive serialization — and files are the entire
 * reason this exists. Module state survives an SPA route change, which is the
 * only hop being made. A hard reload legitimately drops it; the `File` handles
 * would be dead anyway. Mirrors ChatPanel's own module-level `draftStore`,
 * which persists composer text across unmount for the same reason.
 */
export interface ComposerHandoff {
  /** Message body to send once the destination has a session. */
  text: string;
  /** Files to attach. Uploaded by the destination, through the normal path. */
  files: File[];
  /** Distinct per staging, so a consumer can apply each handoff exactly once
   *  even if its effects re-run. */
  token: number;
}

const staged = new Map<string, ComposerHandoff>();
let nextToken = 1;

/** Stage a draft for `key` (a queen id). Replaces any previous one — the user
 *  submitted twice, and only the latest submission is real. */
export function stageComposerHandoff(key: string, text: string, files: File[]): void {
  staged.set(key, { text, files, token: nextToken++ });
}

/** Read the staged draft for `key` without consuming it. Read and clear are
 *  separate so a consumer can commit to sending BEFORE dropping the draft, and
 *  a re-entered effect that bails early doesn't lose the user's message —
 *  the same read-then-commit shape queen-dm uses for `queenFirstMessage`. */
export function peekComposerHandoff(key: string): ComposerHandoff | null {
  return staged.get(key) ?? null;
}

/** Drop the staged draft for `key`, once the destination has taken ownership. */
export function clearComposerHandoff(key: string): void {
  staged.delete(key);
}
