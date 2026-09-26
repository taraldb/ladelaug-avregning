import { useEffect, type ReactNode } from "react";

interface ModalProps {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  /** Widen the dialog for charts / wide tables (max-w-2xl instead of max-w-lg). */
  wide?: boolean;
}

export default function Modal({
  open,
  title,
  onClose,
  children,
  footer,
  wide = false,
}: ModalProps) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    // Don't let the page scroll behind the dialog — on a phone the dialog is a
    // full-width sheet and the page underneath would drag with the gesture.
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = prevOverflow;
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-slate-950/70 sm:items-start sm:p-4 sm:pt-24"
      role="presentation"
      onClick={onClose}
    >
      {/* A bottom sheet on a phone, the familiar centred dialog from `sm` up.
          The body is the only scrolling part, so the footer buttons stay on
          screen however tall the form gets. */}
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={`flex max-h-[90dvh] w-full flex-col rounded-t-xl border border-slate-800 bg-slate-900 shadow-xl sm:max-h-[calc(100dvh-8rem)] sm:rounded-xl ${
          wide ? "sm:max-w-2xl" : "sm:max-w-lg"
        }`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex shrink-0 items-center justify-between border-b border-slate-800 px-5 py-3.5">
          <h2 className="text-sm font-semibold text-slate-100">{title}</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Lukk"
            className="inline-flex h-11 w-11 items-center justify-center rounded-md text-slate-400 hover:bg-slate-800 hover:text-slate-100 sm:h-auto sm:w-auto sm:px-2 sm:py-1"
          >
            ×
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4 text-sm text-slate-200">
          {children}
        </div>
        {footer && (
          <div className="flex shrink-0 justify-end gap-2 border-t border-slate-800 px-5 py-3.5 pb-[calc(0.875rem+env(safe-area-inset-bottom))] sm:pb-3.5">
            {footer}
          </div>
        )}
      </div>
    </div>
  );
}
