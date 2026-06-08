import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Loader2 } from "lucide-react";
import { messagesApi } from "@/api/messages";
import { useColony } from "@/context/ColonyContext";

/**
 * Transient routing screen the user lands on right after submitting from the
 * home page. Reads the pending prompt from sessionStorage, runs queen
 * classification, and redirects (replace) to the resolved queen DM with
 * ?new=1 so the existing bootstrap flow takes over.
 *
 * The point of this page is to get the user out of the home screen *before*
 * the classify LLM call runs — they should never sit on the home page
 * watching a spinner.
 */
export const PENDING_CLASSIFY_KEY = "hive:pendingClassifyMessage";

export default function QueenRouting() {
  const navigate = useNavigate();
  const { refresh } = useColony();
  const [error, setError] = useState<string | null>(null);
  // Re-runs of this effect (StrictMode, fast re-mounts) must not re-fire the
  // classify call — once we've grabbed the pending message we own it.
  const startedRef = useRef(false);

  useEffect(() => {
    if (startedRef.current) return;
    startedRef.current = true;

    let pending: string | null = null;
    try {
      pending = sessionStorage.getItem(PENDING_CLASSIFY_KEY);
      if (pending) sessionStorage.removeItem(PENDING_CLASSIFY_KEY);
    } catch {
      pending = null;
    }

    if (!pending || !pending.trim()) {
      navigate("/", { replace: true });
      return;
    }

    const trimmed = pending.trim();
    let cancelled = false;
    (async () => {
      try {
        const { queen_id } = await messagesApi.classify(trimmed);
        if (cancelled) return;
        // Hand the prompt off to queen-dm via the same key its bootstrap
        // path already consumes. Avoids leaking the message into the URL.
        sessionStorage.setItem(`queenFirstMessage:${queen_id}`, trimmed);
        refresh();
        navigate(`/queen/${queen_id}?new=1`, { replace: true });
      } catch {
        if (cancelled) return;
        setError("Couldn't route your request. Try again from the home screen.");
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [navigate, refresh]);

  return (
    <div className="flex-1 flex flex-col items-center justify-center p-6">
      <div className="flex items-center gap-3 text-muted-foreground">
        <Loader2 className="w-5 h-5 animate-spin" />
        <span className="queen-debate-line text-sm">
          <span>The queens are debating who should take this on</span>
          <span aria-hidden="true">
            {[0, 1, 2].map((dot) => (
              <span key={dot}>.</span>
            ))}
          </span>
        </span>
      </div>
      {error && (
        <div className="mt-6 flex flex-col items-center gap-3">
          <p className="text-sm text-destructive">{error}</p>
          <button
            onClick={() => navigate("/", { replace: true })}
            className="text-xs text-muted-foreground hover:text-foreground border border-border/50 hover:border-primary/30 rounded-full px-3.5 py-1.5 transition-all"
          >
            Back to home
          </button>
        </div>
      )}
    </div>
  );
}
