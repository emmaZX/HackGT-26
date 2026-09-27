import { ReportCard } from "@/lib/types";
import { isUsableSourceUrl } from "./EvidenceList";

/** Public, linked sources only: these are the reports anyone can check. */
const PUBLIC_SOURCES = new Set(["web", "reddit", "news", "x", "iwaspoisoned"]);

const fmt = (d: Date) => d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });

/**
 * "Spotted N days earlier": compares the earliest dated, linked public report with the official
 * recall date. Uses the complaint's own date (observed_at), never the date we scraped it.
 * Renders nothing when no public report predates the recall.
 */
export function LeadTime({ reports, recallDate }: { reports: ReportCard[]; recallDate: string }) {
  const recall = new Date(recallDate);
  if (isNaN(recall.getTime())) return null;

  const before = reports
    .filter((r) => PUBLIC_SOURCES.has(r.source) && isUsableSourceUrl(r.source_url) && !r.is_duplicate && r.observed_at)
    .map((r) => ({ report: r, date: new Date(r.observed_at as string) }))
    .filter(({ date }) => !isNaN(date.getTime()) && date < recall)
    .sort((a, b) => a.date.getTime() - b.date.getTime());

  if (!before.length) return null;
  const first = before[0];
  const days = Math.floor((recall.getTime() - first.date.getTime()) / 86_400_000);
  if (days < 1) return null;

  return (
    <div className="mt-4 rounded-[14px] border border-[#c0d4ef] bg-[#f5f8fe] p-4">
      <p className="font-mulish text-[22px] font-semibold tracking-[-0.04em] text-[#031d4e]">
        Spotted {days} {days === 1 ? "day" : "days"} before the recall
      </p>
      <p className="mt-1 text-[14px] text-[#31405e]">
        First public report: <strong>{fmt(first.date)}</strong> · Official recall: <strong>{fmt(recall)}</strong>
        {before.length > 1 ? ` · ${before.length} public reports came before it` : ""}
      </p>
      <a
        href={first.report.source_url!}
        target="_blank"
        rel="noopener noreferrer"
        className="mt-2 inline-block text-[13px] text-[#031d4e] underline decoration-[#c0d4ef] decoration-2 underline-offset-4 hover:decoration-[#031d4e]"
      >
        See the first report
      </a>
      <p className="mt-2 text-[12px] text-[#627290]">
        Based on dated, linked public posts. It shows when the public was talking, not when the agency knew.
      </p>
    </div>
  );
}
