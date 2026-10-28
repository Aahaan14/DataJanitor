import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";

type Kind = "success" | "error" | "info";
interface ToastItem { id: number; kind: Kind; title: string; message?: string }
interface ToastApi {
  success: (title: string, message?: string) => void;
  error: (title: string, message?: string) => void;
  info: (title: string, message?: string) => void;
}

const ToastContext = createContext<ToastApi | null>(null);

const STYLE: Record<Kind, string> = {
  success: "border-emerald-300 bg-emerald-50 text-emerald-900 dark:border-emerald-800 dark:bg-emerald-950 dark:text-emerald-100",
  error: "border-red-300 bg-red-50 text-red-900 dark:border-red-800 dark:bg-red-950 dark:text-red-100",
  info: "border-indigo-300 bg-indigo-50 text-indigo-900 dark:border-indigo-800 dark:bg-indigo-950 dark:text-indigo-100",
};

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const dismiss = useCallback((id: number) => setItems((l) => l.filter((t) => t.id !== id)), []);
  const push = useCallback((kind: Kind, title: string, message?: string) => {
    const id = Date.now() + Math.random();
    setItems((l) => [...l.slice(-3), { id, kind, title, message }]);
    setTimeout(() => dismiss(id), kind === "error" ? 8000 : 4500);
  }, [dismiss]);
  const api = useMemo<ToastApi>(() => ({
    success: (t, m) => push("success", t, m),
    error: (t, m) => push("error", t, m),
    info: (t, m) => push("info", t, m),
  }), [push]);

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div className="pointer-events-none fixed inset-x-0 bottom-0 z-50 flex flex-col items-center gap-2 p-4 sm:items-end">
        {items.map((t) => (
          <div key={t.id} role={t.kind === "error" ? "alert" : "status"}
               className={`pointer-events-auto w-full max-w-sm rounded-lg border p-3 shadow-lg ${STYLE[t.kind]}`}>
            <div className="flex items-start gap-2">
              <div className="min-w-0 flex-1">
                <p className="text-sm font-semibold">{t.title}</p>
                {t.message && <p className="mt-0.5 break-words text-sm opacity-90">{t.message}</p>}
              </div>
              <button onClick={() => dismiss(t.id)} aria-label="Dismiss notification"
                      className="rounded px-1 text-lg leading-none opacity-60 hover:opacity-100">×</button>
            </div>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastApi {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used inside <ToastProvider>");
  return ctx;
}
