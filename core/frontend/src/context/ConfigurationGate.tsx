import { type ReactNode } from "react";
import { useRuntime } from "@/context/RuntimeContext";

/**
 * Holds the UI until the runtime is listening, so the first requests don't
 * race the `uv sync` + serve startup, and shows why when it failed to start.
 *
 * It never blocks on model setup: a chat without a model says so above its
 * composer and links to the model settings (see NoModelNotice).
 */
export function ConfigurationGate({ children }: { children: ReactNode }) {
  const runtime = useRuntime();

  if (runtime.status === "error") {
    return (
      <div className="flex items-center justify-center h-screen bg-background">
        <div className="flex flex-col items-center gap-4 max-w-md text-center px-6">
          <div className="w-10 h-10 rounded-full bg-red-500/10 flex items-center justify-center">
            <span className="text-red-500 text-lg font-bold">!</span>
          </div>
          <p className="text-sm font-medium text-foreground">Hive's runtime did not start</p>
          <p className="text-xs text-muted-foreground">{runtime.error ?? "Runtime failed to start"}</p>
        </div>
      </div>
    );
  }

  if (runtime.status !== "ready") {
    return (
      <div className="flex items-center justify-center h-screen bg-background">
        <div className="flex flex-col items-center gap-4">
          <div className="w-8 h-8 border-2 border-primary/30 border-t-primary rounded-full animate-spin" />
          <p className="text-sm text-muted-foreground">Starting Hive…</p>
        </div>
      </div>
    );
  }

  return <>{children}</>;
}
