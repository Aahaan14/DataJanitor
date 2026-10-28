import { useEffect, useId, useRef, type ReactNode } from "react";
import { Button } from "./ui";

interface ModalProps {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  wide?: boolean;
}

/** Accessible modal: Escape and backdrop close it, focus moves inside and is restored on close. */
export function Modal({ open, title, onClose, children, footer, wide }: ModalProps) {
  const titleId = useId();
  const panel = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement as HTMLElement | null;
    panel.current?.focus();
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("keydown", onKey); previous?.focus?.(); };
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div className="fixed inset-0 z-40 flex items-end justify-center bg-slate-900/50 p-0 sm:items-center sm:p-4"
         onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div ref={panel} role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1}
           className={`flex max-h-[90vh] w-full flex-col rounded-t-xl bg-white shadow-xl outline-none dark:bg-slate-900 sm:rounded-xl ${wide ? "sm:max-w-3xl" : "sm:max-w-lg"}`}>
        <div className="flex items-center justify-between border-b border-slate-200 px-5 py-3 dark:border-slate-700">
          <h2 id={titleId} className="text-base font-semibold">{title}</h2>
          <button onClick={onClose} aria-label="Close dialog" className="rounded px-2 text-xl leading-none text-slate-500 hover:text-slate-900 dark:hover:text-white">×</button>
        </div>
        <div className="overflow-y-auto px-5 py-4">{children}</div>
        {footer && <div className="flex flex-wrap justify-end gap-2 border-t border-slate-200 px-5 py-3 dark:border-slate-700">{footer}</div>}
      </div>
    </div>
  );
}

interface ConfirmProps {
  open: boolean;
  title: string;
  children: ReactNode;
  confirmLabel: string;
  busy?: boolean;
  danger?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

export function ConfirmDialog({ open, title, children, confirmLabel, busy, danger, onConfirm, onCancel }: ConfirmProps) {
  return (
    <Modal open={open} title={title} onClose={onCancel}
           footer={<>
             <Button variant="secondary" onClick={onCancel} disabled={busy}>Cancel</Button>
             <Button variant={danger ? "danger" : "primary"} onClick={onConfirm} loading={busy}>{confirmLabel}</Button>
           </>}>
      <div className="space-y-2 text-sm text-slate-700 dark:text-slate-300">{children}</div>
    </Modal>
  );
}
