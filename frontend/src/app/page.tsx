"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Feed } from "@/lib/types";
import { LocationPrompt } from "@/components/LocationPrompt";
import { ProductCard } from "@/components/ProductCard";
import { EvidenceList } from "@/components/EvidenceList";
import { GeoMap } from "@/components/GeoMap";

export default function HomePage() {
  const [city, setCity] = useState<string | null>(null);
  const [feed, setFeed] = useState<Feed | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (nextCity: string | null) => {
    try {
      setFeed(await api.feed(nextCity));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load the latest stories");
    }
  }, []);

  useEffect(() => {
    load(city);
  }, [city, load]);

  const nearbyGeo = feed?.nearby.flatMap((card) => card.signal.geography) || [];

  return (
    <div>
      <LocationPrompt onChange={setCity} />
      <section className="mb-10 max-w-3xl">
        <p className="section-kicker">Hey, did you hear about this?</p>
        <h1 className="serif mt-3 text-5xl leading-[1.08] md:text-6xl">
          Little product problems, gathered in one friendly place.
        </h1>
        <p className="mt-4 text-lg leading-relaxed text-[#5a6d80]">
          Official recalls stay official. Neighbor stories stay neighbor stories.
          Recall Me Maybe just helps you see the pattern without needing a spreadsheet.
        </p>
      </section>

      {error && <div className="card mb-8 p-5 text-[#c45c6a]">{error}. Please make sure the app is running.</div>}

      <section className="mb-12">
        <h2 className="section-kicker mb-4">Worth a look right now</h2>
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
        <h2 className="section-kicker mb-4">What people just shared</h2>
        <EvidenceList reports={feed?.recent_reports || []} />
      </section>
    </div>
  );
}
