import { createContext, useContext, useState, type ReactNode } from "react";

interface HeaderActionsContextValue {
  actions: ReactNode;
  setActions: (node: ReactNode) => void;
}

const HeaderActionsContext = createContext<HeaderActionsContextValue | null>(null);

export function HeaderActionsProvider({ children }: { children: ReactNode }) {
  const [actions, setActions] = useState<ReactNode>(null);
  return (
    <HeaderActionsContext.Provider value={{ actions, setActions }}>
      {children}
    </HeaderActionsContext.Provider>
  );
}

export function useHeaderActions() {
  const ctx = useContext(HeaderActionsContext);
  if (!ctx) throw new Error("useHeaderActions must be used within HeaderActionsProvider");
  return ctx;
}
