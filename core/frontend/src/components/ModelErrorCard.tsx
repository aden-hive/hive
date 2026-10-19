import { useState } from "react";
import { AlertTriangle, ChevronRight } from "lucide-react";
import { openSettings } from "@/lib/settings-events";

// The runtime's text for a failed model call (AgentLoop's visible_error).
const MODEL_ERROR = /^\s*\[Error: LLM call failed: ([\s\S]*?)(?:\. Please try again\.)?\]\s*$/;
const KEY_PROBLEM = /AuthenticationError|api[_ -]?key|\b401\b|unauthori[sz]ed|permission denied/i;

export interface ModelError {
  /** The provider's error, as the runtime reported it. */
  detail: string;
  /** The key is missing or was rejected (so the fix is in the model settings). */
  keyProblem: boolean;
}

/** A queen message that is really a failed model call, or null for any other text. */
export function parseModelError(content: string): ModelError | null {
  const m = MODEL_ERROR.exec(content);
  if (!m) return null;
  return { detail: m[1].trim(), keyProblem: KEY_PROBLEM.test(m[1]) };
}

/** A failed model call in the chat: what went wrong in a sentence, the way to
 *  the model settings, and the raw error folded away. */
export default function ModelErrorCard({ error }: { error: ModelError }) {
  const [open, setOpen] = useState(false);
  return (
    // Flat: it sits inside the queen's message bubble, which already frames it.
    <div className="text-xs">
      <div className="flex items-start gap-3">
        <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-red-500/10 text-red-500">
          <AlertTriangle className="h-3.5 w-3.5" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-foreground">
            <span className="font-medium">The model couldn't reply.</span>{" "}
            <span className="text-muted-foreground">
              {error.keyProblem ? "Its API key is missing or was rejected." : "The provider returned an error."}
            </span>
          </p>
          <div className="mt-1.5 flex items-center gap-4">
            <button
              type="button"
              onClick={() => openSettings("byok")}
              className="font-medium text-primary underline-offset-2 hover:underline"
            >
              {error.keyProblem ? "Set up a model →" : "Model settings →"}
            </button>
            <button
              type="button"
              onClick={() => setOpen((o) => !o)}
              aria-expanded={open}
              className="inline-flex items-center gap-0.5 text-muted-foreground hover:text-foreground"
            >
              <ChevronRight className={`h-3 w-3 transition-transform ${open ? "rotate-90" : ""}`} />
              Details
            </button>
          </div>
          {open && (
            <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap break-words rounded-md bg-muted/50 p-2 font-mono text-[11px] text-muted-foreground">
              {error.detail}
            </pre>
          )}
        </div>
      </div>
    </div>
  );
}
