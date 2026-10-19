import { createContext, useContext, type ReactNode } from "react";

type RuntimeStatus = "starting" | "ready" | "error";

interface RuntimeState {
  status: RuntimeStatus;
  port: number | null;
  error: string | null;
}

const RuntimeContext = createContext<RuntimeState>({
  status: "ready",
  port: null,
  error: null,
});

export function useRuntime() {
  return useContext(RuntimeContext);
}

export function RuntimeProvider({ children }: { children: ReactNode }) {
  // The web SPA talks to an already-running Python runtime over HTTP; there
  // is no local process to boot, so the runtime is always "ready". Requests
  // surface their own connectivity errors via the API client.
  const state: RuntimeState = { status: "ready", port: null, error: null };
  return (
    <RuntimeContext.Provider value={state}>
      {children}
    </RuntimeContext.Provider>
  );
}
