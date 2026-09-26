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

function host(url: string) {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return null;
  }
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
    return <p className="text-sm text-[#627290]">{emptyMessage}</p>;
  }
  return (
    <ul className="grid gap-3">
      {visible.map((report) => (
        <li key={report.id} className="rounded-[14px] border border-[#e8ebf2] bg-white p-4">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px] text-[#627290]">
            <span className="font-raleway font-semibold tracking-[-0.02em] text-[#031d4e]">
              {SOURCE_LABEL[report.source] || report.source}
            </span>
            {report.created_at && <span>{timeAgo(report.created_at)}</span>}
            {report.location.label && <span>{report.location.label}</span>}
            {report.is_duplicate && <span className="text-[#d9546a]">sounds like a reprint</span>}
          </div>
          {report.title && <p className="mt-2 text-[14px] font-semibold tracking-[-0.02em]">{report.title}</p>}
          <p className="mt-1 text-[14px] leading-relaxed text-[#31405e]">&ldquo;{report.excerpt}&rdquo;</p>
          {isUsableSourceUrl(report.source_url) && (
            <a
              href={report.source_url!}
              target="_blank"
              rel="noopener noreferrer"
              className="mt-2 inline-block text-[13px] text-[#031d4e] underline decoration-[#c0d4ef] decoration-2 underline-offset-4 hover:decoration-[#031d4e]"
            >
              {linkLabel}
              {host(report.source_url!) ? ` (${host(report.source_url!)})` : ""}
            </a>
          )}
        </li>
      ))}
    </ul>
  );
}
