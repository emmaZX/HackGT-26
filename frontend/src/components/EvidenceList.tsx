import { ReportCard } from "@/lib/types";
import { timeAgo } from "@/lib/identity";

const SOURCE_LABEL: Record<string, string> = {
  community: "Neighbor note",
  user_report: "Neighbor note",
  web: "Web",
  news: "News",
  cpsc: "CPSC",
  reddit: "Reddit",
  fda: "FDA",
};

const INTERNET_SOURCES = new Set(["web", "reddit", "news"]);

export function isUsableSourceUrl(url: string | null | undefined): boolean {
  if (!url) return false;
  const lowered = url.trim().toLowerCase();
  if (!(lowered.startsWith("http://") || lowered.startsWith("https://"))) return false;
  try {
    const host = new URL(url).hostname.replace(/^www\./, "");
    if (!host || host === "example.com" || host.endsWith(".example.com")) return false;
  } catch {
    return false;
  }
  return true;
}

export function isInternetReport(report: ReportCard): boolean {
  return INTERNET_SOURCES.has(report.source) && isUsableSourceUrl(report.source_url);
}

export function isSiteReport(report: ReportCard): boolean {
  return report.source === "community" || report.source === "user_report" || report.is_user_generated;
}

export function EvidenceList({
  reports,
  requireUrl = false,
  emptyMessage = "Nothing in this view yet.",
  linkLabel = "Open original",
}: {
  reports: ReportCard[];
  requireUrl?: boolean;
  emptyMessage?: string;
  linkLabel?: string;
}) {
  const visible = requireUrl ? reports.filter((r) => isUsableSourceUrl(r.source_url)) : reports;
  if (!visible.length) {
    return <div className="card p-6 text-sm text-[#5a6d80]">{emptyMessage}</div>;
  }
  return (
    <div className="grid gap-3">
      {visible.map((report) => (
        <article key={report.id} className="card p-5">
          <div className="flex flex-wrap items-center gap-2 text-xs uppercase tracking-[0.1em] text-[#5b8fb5]">
            <span>{SOURCE_LABEL[report.source] || report.source}</span>
            <span>·</span>
            <span>{timeAgo(report.created_at)}</span>
            {report.location.label && (
              <>
                <span>·</span>
                <span>{report.location.label}</span>
              </>
            )}
            {report.is_duplicate && <span className="text-[#c9a84c]">sounds like a reprint</span>}
          </div>
          <p className="mt-3 text-[15px] leading-relaxed">&ldquo;{report.excerpt}&rdquo;</p>
          {isUsableSourceUrl(report.source_url) && (
            <a
              href={report.source_url!}
              target="_blank"
              rel="noopener noreferrer"
              className="mt-3 inline-block text-sm font-medium text-[#5b8fb5] underline-offset-4 hover:underline"
            >
              {linkLabel}
            </a>
          )}
        </article>
      ))}
    </div>
  );
}
