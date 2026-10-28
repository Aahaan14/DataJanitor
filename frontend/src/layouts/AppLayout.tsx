import { useState, type ReactNode } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { useTheme, type Theme } from "../hooks/useTheme";

const NAV: { to: string; label: string; icon: ReactNode; end?: boolean }[] = [
  { to: "/", label: "Dashboard", end: true, icon: <path d="M3 12l9-8 9 8M5 10v10h5v-6h4v6h5V10" /> },
  { to: "/upload", label: "Upload", icon: <path d="M12 16V4m0 0l-4 4m4-4l4 4M4 16v4h16v-4" /> },
  { to: "/datasets", label: "Datasets", icon: <path d="M4 6c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3zm0 0v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3" /> },
  { to: "/history", label: "History", icon: <path d="M12 8v5l3 2M3 12a9 9 0 1 0 3-6.7M3 4v4h4" /> },
  { to: "/settings", label: "Settings", icon: <path d="M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zm7.4-3a7.4 7.4 0 0 0-.1-1.2l2-1.5-2-3.4-2.3.9a7.5 7.5 0 0 0-2-1.2L14.6 2h-4l-.4 2.6a7.5 7.5 0 0 0-2 1.2l-2.3-.9-2 3.4 2 1.5a7.400 7.400 0 0 0 0 2.400l-2 1.500 2 3.400 2.300-.9a7.500 7.500 0 0 0 2 1.200l.4 2.600h4l.4-2.600a7.500 7.500 0 0 0 2-1.200l2.300.9 2-3.400-2-1.500c.1-.4.1-.8.1-1.200z" /> },
];

function Brand() {
  return (
    <div className="flex items-center gap-2 px-2">
      <span className="grid h-8 w-8 place-items-center rounded-lg bg-indigo-600 text-white" aria-hidden="true">
        <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M7 4h10M9 8h6l-1 11a2 2 0 0 1-2 2h0a2 2 0 0 1-2-2z" /></svg>
      </span>
      <span className="text-lg font-bold tracking-tight">DataJanitor</span>
    </div>
  );
}

function NavLinks({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <nav aria-label="Main" className="space-y-1">
      {NAV.map((n) => (
        <NavLink key={n.to} to={n.to} end={n.end} onClick={onNavigate}
                 className={({ isActive }) => `flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium ${isActive ? "bg-indigo-50 text-indigo-700 dark:bg-indigo-950 dark:text-indigo-300" : "text-slate-700 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"}`}>
          <svg viewBox="0 0 24 24" className="h-5 w-5 shrink-0" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{n.icon}</svg>
          {n.label}
        </NavLink>
      ))}
    </nav>
  );
}

function ThemePicker() {
  const [theme, setTheme] = useTheme();
  return (
    <label className="block px-2 text-xs font-medium text-slate-500 dark:text-slate-400">
      Theme
      <select value={theme} onChange={(e) => setTheme(e.target.value as Theme)}
              className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-2 py-1.5 text-sm text-slate-800 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100">
        <option value="system">Match system</option>
        <option value="light">Light</option>
        <option value="dark">Dark</option>
      </select>
    </label>
  );
}

export function AppLayout() {
  const [open, setOpen] = useState(false);
  return (
    <div className="min-h-screen lg:flex">
      <a href="#main" className="sr-only z-50 rounded bg-white px-3 py-2 text-sm focus:not-sr-only focus:absolute focus:left-2 focus:top-2">Skip to content</a>

      {/* Desktop sidebar */}
      <aside className="hidden w-60 shrink-0 flex-col justify-between border-r border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900 lg:flex lg:sticky lg:top-0 lg:h-screen">
        <div className="space-y-6"><Brand /><NavLinks /></div>
        <ThemePicker />
      </aside>

      {/* Mobile top bar + drawer */}
      <div className="sticky top-0 z-30 flex items-center justify-between border-b border-slate-200 bg-white px-4 py-3 dark:border-slate-800 dark:bg-slate-900 lg:hidden">
        <Brand />
        <button onClick={() => setOpen((o) => !o)} aria-expanded={open} aria-controls="mobile-nav" aria-label="Toggle navigation menu"
                className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm dark:border-slate-600">{open ? "Close" : "Menu"}</button>
      </div>
      {open && (
        <div id="mobile-nav" className="space-y-4 border-b border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900 lg:hidden">
          <NavLinks onNavigate={() => setOpen(false)} />
          <ThemePicker />
        </div>
      )}

      <main id="main" className="min-w-0 flex-1 px-4 py-6 sm:px-8 lg:py-8">
        <div className="mx-auto max-w-6xl"><Outlet /></div>
      </main>
    </div>
  );
}
