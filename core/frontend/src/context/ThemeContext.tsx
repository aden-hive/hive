import React, { createContext, useContext, useEffect, useState, useCallback } from "react";
import { configApi } from "@/api/config";

type Theme = "light" | "dark";
type Density = "compact" | "spacious";

interface ThemeContextValue {
  theme: Theme;
  setTheme: (theme: Theme) => void;
  density: Density;
  setDensity: (density: Density) => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme, setTheme] = useState<Theme>(() => {
    const stored = localStorage.getItem("theme");

    if (stored === "light" || stored === "dark") {
      return stored;
    }

    // No explicit local choice yet — fall back to the OS preference.
    // Critical for the AuthScreen: the user isn't authenticated yet, so
    // the server-side theme fetch (below) silently 401s. Without this
    // fallback, fresh installs land on light even when the user runs
    // their machine in dark mode. Once they sign in, server profile
    // (and any explicit toggle) override this.
    if (typeof window !== "undefined" && typeof window.matchMedia === "function") {
      try {
        if (window.matchMedia("(prefers-color-scheme: dark)").matches) {
          return "dark";
        }
      } catch {
        // matchMedia missing or threw — fall through to light.
      }
    }
    return "light";
  });

  // Theme/density are persisted per-device in localStorage only (see effects
  // below). There is no cloud profile hydration in local mode.

  const [density, setDensity] = useState<Density>(() => {
    const stored = localStorage.getItem("density");
    if (stored === "compact" || stored === "spacious") return stored;
    // Default to compact — current visual baseline. Spacious is opt-in.
    return "compact";
  });

  useEffect(() => {
    const root = document.documentElement;

    root.classList.remove("light", "dark");
    root.classList.add(theme);

    localStorage.setItem("theme", theme);
  }, [theme]);

  useEffect(() => {
    document.documentElement.dataset.density = density;
    localStorage.setItem("density", density);
  }, [density]);

  const handleSetTheme = useCallback((t: Theme) => {
    setTheme(t);
    // Mark an explicit on-device choice so future /v1/me hydration won't
    // override it with the account's onboarding theme (see hydration effect).
    try { localStorage.setItem("theme-explicit", "1"); } catch { /* ignore */ }
    // Pass undefined for name/about so the runtime leaves them alone — see
    // `configApi.setProfile`. Sending "" would overwrite the user's profile.
    configApi.setProfile(undefined, undefined, t).catch(() => {});
  }, []);

  const handleSetDensity = useCallback((d: Density) => {
    setDensity(d);
    try { localStorage.setItem("density-explicit", "1"); } catch { /* ignore */ }
    configApi.setProfile(undefined, undefined, undefined, d).catch(() => {});
  }, []);

  return (
    <ThemeContext.Provider
      value={{
        theme,
        setTheme: handleSetTheme,
        density,
        setDensity: handleSetDensity,
      }}
    >
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme(): ThemeContextValue {
  const context = useContext(ThemeContext);

  if (!context) {
    throw new Error("useTheme must be used within a ThemeProvider");
  }

  return context;
}
