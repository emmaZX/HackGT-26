"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { api, SearchResult } from "@/lib/api";
import { ProductCard } from "@/components/ProductCard";
import { EvidenceList } from "@/components/EvidenceList";

function SearchInner() {
  const params = useSearchParams();
  const q = params.get("q") || "";
  const [result, setResult] = useState<SearchResult | null>(null);

  useEffect(() => {
    if (!q) return;
    api.search(q).then(setResult);
  }, [q]);

  return (
    <div>
      <h1 className="serif text-4xl">Look something up</h1>
      <p className="mt-2 text-[#5a6d80]">
        Try a brand, a product name, or a plain-English problem like “smells like burning plastic.”
      </p>
      {!q && <p className="mt-8 text-[#5a6d80]">Type a few words in the search box above.</p>}
      {result && (
        <div className="mt-8 grid gap-10">
          <section>
            <h2 className="section-kicker mb-4">Products</h2>
            <div className="grid gap-4 md:grid-cols-2">
              {result.products.map((product) => (
                <ProductCard key={product.slug} product={product} />
              ))}
            </div>
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
          <section>
            <h2 className="section-kicker mb-4">Matching notes</h2>
            <EvidenceList reports={result.reports} />
          </section>
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
