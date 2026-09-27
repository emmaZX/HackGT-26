# Source Pivot v2 — Handoff

## Product thesis

Pull large structured sources → deterministic spike math → AI summarizes **only** the spikes.

**Community evidence is fail-closed:** every unofficial internet report needs a real URL + `observed_at` within ~60 days. Prefer empty over invented or ancient results.

## Three home tiers (honesty)

1. **Official notices** — Ongoing FDA enforcement + USDA-FSIS active recalls + FDA outbreak investigation watches (`OUTBREAK WATCH`). Never invent a recall URL.
2. **Complaint spikes (CAERS)** — openFDA food/event adverse reports; velocity-scored; Gemini summary only when spiked. **Not a recall.** Tag `CAERS SPIKE`, `source_tier=caers`.
3. **Community / open web** — URL-backed iWasPoisoned / Reddit / open-web first-person reports that pass `CommunityEvidence` ([`pipeline/evidence_schema.py`](backend/app/pipeline/evidence_schema.py)). Tag `UNOFFICIAL`. Neighbor site posts are real user UGC only — not seeded templates.

## What we dropped as core

- Invented `FOOD_WATCHLIST` illness templates / fake cities / pre-recall inventors
- Category meal-kit / produce watchlist as the primary unofficial shelf
- Marketing “we monitor Reddit/Twitter”
- Amazon / Bright Data scrapers (out of scope)
- Using scrape `created_at` as if it were the complaint date

## Ingest map

| Source | Tier | Notes |
|--------|------|--------|
| FDA food/enforcement Ongoing | official | Existing overlay |
| FSIS active recalls | official | Live API preferred; Wayback fallback if blocked |
| FDA outbreak investigations table | official | Cards only; no fake Recall row |
| CAERS food/event | caers | Spike scorer; AI on spikes only; lookback ~90d |
| iWasPoisoned via Exa | unofficial | Background community seed + discover; requires `observed_at` |
| Reddit `site:` pass | unofficial | Logged even when 0 hits; same date gate |

## Evidence contract (unofficial)

Required: `source_url`, `observed_at` (stored as `Report.incident_date`), glanceable brand/name, `first_person_complaint`, confidence ≥ 0.42.  
Reject: regulator hosts as “neighbor evidence”, vague names (“prepared chicken”), years before cutoff (e.g. 2006), missing date.

## Config knobs

- `discovery_recency_days` default **60**
- `community_min_url_reports` default **2** (1 strong iWasPoisoned allowed)
- `caers_lookback_days` default **90**
- `seed_fake_posts` default **false**
- `home_scrape_products` default **0**

## Demo checklist

1. Feed has non-empty `official` and ideally `caers_spikes`
2. No Terminated FDA / closed outbreaks on cards
3. CAERS never labeled `FDA RECALL` unless a real Ongoing enforcement match exists
4. Unofficial cards each have linked recent URLs (or section empty)
5. No 2006-era / pre-cutoff complaints in search or product evidence
6. Home UI shows three labeled sections with CAERS/unofficial disclaimers
