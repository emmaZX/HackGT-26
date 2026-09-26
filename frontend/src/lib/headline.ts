import { ProductCard } from "./types";

/** Brand + name without saying the brand twice ("Acme" + "Acme X100" → "Acme X100") */
export function fullName(p: ProductCard) {
  const brand = p.brand && p.brand !== "Unknown" ? p.brand : "";
  if (!brand || p.name.toLowerCase().startsWith(brand.toLowerCase())) return p.name;
  return `${brand} ${p.name}`;
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
  const brand = p.brand && p.brand !== "Unknown" ? p.brand : "";

  if (recall) {
    const why = shortHazard(recall.hazard);
    const base = brand && !p.name.toLowerCase().startsWith(brand.toLowerCase())
      ? `${brand} recalls ${p.name}`
      : `${p.name} recalled`;
    return why ? `${base} over ${why}` : base;
  }

  const people = s.independent_count || s.report_count;
  if (!people) return fullName(p);
  const top = [...s.issues].sort((a, b) => b.count - a.count)[0];
  const who = people === 1 ? "1 person reports" : `${people} people report`;
  const what = top ? top.name.toLowerCase() : "problems";
  return `${who} ${what} with the ${fullName(p)}`;
}

const STATUS_TEXT: Record<string, string> = {
  "FDA RECALL": "FDA recall",
  "CPSC RECALL": "CPSC recall",
  "OFFICIAL RECALL": "Official recall",
  "STRONG SIGNAL": "Strong signal",
  "EMERGING SIGNAL": "Emerging signal",
  "ELEVATED REPORTS": "More reports than usual",
  "LIMITED REPORTS": "A few reports",
};

/** Kicker above the headline: status, then where it comes from */
export function kicker(p: ProductCard) {
  const recall = activeRecall(p);
  const recallTag = p.tags.find((t) => t.endsWith("RECALL") && t in STATUS_TEXT);
  const statusTag = recallTag || p.tags.find((t) => t in STATUS_TEXT);
  const internetFirst = p.tags.includes("INTERNET FIRST");
  return {
    status: statusTag ? STATUS_TEXT[statusTag] : null,
    isRecall: !!recall,
    source: recall ? "Official notice" : internetFirst ? "Spotted online first" : "Online reports",
  };
}

/** Meta line under the headline: where, and what changed recently */
export function meta(p: ProductCard) {
  const s = p.signal;
  const recall = activeRecall(p);
  const parts: string[] = [];
  if (recall?.nationwide) parts.push("Nationwide");
  else if (s.geography[0]) parts.push(s.geography[0].label);

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
