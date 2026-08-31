import type { ReactNode } from "react";
import Modal from "./Modal";

/**
 * A yes/no confirmation dialog. The confirm button is styled as a destructive
 * action by default (rose); pass `tone="normal"` for a neutral confirmation.
 */
export default function ConfirmModal({
  open,
  title,
  message,
  confirmLabel = "Slett",
  cancelLabel = "Avbryt",
  tone = "danger",
  busy = false,
  onConfirm,
  onClose,
}: {
  open: boolean;
  title: string;
  message: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  tone?: "danger" | "normal";
  busy?: boolean;
  onConfirm: () => void;
  onClose: () => void;
}) {
  const confirmClass =
    tone === "danger"
      ? "rounded-md bg-rose-500 px-3 py-1.5 text-sm font-semibold text-white hover:bg-rose-400 disabled:opacity-60"
      : "rounded-md bg-emerald-500 px-3 py-1.5 text-sm font-semibold text-slate-950 hover:bg-emerald-400 disabled:opacity-60";

  return (
    <Modal
      open={open}
      title={title}
      onClose={onClose}
      footer={
        <>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-slate-700 px-3 py-1.5 text-sm text-slate-300 hover:bg-slate-800"
          >
            {cancelLabel}
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={busy}
            className={confirmClass}
          >
            {confirmLabel}
          </button>
        </>
      }
    >
      <div className="text-sm text-slate-200">{message}</div>
    </Modal>
  );
}
