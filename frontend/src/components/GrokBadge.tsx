/** Marks text written by Grok so it's never mistaken for official or first-hand wording */
export function GrokBadge({ size = "md" }: { size?: "sm" | "md" }) {
  const small = size === "sm";
  return (
    <span
      className={`inline-flex shrink-0 items-center gap-1 rounded-full border border-[#c0d4ef] bg-[#eef3fb] font-semibold text-[#031d4e] ${
        small ? "px-[6px] py-[1px] text-[9px]" : "px-[9px] py-[2px] text-[11px]"
      }`}
    >
      <span aria-hidden>✦</span>
      Summarized by Grok
    </span>
  );
}

/** The backend's fixed (non-AI) FDA complaint summaries; anything else there came from Grok */
const CAERS_TEMPLATES = ["CAERS (FDA-hosted adverse event) reports for", "FDA CAERS adverse event reports on file"];

export function isGrokSummary(summary: string | null | undefined, tier: string | null | undefined) {
  return tier === "caers" && !!summary && !CAERS_TEMPLATES.some((t) => summary.startsWith(t));
}
