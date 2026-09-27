"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { api, SearchResult } from "@/lib/api";
import { ProductCard } from "@/components/ProductCard";
import { EvidenceList } from "@/components/EvidenceList";
import { NotFoundPrompt } from "@/components/NotFoundPrompt";

function SearchInner() {
  const params = useSearchParams();
  const q = params.get("q") || "";
  const [result, setResult] = useState<SearchResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!q) {
      setResult(null);
      setError(null);
      setLoading(false);
      return;
    }
    let cancelled = false;
    setResult(null);
    setError(null);
    setLoading(true);

    (async () => {
      try {
        // Fast catalog pass first.
        const local = await api.search(q, false);
        if (cancelled) return;
        const localEmpty =
          local.products.length === 0 && local.reports.length === 0 && local.semantic.length === 0;
        if (!localEmpty) {
          setResult(local);
          setLoading(false);
          return;
        }
        // Nothing in catalog — search the open web and add a product.
        setResult(local);
        const live = await api.search(q, true);
        if (cancelled) return;
        setResult(live);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Search failed");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [q]);

  const empty =
    !!result &&
    result.products.length === 0 &&
    result.reports.length === 0 &&
    result.semantic.length === 0;

  return (
    <div>
      <h1 className="serif text-4xl">Look something up</h1>
      <p className="mt-2 text-[#627290]">
        Try a brand, a product, or plain English — “raw meat”, “got sick after”, “iwaspoisoned”.
      </p>
      {!q && <p className="mt-8 text-[#627290]">Type a few words in the search box above.</p>}
      {q && loading && (
        <p className="mt-8 text-[#627290]">
          {result && result.products.length === 0
            ? "Nothing in the catalog yet — searching iWasPoisoned / Reddit / the open web and adding a listing…"
            : "Looking up matching foods…"}
        </p>
      )}
      {error && <p className="mt-8 text-sm text-[#d9546a]">{error}</p>}
      {empty && !loading && <NotFoundPrompt query={q} />}
      {result && !empty && !loading && (
        <div className="mt-8 grid gap-10">
          {result.discovery && (result.discovery.ingested > 0 || result.discovery.message) && (
            <p className="text-sm text-[#627290]">
              {result.discovery.ingested > 0
                ? `Live discovery added ${result.discovery.ingested} public page${result.discovery.ingested === 1 ? "" : "s"} via ${result.discovery.provider || "search"}.`
                : result.discovery.message}
            </p>
          )}
          <section>
            <h2 className="section-kicker mb-4">Products</h2>
            {result.products.length ? (
              <div className="grid gap-[30px] sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                {result.products.map((product) => (
                  <ProductCard key={product.slug} product={product} />
                ))}
              </div>
            ) : (
              <NotFoundPrompt query={q} title="No matching product yet" />
            )}
          </section>
          {!!result.semantic.length && (
            <section>
              <h2 className="section-kicker mb-4">Sounds related</h2>
              <div className="grid gap-3">
                {result.semantic.map((item) => (
                  <a key={item.product.slug} href={`/product/${item.product.slug}`} className="card p-4">
                    <div className="text-sm text-[#627290]">{item.product.name}</div>
                    <p className="mt-1 text-sm text-[#627290]">“{item.matched_excerpt}”</p>
                  </a>
                ))}
              </div>
            </section>
          )}
          {!!result.reports.length && (
            <section>
              <h2 className="section-kicker mb-4">Matching notes</h2>
              <EvidenceList reports={result.reports} />
            </section>
          )}
        </div>
      )}
    </div>
  );
}

export default function SearchPage() {
  return (
    <Suspense>
      <SearchInner />
    </Suspense>
  );
}
