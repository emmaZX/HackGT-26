/** Figma back arrow (rmm-back-arrow.svg), recoloured to navy so it shows on the page background */
export function BackArrow({ className = "" }: { className?: string }) {
  return (
    <svg viewBox="0 0 150 71" fill="none" aria-hidden className={className}>
      <path d="M11 60C57.5 11 82 7 139 50M57.5 60H11V11" stroke="currentColor" strokeWidth="22" strokeLinecap="round" />
    </svg>
  );
}
