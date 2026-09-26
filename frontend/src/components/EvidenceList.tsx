import { ReportCard } from "@/lib/types";
import { timeAgo } from "@/lib/identity";

const SOURCE_LABEL: Record<string, string> = {
  community: "From a neighbor",
  user_report: "From a neighbor",
  web: "Found online",
  news: "News or blog",
  cpsc: "Official notice",
  reddit: "Public discussion",
};

export function EvidenceList({ reports }: { reports: ReportCard[] }) {
  if (!reports.length) {
    return <div className="card p-6 text-sm text-[#5a6d80]">Nothing in this view yet.</div>;
  }
  return (
    <div className="grid gap-3">
      {reports.map((report) => (
        <article key={report.id} className="card p-5">
          <div className="flex flex-wrap items-center gap-2 text-xs uppercase tracking-[0.1em] text-[#5b8fb5]">
            <span>{SOURCE_LABEL[report.source] || report.source}</span>
            <span>·</span>
            <span>{timeAgo(report.created_at)}</span>
            {report.location.label && (
              <>
                <span>·</span>
                <span>📍 {report.location.label}</span>
              </>
            )}
            {report.is_duplicate && <span className="text-[#c9a84c]">sounds like a reprint</span>}
          </div>
          <p className="mt-3 text-[15px] leading-relaxed">&ldquo;{report.excerpt}&rdquo;</p>
          {report.source_url && (
            <a href={report.source_url} className="mt-3 inline-block text-sm text-[#5b8fb5] underline-offset-4 hover:underline">
              See the original
            </a>
          )}
        </article>
      ))}
    </div>
  );
}
