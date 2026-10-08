import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import QueenDisconnectDialog from "@/components/QueenDisconnectDialog";

/** Same shape we accept in the connect prompt — the SSE listener passes
 * its event ``data`` record and ``credentials.tsx`` passes the account
 * object it already has on hand. */
export type AccountHint = {
  alias?: string;
  identity?: { email?: string | null } | null;
} | null | undefined;

interface QueenDisconnectPromptContextValue {
  /** ``onConfirm`` is invoked after the dialog has finished writing the
   * queen sidecars. The credentials page passes a deleter that calls
   * ``credentialsApi.delete``; the SSE path leaves it undefined since
   * the credential has already been removed elsewhere. */
  openPrompt: (
    provider: string,
    account: AccountHint,
    onConfirm?: () => Promise<void>,
  ) => void;
}

const QueenDisconnectPromptContext =
  createContext<QueenDisconnectPromptContextValue | null>(null);

/** Mirrors the connect prompt's dedup window. When the user clicks
 * Remove inside the app we delete the credential, which fires a paired
 * ``credential_provider_disconnected`` SSE microseconds later. Suppress
 * the second open for the same ``${provider}:${alias}`` key inside the
 * window so the user doesn't see the dialog twice. */
const DEDUP_WINDOW_MS = 30_000;

interface ActivePrompt {
  provider: string;
  accountEmail: string | null;
  onConfirm?: () => Promise<void>;
  key: string;
}

export function QueenDisconnectPromptProvider({
  children,
}: {
  children: ReactNode;
}) {
  const [active, setActive] = useState<ActivePrompt | null>(null);
  const lastKeyRef = useRef<{ key: string; at: number } | null>(null);

  const openPrompt = useCallback(
    (
      provider: string,
      account: AccountHint,
      onConfirm?: () => Promise<void>,
    ) => {
      const alias = account?.alias ?? "";
      const key = `${provider}:${alias}`;
      const now = Date.now();
      const last = lastKeyRef.current;
      if (last && last.key === key && now - last.at < DEDUP_WINDOW_MS) {
        return;
      }
      lastKeyRef.current = { key, at: now };
      const email = account?.identity?.email ?? alias ?? null;
      setActive({ provider, accountEmail: email, onConfirm, key });
    },
    [],
  );

  const value = useMemo(() => ({ openPrompt }), [openPrompt]);

  return (
    <QueenDisconnectPromptContext.Provider value={value}>
      {children}
      <QueenDisconnectDialog
        open={active !== null}
        provider={active?.provider ?? ""}
        accountEmail={active?.accountEmail ?? null}
        onConfirm={active?.onConfirm}
        onClose={() => setActive(null)}
      />
    </QueenDisconnectPromptContext.Provider>
  );
}

export function useQueenDisconnectPrompt(): QueenDisconnectPromptContextValue {
  const ctx = useContext(QueenDisconnectPromptContext);
  if (!ctx) {
    throw new Error(
      "useQueenDisconnectPrompt must be used within QueenDisconnectPromptProvider",
    );
  }
  return ctx;
}
