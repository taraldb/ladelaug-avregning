/** Small "+" glyph for add-actions. The repo has no icon library, so this is a
 * one-off inline SVG rather than a dependency. Inherits colour via
 * `currentColor` and sizes to `1em`. */
export default function PlusIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 16 16"
      width="1em"
      height="1em"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      aria-hidden="true"
      className={className}
    >
      <path d="M8 3v10M3 8h10" />
    </svg>
  );
}
