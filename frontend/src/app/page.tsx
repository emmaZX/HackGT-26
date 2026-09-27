"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Feed, ProductCard } from "@/lib/types";
import { getCity } from "@/lib/identity";
import { LocationPrompt } from "@/components/LocationPrompt";
import { RecentCarousel } from "@/components/RecentCarousel";
import { ProductRow } from "@/components/ProductRow";
import { GeoMap } from "@/components/GeoMap";
import { EvidenceList, isInternetReport, isUsableSourceUrl } from "@/components/EvidenceList";
import { POSTED_EVENT } from "@/components/PostModal";

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
    const refresh = () => load(city);
    window.addEventListener(POSTED_EVENT, refresh);
    return () => window.removeEventListener(POSTED_EVENT, refresh);
  }, [city, load]);

  const onCityChange = useCallback((next: string | null) => {
    setCity(next);
  }, []);

  const official = feed?.official?.length ? feed.official : (feed?.important || []).filter((c) => c.source_tier === "official" || c.signal.source_tier === "official");
  const caers = feed?.caers_spikes?.length
    ? feed.caers_spikes
    : (feed?.important || []).filter((c) => c.source_tier === "caers" || c.signal.source_tier === "caers");
  const unofficial = feed?.unofficial?.length
    ? feed.unofficial
    : (feed?.important || []).filter((c) => (c.source_tier || c.signal.source_tier || "unofficial") === "unofficial");

  const nearbyGeo = feed?.nearby.flatMap((card) => card.signal.geography) || [];
  const rising = feed?.trending.filter((p) => (p.signal.velocity_percent || 0) > 0) || [];
  const mayUse = feed
    ? (rising.length ? rising : [...official, ...caers, ...unofficial]).slice(0, 4)
    : null;
  const latest = (feed?.recent_reports || [])
    .filter((r) => isInternetReport(r) || isUsableSourceUrl(r.source_url))
    .slice(0, 8);
  const showSkeletons = loading && !feed;
  const heroCards = [...unofficial, ...official, ...caers].slice(0, 16);

  return (
    <div>
      <LocationPrompt onChange={onCityChange} />

      {error && (
        <p role="alert" className="card mb-8 p-5 text-sm text-[#d9546a]">
          {error}. Please make sure the app is running.
        </p>
      )}

      <section aria-labelledby="recent-title" aria-busy={showSkeletons}>
        <h2 id="recent-title" className="section-title">recent updates</h2>
        {heroCards.length ? (
          <RecentCarousel products={heroCards} />
        ) : showSkeletons ? (
          <div className="flex gap-[30px] overflow-hidden pb-[18px] pt-[15px]">
            {Array.from({ length: 5 }, (_, i) => (
              <div key={i} className="skeleton h-[370px] w-[335px] shrink-0" />
            ))}
          </div>
        ) : (
          <p className="mb-6 mt-4 text-sm text-[#627290]">No updates yet. Community reports and recent official items fill this section.</p>
        )}
      </section>

      <TierSection
        id="unofficial"
        title="community / open web"
        blurb="Neighbor posts, iWasPoisoned, and Reddit-style conjecture — the early signal, not a verdict."
        products={unofficial}
        loading={showSkeletons}
        empty="No community reports yet. Post with + or search a food brand."
        disclaimer="Unofficial chatter is a heads-up, not proof of harm."
      />

      <TierSection
        id="official"
        title="urgent official items"
        blurb="Newest Ongoing FDA/USDA-FSIS recalls and active outbreak watches only — resolved or stale notices are removed."
        products={official}
        loading={showSkeletons}
        empty="No recent Ongoing official items right now."
      />

      <TierSection
        id="caers"
        title="complaint reports (CAERS)"
        blurb="Foods with FDA-hosted adverse event reports. Not a recall — unverified; report ≠ causation."
        products={caers}
        loading={showSkeletons}
        empty="No CAERS items loaded yet."
        disclaimer="CAERS reports are largely voluntary and do not prove a product caused harm."
      />

      <div className="mt-4 grid gap-10 lg:grid-cols-[710px_1fr] lg:gap-[53px]">
        <section aria-labelledby="area-title">
          <h2 id="area-title" className="section-title">
            in your area{city ? ` · ${city.toLowerCase()}` : ""}
          </h2>
          <GeoMap geography={nearbyGeo} city={city} className="mt-[13px] h-[360px] md:h-[465px]" />
        </section>

        <section aria-labelledby="use-title">
          <h2 id="use-title" className="section-title">products you may use</h2>
          <div className="mt-[23px] grid gap-[17px]">
            {mayUse
              ? mayUse.map((product) => <ProductRow key={product.slug} product={product} />)
              : Array.from({ length: 4 }, (_, i) => <div key={i} className="skeleton h-[86px]" />)}
          </div>
        </section>
      </div>

      {feed && (
        <section aria-labelledby="latest-title" className="mt-14">
          <h2 id="latest-title" className="section-title">latest reports</h2>
          <div className="mt-5 max-w-[870px]">
            <EvidenceList
              reports={latest}
              requireUrl
              emptyMessage="No linked public reports yet. Live discovery fills this section."
              linkLabel="Open original"
            />
          </div>
          {feed.disclaimer && (
            <p className="mt-6 max-w-[70ch] text-[13px] leading-relaxed text-[#627290]">{feed.disclaimer}</p>
          )}
        </section>
      )}
    </div>
  );
}

function TierSection({
  id,
  title,
  blurb,
  products,
  loading,
  empty,
  disclaimer,
}: {
  id: string;
  title: string;
  blurb: string;
  products: ProductCard[];
  loading: boolean;
  empty: string;
  disclaimer?: string;
}) {
  return (
    <section aria-labelledby={`${id}-title`} className="mt-12">
      <h2 id={`${id}-title`} className="section-title">{title}</h2>
      <p className="mt-2 max-w-[70ch] text-[14px] leading-relaxed text-[#627290]">{blurb}</p>
      <div className="mt-5 grid gap-[14px]">
        {products.length
          ? products.slice(0, 24).map((product) => <ProductRow key={`${id}-${product.slug}`} product={product} />)
          : loading
            ? Array.from({ length: 2 }, (_, i) => <div key={i} className="skeleton h-[86px]" />)
            : (
              <p className="text-sm text-[#627290]">{empty}</p>
            )}
      </div>
      {disclaimer && (
        <p className="mt-3 max-w-[70ch] text-[12px] leading-relaxed text-[#8a94a8]">{disclaimer}</p>
      )}
    </section>
  );
}
