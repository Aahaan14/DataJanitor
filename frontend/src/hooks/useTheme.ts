import { useCallback, useEffect, useState } from "react";

export type Theme = "light" | "dark" | "system";
const KEY = "dj-theme";

function read(): Theme {
  try {
    const v = localStorage.getItem(KEY);
    return v === "light" || v === "dark" ? v : "system";
  } catch {
    return "system";
  }
}

function apply(theme: Theme): void {
  const prefersDark =
    typeof window !== "undefined" && typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-color-scheme: dark)").matches;
  document.documentElement.classList.toggle("dark", theme === "dark" || (theme === "system" && prefersDark));
}

/** Light / dark / system theme, remembered in localStorage (a UI preference only). */
export function useTheme(): [Theme, (t: Theme) => void] {
  const [theme, setThemeState] = useState<Theme>(read);
  useEffect(() => { apply(theme); }, [theme]);
  const setTheme = useCallback((t: Theme) => {
    try { localStorage.setItem(KEY, t); } catch { /* private mode: keep in memory only */ }
    setThemeState(t);
  }, []);
  return [theme, setTheme];
}
