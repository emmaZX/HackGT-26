"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

type Related = {
  category: string;
  window_days: number;
  total_reports: number;
  brand_count: number;
  products: { slug: string; name: string; brand: string; report_count: number; is_current: boolean }[];
};

const API = process.env.NEXT_PUBLIC_API_URL || "";

/**
 * "Across this category": reports for every product in the same food category.
 * Several brands with reports at once can point to a shared supplier. Hidden when this
 * product is the only one in its category with recent reports.
 */
export function CategoryPanel({ category, slug }: { category: string; slug: string }) {
  const [data, setData] = useState<Related | null>(null);

  useEffect(() => {
    const q = new URLSearchParams({ category, exclude: slug });
    fetch(`${API}/api/categories/related?${q}`, { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null))
      .then(setData)
      .catch(() => setData(null));
  }, [category, slug]);

  const others = data?.products.filter((p) => !p.is_current) || [];
  if (!data || !others.length) return null;

  return (
    <section className="mt-12">
      <h2 className="section-title">Across this category</h2>
      <p className="mt-4 max-w-[70ch] text-[15px] leading-relaxed">
        {data.total_reports} {data.total_reports === 1 ? "report" : "reports"} in the last {data.window_days} days
        across {data.products.length} products in <strong>{data.category.toLowerCase()}</strong>
        {data.brand_count > 1 ? `, from ${data.brand_count} different brands` : ""}.
      </p>
      <p className="mt-1 max-w-[70ch] text-[13px] text-[#627290]">
        Problems showing up across several brands at once can point to a shared supplier. It can also be coincidence.
      </p>
      <ul className="mt-5 grid gap-3 sm:grid-cols-2">
        {others.map((p) => (
          <li key={p.slug}>
            <Link
              href={`/product/${p.slug}`}
              className="card flex items-center justify-between gap-3 px-4 py-3 transition-shadow hover:shadow-[0_8px_22px_rgba(3,29,78,0.14)]"
            >
              <span className="min-w-0 truncate text-[14px] tracking-[-0.02em]">
                {p.brand && p.brand !== "Unknown" ? `${p.brand} · ` : ""}
                {p.name}
                {p.brand === "Unknown" ? <span className="text-[#627290]"> (unbranded)</span> : null}
              </span>
              <span className="shrink-0 text-[13px] text-[#627290]">
                {p.report_count} {p.report_count === 1 ? "report" : "reports"}
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
