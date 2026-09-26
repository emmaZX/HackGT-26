"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Feed } from "@/lib/types";
import { getCity } from "@/lib/identity";
import { LocationPrompt } from "@/components/LocationPrompt";
import { ProductCard } from "@/components/ProductCard";
import { EvidenceList, isInternetReport, isUsableSourceUrl } from "@/components/EvidenceList";
import { GeoMap } from "@/components/GeoMap";

export default function HomePage() {
  const [city, setCity] = useState<string | null>(() => getCity());
  const [feed, setFeed] = useState<Feed | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async (nextCity: string | null) => {
    try {
      setLoading(true);
      setError(null);
      setFeed(await api.feed(nextCity));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load the latest stories");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load(city);
  }, [city, load]);

  const onCityChange = useCallback((next: string | null) => {
    setCity(next);
  }, []);

  const nearbyGeo = feed?.nearby.flatMap((card) => card.signal.geography) || [];

  return (
    <div>
      <LocationPrompt onChange={onCityChange} />
      <section className="mb-10 max-w-3xl">
        <p className="section-kicker">Before the official page exists</p>
        <h1 className="serif mt-3 text-5xl leading-[1.08] md:text-6xl">
          The internet often notices food problems first.
        </h1>
        <p className="mt-4 text-lg leading-relaxed text-[#5a6d80]">
          Five discovery agents write niche searches, browse forums and reviews, then keep only
          illness-grade complaints — so pages are backed by real internet signal, not just FDA text.
        </p>
      </section>

      {error && <div className="card mb-8 p-5 text-[#c45c6a]">{error}. Please make sure the app is running.</div>}

      {loading && !feed && <HomeLoading />}

      {!loading || feed ? (
        <>
          <section className="mb-12">
            <h2 className="section-kicker mb-4">Emerging signals</h2>
            <div className="grid gap-4 md:grid-cols-2">
              {feed?.important.map((product) => (
                <ProductCard key={product.slug} product={product} />
              ))}
            </div>
          </section>

          <section className="mb-12 grid gap-6 md:grid-cols-[1.2fr_0.8fr]">
            <div>
              <h2 className="section-kicker mb-4">Near you {city ? `· ${city}` : ""}</h2>
              {feed?.nearby.length ? (
                <div className="grid gap-4">
                  {feed.nearby.map((product) => (
                    <ProductCard key={product.slug} product={product} />
                  ))}
                </div>
              ) : (
                <div className="card p-5 text-sm text-[#5a6d80]">
                  {city
                    ? `Nothing extra clustered in ${city} yet. The bigger stories above still apply everywhere.`
                    : "You can add a city if you want local tags. The page works just fine without it."}
                </div>
              )}
            </div>
            <GeoMap geography={nearbyGeo} />
          </section>

          <section className="mb-12">
            <h2 className="section-kicker mb-4">Getting more attention</h2>
            <div className="card divide-y divide-[#e4d9c8]">
              {(feed?.trending.filter((product) => (product.signal.velocity_percent || 0) > 0).length
                ? feed.trending.filter((product) => (product.signal.velocity_percent || 0) > 0)
                : feed?.important.slice(0, 4)
              )?.map((product) => (
                <a key={product.slug} href={`/product/${product.slug}`} className="flex items-center justify-between px-5 py-4">
                  <span>{product.name}</span>
                  <span className="text-[#c45c6a]">
                    {product.signal.velocity_percent != null && product.signal.velocity_percent > 0
                      ? `↑ ${product.signal.velocity_percent}%`
                      : product.signal.severity_label}
                  </span>
                </a>
              ))}
            </div>
          </section>

          <section>
            <h2 className="section-kicker mb-4">Latest reports</h2>
            <EvidenceList
              reports={(feed?.recent_reports || [])
                .filter((r) => isInternetReport(r) || isUsableSourceUrl(r.source_url))
                .slice(0, 8)}
              requireUrl
              emptyMessage="No linked public reports yet — live discovery fills this section."
              linkLabel="Open original"
            />
          </section>
        </>
      ) : null}
    </div>
  );
}

function HomeLoading() {
  return (
    <div className="mb-12" aria-busy="true" aria-live="polite">
      <div className="mb-4 flex items-center gap-3 text-sm text-[#5a6d80]">
        <span className="home-pulse inline-block h-2.5 w-2.5 rounded-full bg-[#c45c6a]" />
        Gathering emerging signals from saved notes…
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="card home-shimmer h-36 p-5">
            <div className="h-3 w-24 rounded bg-[#e4d9c8]/80" />
            <div className="mt-4 h-6 w-3/4 rounded bg-[#e4d9c8]/70" />
            <div className="mt-3 h-3 w-full rounded bg-[#e4d9c8]/55" />
            <div className="mt-2 h-3 w-5/6 rounded bg-[#e4d9c8]/45" />
          </div>
        ))}
      </div>
    </div>
  );
}
