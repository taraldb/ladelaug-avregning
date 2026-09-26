import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Link, NavLink, useLocation } from "react-router-dom";
import { useIsCompact } from "../hooks/useMediaQuery";

export interface NavItem {
  to: string;
  label: string;
  /** Match the path exactly (react-router's `end`). */
  end?: boolean;
  /** Override the lit state — for a tab that covers several paths. */
  active?: boolean;
}

/**
 * One nav destination, for both the desktop bar and the drawer.
 *
 * `NavLink` spreads its own computed `aria-current` *after* the caller's props,
 * so an item that overrides the lit state (System, which stays lit on /brukere
 * and /ladere) cannot express that through NavLink at all — it renders a plain
 * `Link` instead and owns both the class and the aria-current.
 */
export function NavItemLink({
  item,
  className,
}: {
  item: NavItem;
  className: (isActive: boolean) => string;
}) {
  if (item.active !== undefined) {
    return (
      <Link
        to={item.to}
        aria-current={item.active ? "page" : undefined}
        className={className(item.active)}
      >
        {item.label}
      </Link>
    );
  }
  return (
    <NavLink to={item.to} end={item.end} className={({ isActive }) => className(isActive)}>
      {item.label}
    </NavLink>
  );
}

/**
 * The nav below `md`. The panel is mounted only while open, so the drawer's
 * links never coexist in the DOM with the desktop bar's — which keeps every
 * `getByRole("link", { name })` in the suite resolving to exactly one node.
 */
export default function NavDrawer({
  items,
  email,
  onLogout,
}: {
  items: NavItem[];
  email?: string;
  onLogout: () => void;
}) {
  const [open, setOpen] = useState(false);
  const { pathname } = useLocation();
  const compact = useIsCompact();
  const toggleRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  // Navigating away closes the drawer.
  useEffect(() => setOpen(false), [pathname]);

  // The panel is portalled to <body>, so it is no longer inside the `md:hidden`
  // wrapper that CSS would have hidden it with. Close it when the viewport
  // grows past `md` rather than leaving it stranded over the desktop layout.
  useEffect(() => {
    if (!compact) setOpen(false);
  }, [compact]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    // Don't let the page scroll behind the drawer.
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    panelRef.current?.focus();
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [open]);

  function close() {
    setOpen(false);
    toggleRef.current?.focus();
  }

  return (
    <div className="md:hidden">
      <button
        ref={toggleRef}
        type="button"
        aria-label="Meny"
        aria-expanded={open}
        aria-controls="mobile-nav"
        onClick={() => setOpen((v) => !v)}
        className="inline-flex h-11 w-11 items-center justify-center rounded-md border border-slate-700 text-slate-200 hover:bg-slate-800"
      >
        <span aria-hidden="true" className="text-lg leading-none">
          ☰
        </span>
      </button>

      {/* Portalled to <body>: the header sets `backdrop-blur`, and a
          backdrop-filter makes that element a containing block for fixed
          descendants — rendered in place, the overlay would be clipped to the
          64px header box and trapped inside its z-10 stacking context. */}
      {open &&
        createPortal(
          <div
            className="fixed inset-0 z-40 bg-slate-950/70"
            role="presentation"
            onClick={close}
          >
            <div
              id="mobile-nav"
              ref={panelRef}
              tabIndex={-1}
              role="dialog"
              aria-modal="true"
              aria-label="Meny"
              onClick={(e) => e.stopPropagation()}
              className="ml-auto flex h-full w-72 max-w-[85vw] flex-col border-l border-slate-800 bg-slate-900 pt-[env(safe-area-inset-top)] outline-none"
            >
              <div className="flex items-center justify-between border-b border-slate-800 px-4 py-3">
                <span className="text-sm font-semibold text-slate-100">Meny</span>
                <button
                  type="button"
                  onClick={close}
                  aria-label="Lukk meny"
                  className="inline-flex h-11 w-11 items-center justify-center rounded-md text-slate-400 hover:bg-slate-800 hover:text-slate-100"
                >
                  <span aria-hidden="true">×</span>
                </button>
              </div>

              <nav className="flex-1 overflow-y-auto p-2">
                {items.map((item) => (
                  <NavItemLink
                    key={item.to}
                    item={item}
                    className={(isActive) =>
                      `block rounded-md px-3 py-3 text-sm font-medium ${
                        isActive
                          ? "bg-slate-100 text-slate-900"
                          : "text-slate-300 hover:bg-slate-700/60 hover:text-slate-100"
                      }`
                    }
                  />
                ))}
              </nav>

              <div className="border-t border-slate-800 p-4 pb-[calc(1rem+env(safe-area-inset-bottom))]">
                {email && (
                  <p className="mb-2 truncate text-xs text-slate-400">{email}</p>
                )}
                <button
                  type="button"
                  onClick={onLogout}
                  className="w-full rounded-md border border-slate-700 px-3 py-2.5 text-sm text-slate-200 hover:bg-slate-800"
                >
                  Logg ut
                </button>
              </div>
            </div>
  </div>,
          document.body,
        )}
    </div>
  );
}