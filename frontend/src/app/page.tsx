"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Feed, ProductCard } from "@/lib/types";
import { getCity } from "@/lib/identity";
import { LocationPrompt } from "@/components/LocationPrompt";
import { RecentCarousel } from "@/components/RecentCarousel";
import { ProductRow } from "@/components/ProductRow";
import { GeoMap } from "@/components/GeoMap";
import { POSTED_EVENT } from "@/components/PostModal";

/**
 * The three feed sections (community / official / CAERS) are hidden to match the Figma home page.
 * Their data still feeds the carousel. Set to true to show them again.
 */
const SHOW_TIER_SECTIONS = false;

const FEED_CACHE_KEY = "rmm-home-feed-v2";
const FEED_CACHE_MAX_AGE_MS = 30 * 1000; // paint stale briefly, then always soft-refresh

function readCachedFeed(city: string | null): Feed | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = sessionStorage.getItem(FEED_CACHE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as { city: string | null; at: number; feed: Feed };
    if ((parsed.city || null) !== (city || null)) return null;
    if (Date.now() - parsed.at > FEED_CACHE_MAX_AGE_MS) return null;
    return parsed.feed;
  } catch {
    return null;
  }
}

function writeCachedFeed(city: string | null, feed: Feed) {
  try {
    sessionStorage.setItem(FEED_CACHE_KEY, JSON.stringify({ city, at: Date.now(), feed }));
  } catch {
    /* quota / private mode — ignore */
  }
}

