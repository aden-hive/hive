import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import QueensAuthorizationDialog from "@/components/QueensAuthorizationDialog";

/** Minimal shape we accept from the two trigger sources. ``credentials.tsx``
 * passes an account info dict; the SSE listener passes its event ``data``
 * record. Both include an ``alias`` field; ``identity.email`` is best-effort
 * only and may be absent. */
export type AccountHint = {
  alias?: string;
  identity?: { email?: string | null } | null;
} | null | undefined;

interface QueensAuthorizationPromptContextValue {
  openPrompt: (provider: string, account: AccountHint) => void;
  /** Mute the next queens-authorization prompt for ``provider`` (within a
   * short window). Used when a credential is connected for a purpose that
   * has nothing to do with granting queens its tools — e.g. Sentinel saving
   * a Slack token purely to send notification messages. */
  suppressNext: (provider: string) => void;
}

const QueensAuthorizationPromptContext =
  createContext<QueensAuthorizationPromptContextValue | null>(null);

/** Dedup window: the in-app Connect path fires `runResyncCheck` success
 * AND a paired `credential_provider_connected` SSE event microseconds
 * later. Suppress the second open for the same `${provider}:${alias}` key
 * if it lands inside this window. 30s is generous — the second event is
 * always near-instant; the long tail covers manual re-test scenarios. */
const DEDUP_WINDOW_MS = 30_000;

interface ActivePrompt {
  provider: string;
  accountEmail: string | null;
  /** Key used for dedup. Stays valid until the next open with a new key. */
  key: string;
}

export function QueensAuthorizationPromptProvider({
  children,
}: {
  children: ReactNode;
}) {
  const [active, setActive] = useState<ActivePrompt | null>(null);
  const lastKeyRef = useRef<{ key: string; at: number } | null>(null);
  // provider → timestamp it was suppressed; the next openPrompt for that
  // provider inside DEDUP_WINDOW_MS is swallowed and the entry cleared.
  const suppressedRef = useRef<Map<string, number>>(new Map());

  const suppressNext = useCallback((provider: string) => {
    suppressedRef.current.set(provider, Date.now());
  }, []);

  const openPrompt = useCallback(
    (provider: string, account: AccountHint) => {
      const now = Date.now();
      const suppressedAt = suppressedRef.current.get(provider);
      if (suppressedAt != null && now - suppressedAt < DEDUP_WINDOW_MS) {
        suppressedRef.current.delete(provider);
        return;
      }
      const alias = account?.alias ?? "";
      const key = `${provider}:${alias}`;
      const last = lastKeyRef.current;
      if (last && last.key === key && now - last.at < DEDUP_WINDOW_MS) {
        return;
      }
      lastKeyRef.current = { key, at: now };
      const email = account?.identity?.email ?? alias ?? null;
      setActive({ provider, accountEmail: email, key });
    },
    [],
  );

  const value = useMemo(
    () => ({ openPrompt, suppressNext }),
    [openPrompt, suppressNext],
  );

  return (
    <QueensAuthorizationPromptContext.Provider value={value}>
      {children}
      <QueensAuthorizationDialog
        open={active !== null}
        provider={active?.provider ?? ""}
        accountEmail={active?.accountEmail ?? null}
        onClose={() => setActive(null)}
      />
    </QueensAuthorizationPromptContext.Provider>
  );
}

export function useQueensAuthorizationPrompt(): QueensAuthorizationPromptContextValue {
  const ctx = useContext(QueensAuthorizationPromptContext);
  if (!ctx) {
    throw new Error(
      "useQueensAuthorizationPrompt must be used within QueensAuthorizationPromptProvider",
    );
  }
  return ctx;
}
