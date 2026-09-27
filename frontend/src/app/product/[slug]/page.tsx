"use client";

import { useParams, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { ProductDetail } from "@/lib/types";
import { Pill, StatusBadge, splitTags } from "@/components/Tag";
import { GeoMap } from "@/components/GeoMap";
import { EvidenceList, isInternetReport, isSiteReport } from "@/components/EvidenceList";
import { NotFoundPrompt } from "@/components/NotFoundPrompt";
import { Community } from "@/components/Community";
import { Disclaimer } from "@/components/Disclaimer";
import { POSTED_EVENT } from "@/components/PostModal";
import { BackArrow } from "@/components/BackArrow";
import { ProductImage } from "@/components/ProductImage";
import { LeadTime } from "@/components/LeadTime";
import { CaseSummary } from "@/components/CaseSummary";
import { GrokBadge, isGrokSummary } from "@/components/GrokBadge";
import { CategoryPanel } from "@/components/CategoryPanel";

function ProductInner() {
  const router = useRouter();
  const { slug } = useParams<{ slug: string }>();
  const params = useSearchParams();
  const issue = params.get("issue");
  const [product, setProduct] = useState<ProductDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [missing, setMissing] = useState(false);
  const [discoverNote, setDiscoverNote] = useState<string | null>(null);
  const [discovering, setDiscovering] = useState(false);

  const load = useCallback(() => {
    setMissing(false);
    api
      .product(slug, issue)
      .then((data) => {
        setProduct(data);
        setError(null);
      })
      .catch(() => {
        setProduct(null);
        setMissing(true);
      });
  }, [slug, issue]);

  useEffect(() => {
    load();
    window.addEventListener(POSTED_EVENT, load);
    return () => window.removeEventListener(POSTED_EVENT, load);
  }, [load]);

  function goBack() {
    if (window.history.length > 1) router.back();
    else router.push("/");
  }

  const back = (
    <button
      type="button"
      onClick={goBack}
      aria-label="Go back"
      className="-ml-2 rounded-full p-2 text-[#031d4e] transition-colors hover:text-[#8fabd6]"
    >
      <BackArrow className="h-[17px] w-[36px]" />
    </button>
  );

  if (missing) {
    return <NotFoundPrompt query={slug.replace(/-/g, " ")} title="Item not found" />;
  }

  if (error) {
    return (
      <div>
        {back}
        <p role="alert" className="card mt-8 p-6 text-sm text-[#d9546a]">{error}</p>
      </div>
    );
  }

  if (!product) {
    return (
      <div>
        {back}
        <div className="mt-[34px] h-[52px] w-2/3 rounded-xl bg-[#f0f1f7]" />
        <div className="mt-5 grid gap-[38px] lg:grid-cols-[1fr_387px]">
          <div className="skeleton h-[742px]" />
          <div className="skeleton h-[742px]" />
        </div>
      </div>
    );
  }

  const signal = product.signal;
  const official = product.official_status;
  const recall = official.recall;
  const { status, pills } = splitTags(product.tags);
  const sources = product.reports.filter((r) => r.source_url);
  const internet = product.reports.filter(isInternetReport);
  const onSite = product.reports.filter(isSiteReport);
  const tier = product.source_tier || signal.source_tier || "unofficial";
  const tierLabel =
    tier === "official"
      ? signal.outbreak
        ? "Official · outbreak watch"
        : "Official · confirmed notice"
      : tier === "caers"
        ? "CAERS · FDA-hosted reports (not a recall)"
        : "Unofficial · community / open web";

  return (
    <div>
      {back}
      <h1 className="mt-[34px] font-mulish text-[32px] font-semibold leading-[1.1] tracking-[-0.04em] text-black md:text-[44px]">
        {product.name}
      </h1>
      {product.brand && product.brand !== "Unknown" && (
        <p className="mt-2 font-raleway text-[15px] tracking-[-0.02em] text-[#627290]">{product.brand}</p>
      )}
      <p className="mt-3 inline-block rounded-md border border-[#d7dce8] bg-[#f7f8fb] px-3 py-1 text-[12px] font-semibold tracking-wide text-[#031d4e]">
        {tierLabel}
      </p>
      {tier === "caers" && (
        <p className="mt-2 max-w-[65ch] text-[13px] leading-relaxed text-[#627290]">
          Adverse event reports from FDA CAERS — not an official recall. Reports are unverified and do not prove causation.
        </p>
      )}
      {signal.outbreak && (
        <p className="mt-2 max-w-[65ch] text-[13px] leading-relaxed text-[#627290]">
          FDA outbreak investigation #{signal.outbreak.ref}
          {signal.outbreak.pathogen ? ` · ${signal.outbreak.pathogen}` : ""}.
          {signal.outbreak.product_status ? ` Product status: ${signal.outbreak.product_status}.` : ""}
          {" "}This watch is not the same as a product recall unless a recall was separately initiated.
        </p>
      )}

      <div className="mt-5 grid items-start gap-[38px] lg:grid-cols-[1fr_387px]">
        {/* Left: the case */}
        <article className="card min-h-[742px] p-6 md:px-[44px] md:py-[40px]">
          <section>
            <div className="flex flex-wrap items-center gap-3">
              <h2 className="section-title">What&apos;s going on</h2>
              {status && <StatusBadge label={status} />}
            </div>
            <p className="mt-4 font-mulish text-[22px] font-semibold leading-snug tracking-[-0.04em]">
              {official.state === "official_recall" ? official.headline : signal.severity_label}
            </p>
            <p className="mt-2 max-w-[65ch] text-[15px] leading-relaxed text-[#627290]">{official.detail}</p>

            {recall && (
              <div className="mt-5 rounded-[14px] border border-[#ffc5ce] bg-[#fff7f8] p-4 text-[14px] leading-relaxed">
                <p>
                  Recalled by <strong>{recall.agency}</strong> on {recall.recall_date}.
                </p>
                {recall.hazard && <p className="mt-1"><span className="text-[#627290]">Hazard:</span> {recall.hazard}</p>}
                {recall.reason && <p className="mt-1"><span className="text-[#627290]">Why:</span> {recall.reason}</p>}
                <a
                  href={recall.source_url}
                  target="_blank"
                  rel="noreferrer"
                  className="mt-3 inline-block font-semibold text-[#d9546a] underline underline-offset-4"
                >
                  Read the official {recall.agency} notice
                </a>
              </div>
            )}
            {recall?.recall_date && <LeadTime reports={product.reports} recallDate={recall.recall_date} />}
          </section>

          <CaseSummary slug={product.slug} reports={product.reports} />


          <section className="mt-10">
            <h2 className="section-title">Why it&apos;s showing up</h2>
            <p className="mt-4 max-w-[65ch] text-[15px] leading-relaxed">{signal.explanation}</p>
            <dl className="mt-6 grid grid-cols-2 gap-x-6 gap-y-5 sm:grid-cols-5">
              <Metric label="Reports" value={signal.report_count} />
              <Metric label="Different people" value={signal.independent_count} />
              <Metric label="Last 7 days" value={signal.recent_report_count} />
              <Metric
                label="Vs. week before"
                value={signal.velocity_percent != null ? `${signal.velocity_percent > 0 ? "+" : ""}${signal.velocity_percent}%` : "—"}
              />
              <Metric label="Cities" value={signal.geographic_count} />
            </dl>
          </section>

          {!!signal.issues.length && (
            <section className="mt-10">
              <h2 className="section-title">What people mention</h2>
              <div className="mt-4 flex flex-wrap gap-2">
                {signal.issues.map((item) => (
                  <Link
                    key={item.slug}
                    href={`/product/${product.slug}?issue=${item.slug}`}
                    scroll={false}
                    aria-current={issue === item.slug ? "true" : undefined}
                    className={`rounded-full px-4 py-[6px] text-[14px] tracking-[-0.02em] ${
                      issue === item.slug ? "bg-[#031d4e] text-white" : "bg-[#ecf0fc] text-[#031d4e] hover:bg-[#dfe7f8]"
                    }`}
                  >
                    {item.icon} {item.name} · {item.count}
                  </Link>
                ))}
                {issue && (
                  <Link href={`/product/${product.slug}`} scroll={false} className="px-3 py-[6px] text-[14px] text-[#627290] underline underline-offset-4">
                    Show all
                  </Link>
                )}
              </div>
            </section>
          )}

          {!!product.timeline.length && (
            <section className="mt-10">
              <h2 className="section-title">Timeline</h2>
              <p className="mt-3 text-[13px] text-[#627290]">
                How reports built up before the official notice. This doesn&apos;t mean the app predicted the recall.
              </p>
              <ol className="mt-5 border-l-2 border-[#c0d4ef] pl-5">
                {product.timeline.map((event) => (
                  <li key={event.day_offset} className="relative pb-5 last:pb-0">
                    <span
                      aria-hidden
                      className={`absolute -left-[27px] top-[5px] h-3 w-3 rounded-full ${
                        event.event_type.includes("recall") ? "bg-[#ff96a6]" : "bg-[#c0d4ef]"
                      }`}
                    />
                    <div className="text-[13px] text-[#627290]">Day {event.day_offset}</div>
                    <div className="text-[15px]">{event.label}</div>
                    <div className="text-[13px] text-[#627290]">
                      {event.report_count} {event.report_count === 1 ? "report" : "reports"}
                    </div>
                  </li>
                ))}
              </ol>
            </section>
          )}

          <section className="mt-10">
            <div className="flex flex-wrap items-end justify-between gap-3">
              <h2 className="section-title">From the internet ({internet.length})</h2>
              <button
                type="button"
                disabled={discovering}
                onClick={async () => {
                  setDiscovering(true);
                  try {
                    const result = await api.discover(product.slug);
                    const agents = Array.isArray(result.agent_log) ? result.agent_log.length : 0;
                    setDiscoverNote(
                      result.provider
                        ? `Agents searched via ${result.provider}: kept ${result.ingested} signal-grade pages` +
                            (agents ? ` (${agents}-step pipeline).` : ".")
                        : "Live web search is optional. Neighbor notes on this site still count.",
                    );
                    load();
                  } finally {
                    setDiscovering(false);
                  }
                }}
                className="rounded-full border border-[#c0d4ef] px-4 py-[6px] text-[14px] hover:bg-[#f8f8ff] disabled:opacity-50"
              >
                {discovering ? "Running…" : "Run complaint agents"}
              </button>
            </div>
            {discoverNote && <p className="mt-3 text-[13px] text-[#627290]">{discoverNote}</p>}
            <div className="mt-5">
              <EvidenceList
                reports={internet}
                requireUrl
                emptyMessage="No linked public pages yet. Try “run complaint agents.”"
                linkLabel="Open original"
              />
            </div>
          </section>

          <section className="mt-10">
            <h2 className="section-title">On this site ({onSite.length})</h2>
            <div className="mt-5">
              <EvidenceList reports={onSite} emptyMessage="No neighbor notes on this product yet." />
            </div>
          </section>

          <div className="mt-10 border-t border-[#e0e3e9] pt-5">
            <Disclaimer text={product.disclaimer} />
          </div>
        </article>

        {/* Right: the product */}
        <aside className="card p-6 md:px-[41px] md:pb-[36px] md:pt-[41px] lg:sticky lg:top-6">
          <ProductImage
            product={product}
            recall={official.state === "official_recall"}
            className="aspect-[305/290] overflow-hidden rounded-[12px]"
          />
          <div className="mt-6 border-t border-[#e0e3e9] pt-6">
            {pills.length > 0 && (
              <div className="mb-5 flex flex-wrap gap-1">
                {pills.map((tag) => (
                  <Pill key={tag} label={tag} />
                ))}
              </div>
            )}
            <dl className="grid gap-3 text-[14px]">
              <Fact label="Brand" value={product.brand} />
              <Fact label="Model" value={product.model} />
              <Fact label="Category" value={product.category} />
              <Fact label="Maker" value={product.manufacturer} />
              <Fact label="Barcode" value={product.upc} />
            </dl>
            {product.summary && (
              <div className="mt-5">
                {isGrokSummary(product.summary, tier) && (
                  <div className="mb-2">
                    <GrokBadge size="sm" />
                  </div>
                )}
                <p className="text-[13px] leading-relaxed text-[#627290]">{product.summary}</p>
              </div>
            )}
            {sources.length > 0 && (
              <p className="mt-5 text-[13px] text-[#627290]">
                {sources.length} of {product.reports.length} sources link to the original page.
              </p>
            )}
          </div>
        </aside>
      </div>

      {!!signal.geography.length && (
        <section className="mt-12">
          <h2 className="section-title">Where reports come from</h2>
          <GeoMap geography={signal.geography} className="mt-[13px] h-[320px] md:h-[380px]" />
        </section>
      )}

      <CategoryPanel category={product.category} slug={product.slug} />

      <section className="mt-12">
        <h2 className="section-title">Community</h2>
        <div className="mt-5">
          <Community slug={product.slug} posts={product.posts} onChange={load} />
        </div>
      </section>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string | number }) {
  return (
    <div>
      <dt className="text-[13px] text-[#627290]">{label}</dt>
      <dd className="mt-1 font-mulish text-[26px] font-semibold tracking-[-0.04em]">{value}</dd>
    </div>
  );
}

function Fact({ label, value }: { label: string; value: string | null }) {
  if (!value) return null;
  return (
    <div className="flex justify-between gap-4">
      <dt className="text-[#627290]">{label}</dt>
      <dd className="text-right">{value}</dd>
    </div>
  );
}

export default function ProductPage() {
  return (
    <Suspense>
      <ProductInner />
    </Suspense>
  );
}
