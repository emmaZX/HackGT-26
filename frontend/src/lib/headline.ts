import { ProductCard } from "./types";

/** Notable product title first; brand after when it adds something. */
export function fullName(p: { name: string; brand?: string | null }) {
  const brand = p.brand && p.brand !== "Unknown" ? p.brand.trim() : "";
  const title = p.name?.trim() || "Unknown product";
  if (!brand) return title;
  if (title.toLowerCase().includes(brand.toLowerCase())) return title;
  if (brand.toLowerCase().includes(title.toLowerCase())) return brand;
  return `${title} · ${brand}`;
}

/** "Burn hazard" → "burn risk"; long or generic hazards are dropped */
function shortHazard(hazard: string | undefined | null) {
  if (!hazard) return null;
  const h = hazard.trim().toLowerCase();
  if (!h || h === "safety hazard" || h.length > 32) return null;
  return h.replace(/\s*hazard$/, " risk");
}

/** Past (terminated) recalls are history, not news */
function activeRecall(p: ProductCard) {
  const r = p.signal.official_recall;
  return r && r.phase !== "past" ? r : null;
}

/** A news-style headline built from data the backend already sends */
export function headline(p: ProductCard) {
  const s = p.signal;
  const recall = activeRecall(p);
  const title = fullName(p);

  if (recall) {
    const why = shortHazard(recall.hazard);
    const base = `${title} recalled`;
    return why ? `${base} over ${why}` : base;
  }

  const people = s.independent_count || s.report_count;
  if (!people) return title;
  const top = [...s.issues].sort((a, b) => b.count - a.count)[0];
  const who = people === 1 ? "1 person reports" : `${people} people report`;
  const what = top ? top.name.toLowerCase() : "problems";
  return `${who} ${what} with ${title}`;
}

const STATUS_TEXT: Record<string, string> = {
  "FDA RECALL": "FDA recall",
  "CPSC RECALL": "CPSC recall",
  "OFFICIAL RECALL": "Official recall",
  "STRONG SIGNAL": "Strong signal",
  "EMERGING SIGNAL": "Emerging signal",
  "ELEVATED REPORTS": "More reports than usual",
  "LIMITED REPORTS": "A few reports",
  "OUTBREAK WATCH": "Outbreak watch",
  "CAERS SPIKE": "Complaint spike",
  UNOFFICIAL: "Community",
};

/** Kicker above the headline: status, then where it comes from */
export function kicker(p: ProductCard) {
  const recall = activeRecall(p);
  const recallTag = p.tags.find((t) => t.endsWith("RECALL") && t in STATUS_TEXT);
  const statusTag =
    recallTag ||
    p.tags.find((t) => t in STATUS_TEXT) ||
    (p.source_tier === "caers" ? "CAERS SPIKE" : null) ||
    (p.source_tier === "unofficial" ? "UNOFFICIAL" : null);
  const internetFirst = p.tags.includes("INTERNET FIRST");
  const tier = p.source_tier || p.signal?.source_tier;
  let source = "Online reports";
  if (recall) source = "Official notice";
  else if (tier === "caers") source = "FDA complaint reports · no recall yet";
  else if (internetFirst) source = "Spotted online first · no recall yet";
  else if (tier === "unofficial") source = "No recall yet";
  return {
    status: statusTag ? STATUS_TEXT[statusTag] : null,
    isRecall: !!recall,
    source,
  };
}

/** Meta line under the headline: where, linked sources, and what changed recently */
export function meta(p: ProductCard) {
  const s = p.signal;
  const recall = activeRecall(p);
  const parts: string[] = [];
  if (recall?.nationwide) parts.push("Nationwide");
  else if (s.geography[0]) parts.push(s.geography[0].label);

  const evidenceCount = p.evidence_count;
  if (typeof evidenceCount === "number" && evidenceCount > 0) {
    parts.push(`${evidenceCount} linked source${evidenceCount === 1 ? "" : "s"}`);
  } else if (s.report_count > 1) {
    parts.push(`${s.report_count} reports`);
  }

  if (recall?.recall_date) {
    const d = new Date(recall.recall_date);
    parts.push(
      isNaN(d.getTime())
        ? `Recalled ${recall.recall_date}`
        : `Recalled ${d.toLocaleDateString("en-US", { month: "short", day: "numeric" })}`,
    );
  } else if (s.recent_report_count) {
    parts.push(`${s.recent_report_count} new this week`);
  }
  return parts.join(" · ");
}
