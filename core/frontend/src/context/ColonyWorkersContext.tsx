import { createContext, useContext, useCallback, type ReactNode } from "react";

interface ColonyWorkersContextValue {
  openColonyWorkers: (sessionId: string) => void;
}

const ColonyWorkersContext = createContext<ColonyWorkersContextValue | null>(null);

export function ColonyWorkersProvider({
  onOpen,
  children,
}: {
  onOpen: (sessionId: string) => void;
  children: ReactNode;
}) {
  const openColonyWorkers = useCallback(
    (sessionId: string) => onOpen(sessionId),
    [onOpen],
  );
  return (
    <ColonyWorkersContext.Provider value={{ openColonyWorkers }}>
      {children}
    </ColonyWorkersContext.Provider>
  );
}

export function useColonyWorkers() {
  const ctx = useContext(ColonyWorkersContext);
  if (!ctx)
    throw new Error("useColonyWorkers must be used within ColonyWorkersProvider");
  return ctx;
}
