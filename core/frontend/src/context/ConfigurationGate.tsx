import { useCallback, useEffect, useState, type ReactNode } from "react";
import { configApi, type LLMConfig } from "@/api/config";
import { ApiError } from "@/api/client";
import FirstRun from "@/components/FirstRun";
import { useRuntime } from "@/context/RuntimeContext";

type GateState =
  | { kind: "loading" }
  | { kind: "needs-setup"; config: LLMConfig | null }
  | { kind: "ready"; config: LLMConfig }
  | { kind: "error"; message: string };

/**
 * Gates the main UI behind a check that the user has at least one working
 * LLM provider configured. If not, renders the first-run wizard. Once the
 * wizard completes (or if configuration already exists), renders children.
 *
 * The check itself is `GET /api/config/llm` → `has_api_key`. The runtime
 * considers the user configured when any provider key lives in the
 * encrypted credential store or an env var, so this naturally honours
 * existing installs.
 */
export function ConfigurationGate({ children }: { children: ReactNode }) {
  const runtime = useRuntime();
  const [state, setState] = useState<GateState>({ kind: "loading" });

  const refresh = useCallback(async () => {
    try {
      const config = await configApi.getLLMConfig();
      // A working BYOK provider (a real API key in the credential store or an
      // env var) is required. The managed "hive" cloud proxy isn't available
      // in a self-hosted runtime, so — unlike the desktop build — we do NOT
      // treat provider === "hive" as ready; a fresh install lands on the
      // provider picker instead of being stuck on hive-2.1.
      if (config.has_api_key) {
        setState({ kind: "ready", config });
      } else {
        setState({ kind: "needs-setup", config });
      }
    } catch (err) {
      const message =
        err instanceof ApiError
          ? `${err.status}: ${err.message}`
          : err instanceof Error
            ? err.message
            : String(err);
      setState({ kind: "error", message });
    }
  }, []);

  // Don't fetch until the runtime is actually listening. Otherwise the
  // first request races the `uv sync` + serve startup and the user sees
  // "Could not load configuration: 0: fetch failed" on every fresh
  // launch. The spinner stays put while we wait.
  useEffect(() => {
    if (runtime.status === "ready") {
      void refresh();
    } else if (runtime.status === "error") {
      setState({ kind: "error", message: runtime.error ?? "Runtime failed to start" });
    }
  }, [runtime.status, runtime.error, refresh]);

  if (state.kind === "loading") {
    return (
      <div className="flex items-center justify-center h-screen bg-background">
        <div className="flex flex-col items-center gap-4">
          <div className="w-8 h-8 border-2 border-primary/30 border-t-primary rounded-full animate-spin" />
          <p className="text-sm text-muted-foreground">Loading configuration…</p>
        </div>
      </div>
    );
  }

  if (state.kind === "error") {
    return (
      <div className="flex items-center justify-center h-screen bg-background">
        <div className="flex flex-col items-center gap-4 max-w-md text-center px-6">
          <div className="w-10 h-10 rounded-full bg-red-500/10 flex items-center justify-center">
            <span className="text-red-500 text-lg font-bold">!</span>
          </div>
          <p className="text-sm font-medium text-foreground">
            Could not load configuration
          </p>
          <p className="text-xs text-muted-foreground">{state.message}</p>
          <button
            type="button"
            onClick={() => {
              setState({ kind: "loading" });
              void refresh();
            }}
            className="text-xs px-3 py-1.5 rounded border border-border hover:bg-accent"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  if (state.kind === "needs-setup") {
    return (
      <FirstRun
        onComplete={refresh}
        onSkip={() => setState({ kind: "ready", config: state.config ?? { provider: "", model: "", has_api_key: false, max_tokens: null, max_context_tokens: null, connected_providers: [], active_subscription: null, detected_subscriptions: [], subscriptions: [] } })}
      />
    );
  }

  // Subscription gating lives one layer up (SubscriptionProvider in
  // main.tsx) and uses /v1/billing/subscription as the source of truth.
  return <>{children}</>;
}
