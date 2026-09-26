"use client";

import { useParams, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { ProductDetail } from "@/lib/types";
import { Tag } from "@/components/Tag";
import { GeoMap } from "@/components/GeoMap";
import { EvidenceList, isInternetReport, isSiteReport } from "@/components/EvidenceList";
import { Community } from "@/components/Community";
import { Disclaimer } from "@/components/Disclaimer";

export default function ProductPage() {
  const { slug } = useParams<{ slug: string }>();
  const params = useSearchParams();
  const issue = params.get("issue");
  const [product, setProduct] = useState<ProductDetail | null>(null);
  const [discoverNote, setDiscoverNote] = useState<string | null>(null);

  const load = useCallback(() => {
    api.product(slug, issue).then(setProduct);
  }, [slug, issue]);

  useEffect(() => {
    load();
  }, [load]);

  if (!product) {
    return <div className="card p-6 text-[#5a6d80]">One moment — gathering the story…</div>;
  }

  const signal = product.signal;
  const official = product.official_status;

  return (
    <div className="grid gap-8">
      <header>
        <div className="mb-3 flex flex-wrap gap-2">
          {product.tags.map((tag) => (
            <Tag key={tag} label={tag} />
          ))}
        </div>
        <div className="text-xs uppercase tracking-[0.14em] text-[#5b8fb5]">
          {product.brand} · {product.category}
          {product.model ? ` · ${product.model}` : ""}
        </div>
        <h1 className="serif mt-2 text-5xl leading-tight">{product.name}</h1>
      </header>

      <section
        className={`card p-6 ${
          official.state === "official_recall" ? "border-[#e8a8b0]" : "border-[#b7d7c6]"
        }`}
      >
        <div className="section-kicker">Has this been recalled?</div>
        <h2 className="serif mt-2 text-3xl">
          {official.state === "official_recall"
            ? "Yes — official recall"
            : "No official recall found"}
        </h2>
        <p className="mt-2 max-w-3xl text-[#5a6d80]">{official.detail}</p>
        {official.recall && (
          <div className="mt-4 text-sm leading-relaxed">
            Recalled by {official.recall.agency} on {official.recall.recall_date}. {official.recall.reason}{" "}
            <a className="text-[#5b8fb5] underline" href={official.recall.source_url}>
              Read the official notice
            </a>
          </div>
        )}
      </section>

      <section className="card p-6">
        <div className="section-kicker">What neighbors are noticing</div>
        <h2 className="serif mt-2 text-3xl">
          {signal.official_recall ? "Neighbor reports next to the recall" : signal.severity_label}
        </h2>
        <p className="mt-3 max-w-3xl text-[#5a6d80]">{signal.explanation}</p>
        <dl className="mt-6 grid grid-cols-2 gap-4 text-sm md:grid-cols-5">
          <Metric label="Reports" value={signal.report_count} />
          <Metric label="Different people" value={signal.independent_count} />
          <Metric label="Last 7 days" value={signal.recent_report_count} />
          <Metric
            label="This week"
            value={signal.velocity_percent != null ? `+${signal.velocity_percent}%` : "—"}
          />
          <Metric label="Places" value={signal.geographic_count} />
        </dl>
        <div className="mt-6">
          <div className="section-kicker">Why are we showing this?</div>
          <p className="mt-2 text-sm text-[#5a6d80]">{signal.explanation}</p>
        </div>
      </section>

      <section>
        <h3 className="section-kicker mb-3">What people keep mentioning</h3>
        <div className="flex flex-wrap gap-2">
          {signal.issues.map((item) => (
            <Link
              key={item.slug}
              href={`/product/${product.slug}?issue=${item.slug}`}
              className={`rounded-full px-4 py-2 text-sm ${issue === item.slug ? "bg-[#1a365d] text-white" : "bg-white border border-[#e4d9c8]"}`}
            >
              {item.icon} {item.name} — {item.count}
            </Link>
          ))}
          {issue && (
            <Link href={`/product/${product.slug}`} className="rounded-full px-4 py-2 text-sm text-[#5a6d80]">
              Show everything
            </Link>
          )}
        </div>
      </section>

      <section>
        <h3 className="section-kicker mb-3">What people around you are saying</h3>
        <GeoMap geography={signal.geography} />
      </section>

      {!!product.timeline.length && (
        <section className="card p-6">
          <h3 className="section-kicker">Before the official recall</h3>
          <p className="mt-2 text-sm text-[#5a6d80]">
            A simple demo of how reports piled up first. This is not a claim that the app predicted the recall.
          </p>
          <ol className="mt-5 space-y-3">
            {product.timeline.map((event) => (
              <li key={event.day_offset} className="flex gap-4">
                <div className="w-16 text-sm text-[#5b8fb5]">Day {event.day_offset}</div>
                <div>
                  <div>{event.label}</div>
                  <div className="text-sm text-[#5a6d80]">{event.report_count} reports</div>
                </div>
              </li>
            ))}
          </ol>
        </section>
      )}

      <section>
        <div className="mb-3 flex items-center justify-between">
          <h3 className="section-kicker">From the internet</h3>
          <button
            onClick={async () => {
              const result = await api.discover(product.slug);
              const agents = Array.isArray(result.agent_log) ? result.agent_log.length : 0;
              setDiscoverNote(
                result.provider
                  ? `Agents searched via ${result.provider}: kept ${result.ingested} signal-grade pages` +
                      (agents ? ` (${agents}-step pipeline).` : ".")
                  : "Live web search is optional. Neighbor notes on this site still count.",
              );
              load();
            }}
            className="text-sm text-[#5b8fb5]"
          >
            Run complaint agents
          </button>
        </div>
        {discoverNote && <p className="mb-3 text-sm text-[#5a6d80]">{discoverNote}</p>}
        <EvidenceList
          reports={product.reports.filter(isInternetReport)}
          requireUrl
          emptyMessage="No linked public pages yet. Try “Run complaint agents.”"
          linkLabel="Open original"
        />
      </section>

      <section>
        <h3 className="section-kicker mb-3">On this site</h3>
        <EvidenceList
          reports={product.reports.filter(isSiteReport)}
          emptyMessage="No neighbor notes on this product yet."
        />
        <div className="mt-6">
          <Community slug={product.slug} posts={product.posts} onChange={load} />
        </div>
      </section>

      <Disclaimer text={product.disclaimer} />
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string | number }) {
  return (
    <div>
      <dt className="text-[#5a6d80]">{label}</dt>
      <dd className="serif text-2xl">{value}</dd>
    </div>
  );
}
