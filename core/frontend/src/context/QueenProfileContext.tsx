import { createContext, useContext, useCallback, type ReactNode } from "react";

interface QueenProfileContextValue {
  openQueenProfile: (queenId: string) => void;
}

const QueenProfileContext = createContext<QueenProfileContextValue | null>(null);

export function QueenProfileProvider({
  onOpen,
  children,
}: {
  onOpen: (queenId: string) => void;
  children: ReactNode;
}) {
  const openQueenProfile = useCallback(
    (queenId: string) => onOpen(queenId),
    [onOpen],
  );
  return (
    <QueenProfileContext.Provider value={{ openQueenProfile }}>
      {children}
    </QueenProfileContext.Provider>
  );
}

export function useQueenProfile() {
  const ctx = useContext(QueenProfileContext);
  if (!ctx) throw new Error("useQueenProfile must be used within QueenProfileProvider");
  return ctx;
}
