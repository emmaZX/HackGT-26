"use client";

import { Fragment, useEffect, useState } from "react";
import { ReportCard } from "@/lib/types";
import { isUsableSourceUrl } from "./EvidenceList";

type Summary = { summary: string | null; cited_ids?: number[]; report_count?: number };

const API = process.env.NEXT_PUBLIC_API_URL || "";

/**
 * Grok-written summary of what people describe, with [id] citations turned into links to the
 * cited reports. Hidden when there are fewer than 2 reports or Grok isn't configured.
 */
export function CaseSummary({ slug, reports }: { slug: string; reports: ReportCard[] }) {
  const [data, setData] = useState<Summary | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    fetch(`${API}/api/products/${encodeURIComponent(slug)}/summary`, { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null))
      .then(setData)
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, [slug, reports.length]);

  if (loading) {
    return (
      <section className="mt-10" aria-busy="true">
        <h2 className="section-title">What people are describing</h2>
        <div className="mt-4 h-16 animate-pulse rounded-[12px] bg-[#f0f3fa]" />
      </section>
    );
  }
  if (!data?.summary) return null;

  const byId = new Map(reports.map((r, i) => [r.id, { report: r, n: i + 1 }]));

  // Turn "[12, 15]" into small numbered links to those reports
  const parts = data.summary.split(/(\[[\d,\s]+\])/g);
  return (
    <section className="mt-10">
      <h2 className="section-title">What people are describing</h2>
      <p className="mt-4 max-w-[65ch] text-[16px] leading-relaxed text-[#031d4e]">
        {parts.map((part, i) => {
          const ids = part.match(/^\[([\d,\s]+)\]$/)?.[1].split(",").map((x) => Number(x.trim()));
          if (!ids) return <Fragment key={i}>{part}</Fragment>;
          return (
            <sup key={i} className="ml-[1px] whitespace-nowrap text-[11px]">
              {ids.map((id, j) => {
                const hit = byId.get(id);
                const label = hit ? hit.n : id;
                const url = hit && isUsableSourceUrl(hit.report.source_url) ? hit.report.source_url! : null;
                return (
                  <Fragment key={id}>
                    {j > 0 && ","}
                    {url ? (
                      <a href={url} target="_blank" rel="noopener noreferrer" className="text-[#627290] underline decoration-[#c0d4ef] underline-offset-2 hover:text-[#031d4e]" title={hit!.report.excerpt}>
                        {label}
                      </a>
                    ) : (
                      <span className="text-[#627290]" title={hit?.report.excerpt}>{label}</span>
                    )}
                  </Fragment>
                );
              })}
            </sup>
          );
        })}
      </p>
      <p className="mt-2 text-[12px] text-[#627290]">
        Summarized by Grok from {data.report_count} reports. It can be wrong: the numbers link to the reports it used.
      </p>
    </section>
  );
}