export default function HomePage() {
  // Start as null on both server and client; the saved city is read after mount.
  // Reading localStorage during render made the server and browser HTML disagree.
  const [city, setCity] = useState<string | null>(null);
  const [cityReady, setCityReady] = useState(false);
  const [feed, setFeed] = useState<Feed | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async (nextCity: string | null, { soft = false }: { soft?: boolean } = {}) => {
    try {
      // Soft refresh: keep showing the last feed (news-site style) while we refetch.
      if (!soft) setLoading(true);
      setError(null);
      const next = await api.feed(nextCity);
      setFeed(next);
      writeCachedFeed(nextCity, next);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load the latest stories");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    setCity(getCity());
    setCityReady(true);
  }, []);

  useEffect(() => {
    if (!cityReady) return;
    // No saved city → treat as Atlanta for the local shelf / map (demo default).
    const effectiveCity = city || "Atlanta";
    const cached = readCachedFeed(effectiveCity);
    if (cached) {
      setFeed(cached);
      setLoading(false);
      // Refresh in background — page already looks full.
      load(effectiveCity, { soft: true });
    } else {
      load(effectiveCity);
    }
    const refresh = () => load(effectiveCity, { soft: true });
    window.addEventListener(POSTED_EVENT, refresh);
    return () => window.removeEventListener(POSTED_EVENT, refresh);
  }, [city, cityReady, load]);

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
  // Snapshot demos often have no "nearby" until a city is chosen — still show map density
  // from priority / official cards so the home map isn't empty.
  const mapGeo = (() => {
    const buckets = new Map<string, { label: string; count: number; latitude: number | null; longitude: number | null }>();
    const sources = [
      ...(feed?.nearby || []),
      ...(feed?.priority_foods || []),
      ...(feed?.important || []),
    ];
    for (const card of sources) {
      for (const g of card.signal.geography || []) {
        const prev = buckets.get(g.label);
        if (!prev || g.count > prev.count) {
          buckets.set(g.label, {
            label: g.label,
            count: g.count,
            latitude: g.latitude ?? null,
            longitude: g.longitude ?? null,
          });
        } else {
          prev.count += g.count;
        }
      }
    }
    // Prefer nearby-only when the visitor city matched local cards.
    return nearbyGeo.length ? nearbyGeo : Array.from(buckets.values());
  })();
  // Local-only shelf — never fall back to national Priority foods.
  const mayUse = feed ? (feed.nearby || []).slice(0, 4) : null;
  const priorityFoods = (feed?.priority_foods?.length
    ? feed.priority_foods
    : [...official, ...unofficial, ...caers]
  ).slice(0, 12);
  const showSkeletons = loading && !feed;
  // Top band leads with what only this app shows: complaints with no official recall yet.
  // Official recalls still lead the "Priority foods" list below.
  const earlyCards = [...unofficial, ...caers].slice(0, 16);
  const heroCards = earlyCards.length
    ? earlyCards
    : (feed?.priority_foods?.length ? feed.priority_foods : [...official, ...unofficial, ...caers]).slice(0, 16);

  return (
    <div>
      <LocationPrompt onChange={onCityChange} />

      {error && (
        <p role="alert" className="card mb-8 p-5 text-sm text-[#d9546a]">
          {error}. Please make sure the app is running.
        </p>
      )}

      <section aria-labelledby="recent-title" aria-busy={showSkeletons}>
        <div className="flex flex-wrap items-end gap-x-4 gap-y-1">
          <h2 id="recent-title" className="section-title">
            {earlyCards.length || !feed ? "Not recalled yet" : "Recent updates"}
          </h2>
          {(earlyCards.length > 0 || !feed) && (
            <p className="pb-1 text-[13px] text-[#627290]">
              Public complaints with no official recall. Early signals, not proof.
            </p>
          )}
        </div>
        {/* Band sits exactly behind the scrolling window */}
        <div className="mt-4 overflow-hidden bg-[#9DBAD7] py-2">
          {heroCards.length ? (
            <RecentCarousel products={heroCards} />
          ) : showSkeletons ? (
            <div className="flex gap-[30px] overflow-hidden pb-[18px] pt-[15px]">
              {Array.from({ length: 5 }, (_, i) => (
                <div key={i} className="skeleton h-[370px] w-[335px] shrink-0" />
              ))}
            </div>
          ) : (
            <p className="px-6 py-8 text-sm text-[#031d4e]">
              No updates yet. Community reports and recent official items fill this section.
            </p>
          )}
        </div>
      </section>

      {SHOW_TIER_SECTIONS && (
        <>
        <TierSection
          id="unofficial"
          title="Community / open web"
          blurb="Neighbor posts, iWasPoisoned, and Reddit-style conjecture — the early signal, not a verdict."
          products={unofficial}
          loading={showSkeletons}
          empty="No community reports yet. Post with + or search a food brand."
          disclaimer="Unofficial chatter is a heads-up, not proof of harm."
        />

        <TierSection
          id="official"
          title="Urgent official items"
          blurb="Newest Ongoing FDA/USDA-FSIS recalls and active outbreak watches only — resolved or stale notices are removed."
          products={official}
          loading={showSkeletons}
          empty="No recent Ongoing official items right now."
        />

        <TierSection
          id="caers"
          title="Complaint reports (CAERS)"
          blurb="Foods with FDA-hosted adverse event reports. Not a recall — unverified; report ≠ causation."
          products={caers}
          loading={showSkeletons}
          empty="No CAERS items loaded yet."
          disclaimer="CAERS reports are largely voluntary and do not prove a product caused harm."
        />
        </>
      )}

      <div className="mt-10 grid gap-10 lg:grid-cols-[710px_1fr] lg:gap-[53px]">
        <section aria-labelledby="area-title">
          <h2 id="area-title" className="section-title">
            In your area · {city || "Atlanta"}
          </h2>
          <GeoMap geography={mapGeo} city={city || "Atlanta"} className="mt-[13px] h-[360px] md:h-[465px]" />
        </section>

        <section aria-labelledby="use-title">
          <h2 id="use-title" className="section-title">Products you may use</h2>
          <p className="mt-2 max-w-[40ch] text-[13px] leading-relaxed text-[#627290]">
            Grocery foods neighbors near {city || "Atlanta"} are talking about — not the national priority list.
          </p>
          <div className="mt-[23px] grid gap-[17px]">
            {mayUse?.length
              ? mayUse.map((product) => <ProductRow key={product.slug} product={product} />)
              : showSkeletons
                ? Array.from({ length: 4 }, (_, i) => <div key={i} className="skeleton h-[86px]" />)
                : (
                  <p className="text-sm text-[#627290]">
                    No local grocery reports near {city || "Atlanta"} yet. Priority foods below still cover national notices.
                  </p>
                )}
          </div>
        </section>
      </div>

      {feed && (
        <section aria-labelledby="priority-title" className="mt-14">
          <h2 id="priority-title" className="section-title">Priority foods</h2>
          <p className="mt-2 max-w-[70ch] text-[14px] leading-relaxed text-[#627290]">
            Grocery items ranked by shopper urgency — product recalls first (hazard + size + recency),
            then outbreak watches, then linked community reports, then CAERS. Not an AI ranking.
          </p>
          <div className="mt-5 grid max-w-[870px] gap-[14px]">
            {priorityFoods.length
              ? priorityFoods.map((product) => (
                  <ProductRow key={`priority-${product.slug}`} product={product} />
                ))
              : (
                <p className="text-sm text-[#627290]">No grocery foods with linked sources yet.</p>
              )}
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