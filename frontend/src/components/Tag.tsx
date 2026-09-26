const RECALL = new Set(["FDA RECALL", "CPSC RECALL", "OFFICIAL RECALL"]);
const SIGNAL = new Set(["STRONG SIGNAL", "EMERGING SIGNAL", "ELEVATED REPORTS", "LIMITED REPORTS"]);
const ACRONYMS = new Set(["CPSC", "FDA"]);

export const isRecallTag = (tag: string | null | undefined) => !!tag && RECALL.has(tag);

/**
 * Split backend tags into one status badge and the small pills.
 * An active recall wins over a signal; everything else (INTERNET FIRST, LOCAL, TRENDING, agencies) is a pill.
 */
export function splitTags(tags: string[]) {
  const status = tags.find((t) => RECALL.has(t)) || tags.find((t) => SIGNAL.has(t)) || null;
  return {
    status,
    pills: tags.filter((t) => !RECALL.has(t) && !SIGNAL.has(t)),
  };
}

export function StatusBadge({ label }: { label: string }) {
  if (RECALL.has(label)) {
    return <span className="badge bg-[#ff96a6] text-white">{label}</span>;
  }
  if (label === "STRONG SIGNAL" || label === "EMERGING SIGNAL") {
    return <span className="badge border border-[#ff96a6] bg-white text-[#d9546a]">{label}</span>;
  }
  return <span className="badge border border-[#c0d4ef] bg-white text-[#627290]">{label}</span>;
}

export function Pill({ label }: { label: string }) {
  return <span className="pill">{ACRONYMS.has(label) ? label : label.toLowerCase()}</span>;
}

/** For pages that just render a list of tags */
export function Tag({ label }: { label: string }) {
  return RECALL.has(label) || SIGNAL.has(label) ? <StatusBadge label={label} /> : <Pill label={label} />;
}
