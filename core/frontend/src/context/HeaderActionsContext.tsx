import { createContext, useContext, useState, type ReactNode } from "react";

interface HeaderActionsContextValue {
  /** Right-aligned actions (e.g. Colony button, BrowserStatusBadge). */
  actions: ReactNode;
  setActions: (node: ReactNode) => void;
  /** Inline content rendered after the page title + queen-title pill on
   *  the left side of the app header. Used for status chips that belong
   *  next to the title, like the per-colony cloud pill. */
  leftActions: ReactNode;
  setLeftActions: (node: ReactNode) => void;
}

const HeaderActionsContext = createContext<HeaderActionsContextValue | null>(null);

export function HeaderActionsProvider({ children }: { children: ReactNode }) {
  const [actions, setActions] = useState<ReactNode>(null);
  const [leftActions, setLeftActions] = useState<ReactNode>(null);
  return (
    <HeaderActionsContext.Provider
      value={{ actions, setActions, leftActions, setLeftActions }}
    >
      {children}
    </HeaderActionsContext.Provider>
  );
}

export function useHeaderActions() {
  const ctx = useContext(HeaderActionsContext);
  if (!ctx) throw new Error("useHeaderActions must be used within HeaderActionsProvider");
  return ctx;
}
