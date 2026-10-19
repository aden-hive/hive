import { useEffect, useState } from "react";

// Developer-only toggle for the floating "Runtime logs" drawer in the
// bottom-right corner. Hidden by default; opt-in from Settings → Developer.
// Persisted in localStorage and shared across components via a tiny
// module-level pub/sub so flipping the toggle updates the drawer live.
const STORAGE_KEY = "showRuntimeLogs";

function read(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) === "true";
  } catch {
    return false;
  }
}

let value = read();
const listeners = new Set<(v: boolean) => void>();

export function useShowRuntimeLogs(): [boolean, (next: boolean) => void] {
  const [v, setV] = useState(value);
  useEffect(() => {
    listeners.add(setV);
    return () => {
      listeners.delete(setV);
    };
  }, []);
  return [
    v,
    (next: boolean) => {
      value = next;
      try {
        localStorage.setItem(STORAGE_KEY, String(next));
      } catch {}
      listeners.forEach((fn) => fn(next));
    },
  ];
}
