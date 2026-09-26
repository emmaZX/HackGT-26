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
    setResult(null);
    setError(null);
    setLoading(true);
    api
      .search(q)
      .then((data) => {
        setResult(data);
        setError(null);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Search failed"))
      .finally(() => setLoading(false));
  }, [q]);

  const empty =
    !!result &&
    result.products.length === 0 &&
    result.reports.length === 0 &&
    result.semantic.length === 0;

  return (
    <div>
      <h1 className="serif text-4xl">Look something up</h1>
      <p className="mt-2 text-[#5a6d80]">
        Try a brand, a product name, or a plain-English problem like “smells like burning plastic.”
      </p>
      {!q && <p className="mt-8 text-[#5a6d80]">Type a few words in the search box above.</p>}
      {q && loading && (
        <p className="mt-8 text-[#5a6d80]">Looking across the public web for related reports…</p>
      )}
      {error && <p className="mt-8 text-sm text-[#c45c6a]">{error}</p>}
      {empty && !loading && <NotFoundPrompt query={q} />}
      {result && !empty && !loading && (
        <div className="mt-8 grid gap-10">
          {result.discovery && (result.discovery.ingested > 0 || result.discovery.message) && (
            <p className="text-sm text-[#5a6d80]">
              {result.discovery.ingested > 0
                ? `Live discovery added ${result.discovery.ingested} public page${result.discovery.ingested === 1 ? "" : "s"} via ${result.discovery.provider || "search"}.`
                : result.discovery.message}
            </p>
          )}
          <section>
            <h2 className="section-kicker mb-4">Products</h2>
            {result.products.length ? (
              <div className="grid gap-4 md:grid-cols-2">
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
                    <div className="text-sm text-[#5b8fb5]">{item.product.name}</div>
                    <p className="mt-1 text-sm text-[#5a6d80]">“{item.matched_excerpt}”</p>
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
