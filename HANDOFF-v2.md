# Source Pivot v2 — Handoff

## Product thesis

Pull large structured sources → deterministic spike math → AI summarizes **only** the spikes.

Category-watchlist Exa discovery is no longer the main home filler. We do **not** claim we monitor Reddit/Twitter as core coverage.

## Three home tiers (honesty)

1. **Official notices** — Ongoing FDA enforcement + USDA-FSIS active recalls + FDA outbreak investigation watches (`OUTBREAK WATCH`). Never invent a recall URL.
2. **Complaint spikes (CAERS)** — openFDA food/event adverse reports; velocity-scored; Gemini summary only when spiked. **Not a recall.** Tag `CAERS SPIKE`, `source_tier=caers`.
3. **Community / open web** — neighbor posts + best-effort iWasPoisoned / Reddit-restricted search. Tag `UNOFFICIAL`.

## What we dropped as core

- Category meal-kit / produce watchlist discovery as the primary path
- Marketing “we monitor Reddit/Twitter”
- Amazon / Bright Data scrapers (out of scope)

## Ingest map

| Source | Tier | Notes |
|--------|------|--------|
| FDA food/enforcement Ongoing | official | Existing overlay |
| FSIS active recalls | official | Live API preferred; Wayback fallback if blocked |
| FDA outbreak investigations table | official | Cards only; no fake Recall row |
| CAERS food/event | caers | Spike scorer; AI on spikes only |
| iWasPoisoned via Exa | unofficial | Best-effort discovery |
| Reddit `site:` pass | unofficial | Logged even when 0 hits |

## Config knobs

- `caers_lookback_days`, `caers_fetch_limit`, `caers_spike_min_reports`, `caers_spike_velocity`
- `home_scrape_products` default **0** (do not fill home from category Exa)

## Demo checklist

1. Feed has non-empty `official` and ideally `caers_spikes`
2. No Terminated FDA on cards
3. CAERS never labeled `FDA RECALL` unless a real Ongoing enforcement match exists
4. Home UI shows three labeled sections with CAERS/unofficial disclaimers
