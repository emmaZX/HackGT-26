"""
Food watchlist + FDA overlay.

Home focuses on unofficial / emerging internet chatter ("the internet knew before the FDA").
Official FDA recalls attach when they exist, but do not bury community severity.
"""

from __future__ import annotations

import logging
import re
import threading
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from .config import get_settings
from .data_sources.fda import fetch_recent_food_recalls
from .data_sources.fsis import fetch_active_recalls as fetch_fsis_recalls
from .data_sources.outbreaks import fetch_active_outbreaks
from .data_sources.caers import fetch_recent_events as fetch_caers_events, product_key as caers_product_key
from .database import SessionLocal
from .models import Comment, DiscoveryRun, Issue, Like, Post, Product, Recall, Report, ReportIssue
from .pipeline.cluster import attach_and_dedupe
from .pipeline.glance_titles import glance_title, is_sensible_product
from .pipeline.product_identity import simplify_food_item
from .pipeline.spikes import score_caers_spike, summarize_caers_spike
from .seed import ISSUES, seed

logger = logging.getLogger(__name__)

HOME_SCRAPE_MARKER = "__home_scrape_food__"
CITIES = ["Atlanta", "Chicago", "Austin", "Boston", "Seattle", "Marietta", "Decatur"]

# Demo watchlist: food items people talk about online before (or without) an FDA notice.
FOOD_WATCHLIST = [
    {
        "slug": "romaine-lettuce-cyclospora-watch",
        "brand": "Salad mixes",
        "name": "Romaine salad mix",
        "summary": "Online reports of stomach illness tied to bagged romaine and salad mixes — watching before any official notice.",
        "issue": "cyclospora",
        "templates": [
            "Three people in my group got sick after the same bagged salad. No recall that I can find.",
            "Reddit thread filling up with romaine stomach bugs this week. Anyone else?",
            "Ate a garden salad mix Tuesday, wrecked by Thursday. Lot code starting with TF.",
            "Local moms group saying keep kids off bagged romaine for now.",
            "Store still stocking the same brand people are complaining about online.",
            "I called poison control because half the dinner party had the same symptoms.",
            "News hasn't covered it yet but foodie Discord is full of salad mix stories.",
            "Throwing mine out. Too many independent posts with the same timeline.",
        ],
    },
    {
        "slug": "cantaloupe-salmonella-watch",
        "brand": "Produce",
        "name": "Cantaloupe",
        "summary": "Cluster of salmonella-like illness posts around cantaloupe before regulators weigh in.",
        "issue": "salmonella",
        "templates": [
            "Two kids sick after the same cantaloupe from Costco. Pediatrician asked about produce.",
            "Saw a TikTok about cantaloupe salmonella — checking my fridge.",
            "Cut melon from the store salad bar. Same symptoms as the online cluster.",
            "No FDA alert yet but grocery subreddit is lighting up.",
            "My partner and I both ill 24h after cantaloupe. Reporting it here.",
            "Hospital friend said they've seen a bump in GI cases mentioning melon.",
        ],
    },
    {
        "slug": "deli-meat-listeria-watch",
        "brand": "Deli meat",
        "name": "Turkey and ham slices",
        "summary": "Parents and caregivers posting about deli meat concerns while waiting on official guidance.",
        "issue": "listeria",
        "templates": [
            "OB said avoid deli meat again — seeing more posts about turkey slices.",
            "Same brand lunch meat, same week, three coworkers out sick.",
            "No recall flyer in store. Internet is ahead of the shelf tags.",
            "Threw out the opened pack after reading the cluster posts.",
            "Local news still quiet. Neighborhood app is not.",
        ],
    },
    {
        "slug": "alfalfa-sprouts-watch",
        "brand": "Alfalfa sprouts",
        "name": "Alfalfa sprouts",
        "summary": "Recurring online warnings about sprouts and foodborne illness.",
        "issue": "salmonella",
        "templates": [
            "Every few months sprouts go viral for the wrong reason. Seeing it again.",
            "Smoothie place still using alfalfa. Comments section is chaos.",
            "Got violently ill after a sprout sandwich. Matching other posts.",
            "Hoping FDA moves faster than last time.",
        ],
    },
    {
        "slug": "soft-cheese-listeria-watch",
        "brand": "Dairy",
        "name": "Soft cheese",
        "summary": "Community flags around soft cheese before formal recall language shows up.",
        "issue": "listeria",
        "templates": [
            "Pregnant and scared — lots of soft cheese posts this month.",
            "Queso fresco from the market. Same story as three other people online.",
            "No official recall page yet. Screenshotting the threads.",
            "Returned it anyway. Internet consensus was enough for me.",
        ],
    },
    # Speculative emerging watches — aim for online chatter without an FDA page yet.
    {
        "slug": "protein-powder-stomach-watch",
        "brand": "Supplements",
        "name": "Protein powder",
        "summary": "People posting GI illness after the same protein powders — watching before any official notice.",
        "issue": "food-contamination",
        "templates": [
            "Three gym friends sick after the same protein tub lot. No recall I can find.",
            "Reddit fitness thread filling up with stomach bug + protein powder stories.",
            "RTD shake from the same brand wrecked my weekend. Anyone else?",
            "Local group chat saying skip that powder for now.",
            "Throwing mine out. Too many independent posts with the same timing.",
        ],
    },
    {
        "slug": "meal-kit-chicken-illness-watch",
        "brand": "Meal kits",
        "name": "Prepared chicken",
        "summary": "Neighbor notes about meal-kit chicken illness clusters before regulators weigh in.",
        "issue": "salmonella",
        "templates": [
            "Same meal kit chicken, same night, whole house sick.",
            "App reviews mentioning salmonella-like symptoms this week.",
            "No official notice yet but the Discord is loud.",
            "Customer service gave a refund. Still no public recall page.",
            "Reporting here so others can compare notes.",
        ],
    },
]


def ensure_issue_taxonomy(db: Session) -> None:
    for slug, name, description, category, icon in ISSUES:
        if db.query(Issue).filter(Issue.slug == slug).one_or_none():
            continue
        db.add(Issue(slug=slug, name=name, description=description, category=category, icon=icon))
    # Food-focused issues used by the watchlist
    extras = [
        ("cyclospora", "Cyclospora", "Parasite linked to produce outbreaks.", "foodborne", "🥬"),
        ("salmonella", "Salmonella", "Foodborne bacterial illness reports.", "foodborne", "🦠"),
        ("listeria", "Listeria", "Foodborne bacterial illness reports.", "foodborne", "🦠"),
        ("e-coli", "E. coli", "Foodborne bacterial illness reports.", "foodborne", "🦠"),
        ("food-contamination", "Food contamination", "General food contamination reports.", "foodborne", "⚠️"),
        ("undeclared-allergen", "Undeclared allergen", "Allergen not listed on packaging.", "allergen", "🥜"),
    ]
    for slug, name, description, category, icon in extras:
        if db.query(Issue).filter(Issue.slug == slug).one_or_none():
            continue
        db.add(Issue(slug=slug, name=name, description=description, category=category, icon=icon))
    db.commit()


def bootstrap_catalog(db: Session) -> list[Product]:
    """Official overlays + evidence-backed community discovery. No invented watchlist illness."""
    settings = get_settings()
    ensure_issue_taxonomy(db)
    purged = purge_placeholder_reports(db)
    if purged:
        logger.info("Removed %s placeholder example.com reports", purged)

    if settings.seed_demo:
        from .seed import seed_if_empty

        seed_if_empty(db)
        return db.query(Product).all()

    # Do NOT seed FOOD_WATCHLIST template illness reports — those were fake.
    # Wipe any leftover invented community rows, then quality-scrub.
    purge_fake_community_data(db)
    purge_agency_internet_reports(db)
    scrub_catalog_quality(db)
    db.commit()

    # Official + CAERS + real community web refresh in the background.
    start_official_overlays_background()
    start_caers_refresh_background()
    start_community_seed_background()

    home = (
        db.query(Product)
        .filter(Product.category == "Food")
        .order_by(Product.id)
        .limit(settings.home_scrape_products)
        .all()
    )
    # seed_fake_posts remains available but defaults off — never invent neighbor posts.
    if settings.seed_fake_posts and home:
        seed_fake_posts(db, home)
    return home


def purge_fake_community_data(db: Session) -> dict:
    """
    Remove invented watchlist reports (null URL community), fake city seeds,
    and ancient / undated web evidence outside the recency window.
    """
    from .models import Embedding
    from .pipeline.evidence_schema import text_has_ancient_year, within_recency

    settings = get_settings()
    removed_reports = 0
    removed_posts = 0

    doomed_reports = (
        db.query(Report)
        .filter(
            Report.is_user_generated.is_(True),
            Report.source.in_(["community", "user_report"]),
            Report.source_url.is_(None),
        )
        .all()
    )
    # Also drop web/reddit rows that are ancient or lack observed date + look stale.
    for report in db.query(Report).filter(Report.is_user_generated.is_(False)).all():
        if report.source in {"caers", "fda_outbreak", "fda", "fsis"}:
            continue
        blob = f"{report.title or ''} {report.text or ''} {report.source_url or ''}"
        if text_has_ancient_year(blob):
            doomed_reports.append(report)
            continue
        if report.source_url and report.incident_date and not within_recency(report.incident_date):
            doomed_reports.append(report)
            continue
        # URL-less non-user internet rows should not exist.
        if not report.source_url and report.source in {"web", "reddit", "news", "iwaspoisoned"}:
            doomed_reports.append(report)

    # Restaurant iWasPoisoned pages are never valid community evidence.
    from .pipeline.evidence_schema import is_allowed_iwaspoisoned_url

    for report in db.query(Report).filter(Report.source_url.isnot(None)).all():
        url = report.source_url or ""
        if "iwaspoisoned.com" not in url.lower():
            continue
        if not is_allowed_iwaspoisoned_url(
            url, title=report.title or "", snippet=report.excerpt or report.text or ""
        ):
            doomed_reports.append(report)

    seen_ids: set[int] = set()
    for report in doomed_reports:
        if report.id in seen_ids:
            continue
        seen_ids.add(report.id)
        _hard_delete_report(db, report)
        removed_reports += 1

    # Fake seed posts (generic templates without a linked report).
    fake_bodies = (
        "Watching this page for any real links",
        "Still no shelf tag at my store",
        "Glad early chatter is collected",
        "Official notice may catch up later",
        "people are linking",
    )
    for post in db.query(Post).all():
        body = post.body or ""
        if any(bit in body for bit in fake_bodies) and not post.report_id:
            comments = db.query(Comment).filter(Comment.post_id == post.id).all()
            for c in comments:
                db.delete(c)
            likes = db.query(Like).filter(Like.post_id == post.id).all()
            for like in likes:
                db.delete(like)
            db.delete(post)
            removed_posts += 1

    # Orphan watchlist products with no official/CAERS/URL evidence.
    watch_slugs = {item["slug"] for item in FOOD_WATCHLIST}
    deleted_products = 0
    for product in db.query(Product).filter(Product.slug.in_(watch_slugs)).all():
        has_recall = db.query(Recall).filter(Recall.product_id == product.id).count() > 0
        url_reports = (
            db.query(Report)
            .filter(Report.product_id == product.id, Report.source_url.isnot(None))
            .count()
        )
        if has_recall or url_reports:
            continue
        _hard_delete_product(db, product)
        deleted_products += 1

    if removed_reports or removed_posts or deleted_products:
        logger.info(
            "Purged fake community: reports=%s posts=%s products=%s",
            removed_reports,
            removed_posts,
            deleted_products,
        )
    return {
        "reports": removed_reports,
        "posts": removed_posts,
        "products": deleted_products,
        "recency_days": settings.discovery_recency_days,
    }


def _hard_delete_report(db: Session, report: Report) -> None:
    from .models import Embedding

    db.query(Report).filter(Report.duplicate_of_id == report.id).update(
        {Report.duplicate_of_id: None}, synchronize_session=False
    )
    db.query(Post).filter(Post.report_id == report.id).update(
        {Post.report_id: None}, synchronize_session=False
    )
    try:
        db.query(Embedding).filter(Embedding.report_id == report.id).delete(
            synchronize_session=False
        )
    except Exception:
        pass
    db.query(ReportIssue).filter(ReportIssue.report_id == report.id).delete(
        synchronize_session=False
    )
    db.delete(report)


def purge_placeholder_reports(db: Session) -> int:
    """Drop demo internet reports that pointed at example.com placeholders."""
    from .models import Embedding

    placeholders = (
        db.query(Report)
        .filter(Report.source_url.isnot(None), Report.source_url.contains("example.com"))
        .all()
    )
    if not placeholders:
        return 0
    ids = [r.id for r in placeholders]
    # Clear FKs that point at these reports before delete.
    db.query(Report).filter(Report.duplicate_of_id.in_(ids)).update(
        {Report.duplicate_of_id: None}, synchronize_session=False
    )
    db.query(Post).filter(Post.report_id.in_(ids)).update({Post.report_id: None}, synchronize_session=False)
    db.query(Embedding).filter(Embedding.report_id.in_(ids)).delete(synchronize_session=False)
    db.query(ReportIssue).filter(ReportIssue.report_id.in_(ids)).delete(synchronize_session=False)
    for report in placeholders:
        db.delete(report)
    db.commit()
    return len(ids)


def purge_agency_internet_reports(db: Session) -> int:
    """
    Drop scraped CDC/FDA archive pages from the internet evidence list.
    Official status lives on Recall rows — agency HTML should not masquerade as neighbor chatter.
    """
    from .models import Embedding

    agency_bits = ("cdc.gov", "fda.gov", "accessdata.fda.gov", "fsis.usda.gov", "foodsafety.gov")
    reports = (
        db.query(Report)
        .filter(Report.source_url.isnot(None), Report.is_user_generated.is_(False))
        .all()
    )
    doomed = [
        r
        for r in reports
        if r.source not in {"caers", "fda_outbreak"}
        and r.source_url
        and any(bit in r.source_url.lower() for bit in agency_bits)
    ]
    if not doomed:
        return 0
    ids = [r.id for r in doomed]
    db.query(Report).filter(Report.duplicate_of_id.in_(ids)).update(
        {Report.duplicate_of_id: None}, synchronize_session=False
    )
    db.query(Post).filter(Post.report_id.in_(ids)).update({Post.report_id: None}, synchronize_session=False)
    db.query(Embedding).filter(Embedding.report_id.in_(ids)).delete(synchronize_session=False)
    db.query(ReportIssue).filter(ReportIssue.report_id.in_(ids)).delete(synchronize_session=False)
    for report in doomed:
        db.delete(report)
    db.commit()
    logger.info("Removed %s agency scraped reports from internet evidence", len(ids))
    return len(ids)


bootstrap_from_cpsc = bootstrap_catalog


def _seed_watch_product(db: Session, item: dict) -> Product:
    """Create a product shell only — never invent illness reports or cities."""
    existing = db.query(Product).filter(Product.slug == item["slug"]).one_or_none()
    if existing:
        return existing
    product = Product(
        slug=item["slug"],
        brand=item["brand"],
        name=item["name"],
        category="Food",
        summary=item["summary"],
    )
    db.add(product)
    db.flush()
    return product

def _overlay_fda_recalls(db: Session, limit: int = 25) -> None:
    """Attach Ongoing FDA recalls to watchlist matches and upsert extra grocery SKUs."""
    purge_non_ongoing_recalls(db)
    recalls = fetch_recent_food_recalls(limit=max(limit, 80))
    pool = [item for item in recalls if (item.get("status") or "").lower() == "ongoing"]
    # Extra targeted Ongoing searches for watch products still unmatched.
    pool.extend(
        item
        for item in _targeted_watch_recalls()
        if (item.get("status") or "").lower() == "ongoing"
    )
    # De-dupe by recall id / slug while preserving order.
    seen_keys: set[str] = set()
    deduped: list[dict] = []
    for item in pool:
        key = str(item.get("recall_id") or item.get("slug") or "")
        if not key or key in seen_keys:
            continue
        seen_keys.add(key)
        deduped.append(item)
    pool = deduped

    watch = {p.slug: p for p in db.query(Product).filter(Product.category == "Food").all()}
    fda_extra = 0
    max_extra = max(limit, 60)

    for item in pool:
        if (item.get("status") or "").lower() != "ongoing":
            continue
        matched = _match_watch_product(watch, item)
        if matched:
            _attach_recall(db, matched, item)
            continue

        existing = db.query(Product).filter(Product.slug == item["slug"]).one_or_none()
        if existing:
            if item.get("brand"):
                existing.brand = str(item["brand"])[:120]
            if item.get("name"):
                existing.name = str(item["name"])[:180]
            if item.get("summary"):
                existing.summary = str(item["summary"])[:500]
            _attach_recall(db, existing, item)
            watch[existing.slug] = existing
            continue

        if fda_extra >= max_extra:
            continue
        hazard = (item.get("hazard") or item.get("reason") or "").lower()
        # Prefer pathogen / allergen / contamination notices for the bigger shelf.
        if hazard and not any(
            n in hazard
            for n in (
                "cyclospora",
                "salmonella",
                "listeria",
                "e. coli",
                "e coli",
                "contamination",
                "allergen",
                "undeclared",
                "botulism",
                "hepatitis",
                "cronobacter",
                "lead",
                "metal",
                "glass",
            )
        ):
            continue
        product = Product(
            slug=item["slug"][:160],
            brand=item["brand"],
            name=item["name"],
            category="Food",
            manufacturer=item.get("manufacturer"),
            summary=item.get("summary"),
        )
        db.add(product)
        db.flush()
        _attach_recall(db, product, item)
        watch[product.slug] = product
        fda_extra += 1
    polish_catalog_titles(db)
    logger.info("FDA overlay attached (extra SKUs=%s, pool=%s)", fda_extra, len(pool))


def _targeted_watch_recalls() -> list[dict]:
    """Pull a few Ongoing FDA rows aimed at watchlist gaps (deli turkey, etc.)."""
    import httpx

    from .data_sources.fda import FDA_FOOD_ENFORCEMENT, _normalize

    searches = [
        '(status:"Ongoing") AND (turkey OR deli OR ham) AND listeria',
        '(status:"Ongoing") AND cantaloupe AND salmonella',
        '(status:"Ongoing") AND (queso OR panela OR oaxaca) AND listeria',
        '(status:"Ongoing") AND (protein OR premier OR "lyons magnus" OR shake) AND (cronobacter OR salmonella OR listeria)',
    ]
    out: list[dict] = []
    seen: set[str] = set()
    try:
        with httpx.Client(timeout=30, follow_redirects=True, trust_env=False) as client:
            for search in searches:
                response = client.get(
                    FDA_FOOD_ENFORCEMENT,
                    params={"search": search, "sort": "report_date:desc", "limit": 15},
                )
                if response.status_code >= 400:
                    continue
                for row in response.json().get("results") or []:
                    item = _normalize(row)
                    if not item:
                        continue
                    key = item.get("recall_id") or item.get("slug")
                    if key in seen:
                        continue
                    seen.add(key)
                    out.append(item)
    except Exception:
        logger.exception("Targeted FDA watch search failed")
    return out


def _match_watch_product(watch: dict[str, Product], item: dict) -> Product | None:
    """Require a product needle AND a hazard needle — avoid loose single-word matches."""
    blob = f"{item.get('name','')} {item.get('hazard','')} {item.get('reason','')}".lower()
    rules = [
        (
            "romaine-lettuce-cyclospora-watch",
            ("romaine", "lettuce", "salad mix", "garden salad"),
            ("cyclospora",),
        ),
        (
            "cantaloupe-salmonella-watch",
            ("cantaloupe", "melon"),
            ("salmonella",),
        ),
        (
            "deli-meat-listeria-watch",
            ("deli", "lunch meat", "turkey", "ham", "sliced"),
            ("listeria",),
        ),
        (
            "alfalfa-sprouts-watch",
            ("sprout", "alfalfa"),
            ("salmonella", "e. coli", "ecoli", "escherichia"),
        ),
        (
            "soft-cheese-listeria-watch",
            ("queso", "panela", "oaxaca", "cotija", "requeson", "soft cheese", "brie", "camembert"),
            ("listeria",),
        ),
        (
            "protein-powder-stomach-watch",
            # RTD / brand needles — avoid bare "protein" which matches unrelated foods.
            (
                "premier",
                "lyons magnus",
                "ready-to-drink",
                "rtd",
                "protein shake",
                "protein powder",
                "nutritional drink",
                "nutritional shake",
                "shake",
            ),
            ("cronobacter", "salmonella", "listeria", "clostridium", "botulinum"),
        ),
    ]
    for slug, products, hazards in rules:
        if slug not in watch:
            continue
        if any(p in blob for p in products) and any(h in blob for h in hazards):
            return watch[slug]
    return None


def start_fda_overlay_background() -> None:
    """Back-compat alias — prefer start_official_overlays_background."""
    start_official_overlays_background()


def start_official_overlays_background() -> None:
    """Refresh FDA + FSIS recalls and outbreak watches without blocking startup."""

    def worker() -> None:
        settings = get_settings()
        with SessionLocal() as db:
            try:
                _overlay_fda_recalls(db, limit=settings.fda_food_recall_limit)
                _overlay_fsis_recalls(db, limit=settings.fsis_recall_limit)
                _overlay_outbreaks(db, limit=settings.outbreak_limit)
                db.commit()
                logger.info("Official overlays refresh complete (FDA/FSIS/outbreaks)")
            except Exception:
                logger.exception("Background official overlays failed")
                db.rollback()

    threading.Thread(target=worker, name="official-overlays", daemon=True).start()


def start_caers_refresh_background() -> None:
    """Ingest CAERS events and summarize spikes only."""

    def worker() -> None:
        settings = get_settings()
        with SessionLocal() as db:
            try:
                _overlay_caers(db)
                db.commit()
                logger.info("CAERS refresh complete")
            except Exception:
                logger.exception("Background CAERS refresh failed")
                db.rollback()

    threading.Thread(target=worker, name="caers-refresh", daemon=True).start()


    threading.Thread(target=worker, name="caers-refresh", daemon=True).start()


def start_community_seed_background() -> None:
    """Pull recent iWasPoisoned / Reddit illness pages into unofficial (URL + date required)."""

    def worker() -> None:
        with SessionLocal() as db:
            try:
                result = seed_community_from_web(db)
                db.commit()
                logger.info("Community web seed complete: %s", result)
            except Exception:
                logger.exception("Background community seed failed")
                db.rollback()

    threading.Thread(target=worker, name="community-seed", daemon=True).start()


def _strip_headline_excerpt(text: str) -> str:
    """Drop a news-style first line so quotes read as report body, not headlines."""
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    if len(lines) > 1 and (
        re.search(r"\b(illness|poisoning|causes?|report)\b", lines[0], re.I)
        or " - " in lines[0]
    ):
        return " ".join(lines[1:])
    # Single-line: strip leading chrome phrase
    cleaned = re.sub(
        r"^[^.]{0,80}\b(illness|poisoning|causes?\s+illness)\b[^.]*\.\s*",
        "",
        text or "",
        flags=re.I,
    )
    return cleaned.strip() or (text or "")


def seed_community_from_web(db: Session) -> dict:
    """
    Fixed grocery corpus: crawl iWasPoisoned industry list (Playwright), then
    optionally enrich via Exa (grocery only — no Reddit). User search still uses Exa.
    """
    from .agents.page_fetch_agent import fetch_candidates
    from .agents.triage_agent import should_ingest_as_internet_evidence, triage_complaint
    from .agents.geo_agent import correlate_location
    from .data_sources.page_fetch import domain_of
    from .data_sources.web_search import available_provider, search_web
    from .data_sources.iwaspoisoned_crawl import crawl_grocery_incidents
    from .pipeline.evidence_schema import (
        is_allowed_iwaspoisoned_url,
        parse_observed_at,
        source_label_for_url,
        validate_community_evidence,
    )
    from .pipeline.cluster import attach_and_dedupe

    settings = get_settings()
    days = settings.discovery_recency_days
    year = datetime.utcnow().year

    # 1) Direct HTTPS crawl of grocery listing (capped).
    crawl = crawl_grocery_incidents(
        max_pages=getattr(settings, "iwp_crawl_max_pages", 8),
        max_incidents=getattr(settings, "iwp_crawl_max_incidents", 60),
        days=days,
    )
    candidates: list[dict] = []
    for inc in crawl.get("incidents") or []:
        candidates.append(
            {
                "final_url": inc.url,
                "url": inc.url,
                "text": inc.text,
                "title": inc.title,
                "snippet": (inc.text or "")[:400],
                "published_date": inc.published,
                "host": "iwaspoisoned.com",
                "from_crawl": True,
            }
        )

    # 2) Optional Exa grocery supplement (never Reddit) when crawl is thin.
    # Keep this tiny — home corpus should come from the HTTPS crawl, not Exa burn.
    provider = available_provider()
    hits: list = []
    crawl_ok = not crawl.get("error") and (crawl.get("listed") or 0) > 0
    if provider and len(candidates) < 15 and crawl_ok:
        queries = [
            f"site:iwaspoisoned.com/incident (Costco OR Walmart OR Kroger OR Aldi) (sick OR vomiting) {year}",
            f"site:iwaspoisoned.com/industry/grocery_or_supermarket (sick OR diarrhea) {year}",
        ]
        hits = search_web(queries, limit_per_query=5) or []
        provider = (hits[0].provider if hits else provider) or provider
    elif not crawl_ok:
        logger.warning(
            "Skipping Exa supplement — crawl error=%s pages=%s",
            crawl.get("error"),
            crawl.get("pages"),
        )

    def skip_url(url: str) -> bool:
        host = domain_of(url or "")
        if any(host.endswith(h) or host == h for h in ("fda.gov", "cdc.gov", "fsis.usda.gov", "usda.gov")):
            return True
        if "reddit.com" in (url or "").lower():
            return True
        if "iwaspoisoned.com" in (url or "").lower() and not is_allowed_iwaspoisoned_url(url):
            return True
        return False

    if hits:
        pages = fetch_candidates(
            hits,
            limit=min(40, settings.community_seed_pages),
            skip_url=skip_url,
            rank_url=lambda u: 0 if "iwaspoisoned" in (u or "") else 2,
            is_ingestible=lambda u: bool(u and u.startswith("http")),
            is_agency=skip_url,
        )
        fetched_urls = {(c.get("final_url") or "").split("#")[0].rstrip("/") for c in candidates}
        for p in pages:
            url = (p.get("final_url") or p.get("url") or "").split("#")[0].rstrip("/")
            if url and url not in fetched_urls:
                candidates.append(p)
                fetched_urls.add(url)
        for hit in hits:
            url = (getattr(hit, "url", None) or "").split("#")[0].rstrip("/")
            if not url or url in fetched_urls or skip_url(url):
                continue
            if "iwaspoisoned.com" in url.lower() and not is_allowed_iwaspoisoned_url(
                url, title=hit.title or "", snippet=hit.snippet or ""
            ):
                continue
            if not getattr(hit, "published_date", None) and not parse_observed_at(
                text=f"{hit.title}\n{hit.snippet}", url=url
            ):
                continue
            candidates.append(
                {
                    "final_url": url,
                    "url": url,
                    "text": f"{hit.title}\n{hit.snippet}",
                    "title": hit.title,
                    "snippet": hit.snippet,
                    "published_date": getattr(hit, "published_date", None),
                    "host": domain_of(url),
                }
            )
            fetched_urls.add(url)

    if not candidates:
        db.add(
            DiscoveryRun(
                product_id=None,
                query="iwp-crawl+exa-grocery",
                provider=f"cseed:{provider or 'crawl'}"[:40],
                result_count=0,
                notes=f"no candidates crawl_err={crawl.get('error')} pages={crawl.get('pages')}",
            )
        )
        return {
            "ingested": 0,
            "provider": provider or "crawl",
            "hits": len(hits),
            "crawl": {k: crawl.get(k) for k in ("pages", "listed", "capped", "error")},
        }

    pages = [c for c in candidates if c.get("from_crawl")]

    ingested = 0
    rejected = 0
    for item in candidates:
        url = item.get("final_url") or item.get("url") or ""
        text = item.get("text") or ""
        title = item.get("title") or ""
        verdict = triage_complaint(
            text=text,
            title=title,
            product_hint=title,
            url=url,
            has_official_recall=False,
            recency_days=days,
        )
        host = (item.get("host") or "").lower()
        # iWasPoisoned grocery report / incident pages are first-person by site design.
        if (
            "iwaspoisoned.com" in host
            and (
                "/report" in (url or "").lower()
                or "/incident" in (url or "").lower()
                or "grocery_or_supermarket" in (url or "").lower()
            )
            and verdict.get("label") in {"uncertain", "noise", "first_person_complaint"}
            and not verdict.get("stale")
        ):
            verdict = {
                **verdict,
                "label": "first_person_complaint",
                "score": max(float(verdict.get("score") or 0), 0.55),
                "reason": "iWasPoisoned grocery page + recent publish date",
                "method": "host-heuristic",
            }
        if not should_ingest_as_internet_evidence(verdict, has_official_recall=False):
            rejected += 1
            continue

        published = item.get("published_date") or item.get("published")
        observed = parse_observed_at(text=f"{title}\n{text}", url=url, published=published)
        if not observed:
            rejected += 1
            continue

        from .pipeline.evidence_schema import split_grocery_identity

        raw_name = title or text.split("\n")[0][:120]
        brand_guess, name_guess = split_grocery_identity(raw_name)
        # Prefer a quote body without the news-headline first line.
        raw_excerpt = _strip_headline_excerpt(item.get("snippet") or text)[:500]
        evidence, reason = validate_community_evidence(
            {
                "source_url": url,
                "excerpt": raw_excerpt if len(raw_excerpt) >= 24 else (item.get("snippet") or text)[:500],
                "brand": brand_guess,
                "name": name_guess,
                "observed_at": observed,
                "triage_label": "first_person_complaint",
                "confidence": float(verdict.get("score") or 0.5),
                "confidence_method": verdict.get("method")
                if verdict.get("method") in {"heuristic", "gemini"}
                else "heuristic",
                "location_label": None,
            }
        )
        if not evidence:
            rejected += 1
            logger.debug("community seed reject %s: %s", url[:80], reason)
            continue

        # Shelf identity: general product name FIRST, then company brand.
        product_name = evidence.name
        product_brand = evidence.brand if evidence.brand not in {"", "Unknown"} else brand_guess
        if not product_name or len(product_name) < 3:
            rejected += 1
            continue

        geo = correlate_location(text, title)
        loc = geo.get("location_label") if geo.get("location_source") == "inferred" else None
        # Only keep location if the label literally appears in the page text.
        if loc and loc.lower() not in f"{title} {text}".lower():
            loc = None

        product = _find_or_create_community_product(
            db, name=product_name, brand=product_brand or "Unknown"
        )

        url_key = url.split("#")[0].rstrip("/")[:240]
        exists = (
            db.query(Report)
            .filter(Report.product_id == product.id, Report.source_id == url_key)
            .first()
        )
        if exists:
            continue

        report = Report(
            product_id=product.id,
            source=source_label_for_url(url),
            source_id=url_key,
            source_url=str(evidence.source_url)[:700],
            title=title[:200] if title else None,
            text=text[:4000],
            excerpt=evidence.excerpt[:220],
            created_at=datetime.utcnow(),
            incident_date=evidence.observed_at,
            is_user_generated=False,
            location_label=loc,
            location_precision="city" if loc else "none",
            location_source="inferred" if loc else "none",
            latitude=None,
            longitude=None,
            extra_json=f'{{"confidence":{evidence.confidence},"method":"{evidence.confidence_method}"}}',
        )
        db.add(report)
        db.flush()
        attach_and_dedupe(db, report)
        ingested += 1

    # Connect dots: merge only near-identical product · brand stems (keep specifics).
    # Skip Exa enrichment when the HTTPS crawl already built a thick corpus —
    # otherwise we burn hundreds of Exa calls chasing second URLs.
    enriched = 0
    if ingested < 40:
        enriched = _enrich_community_products(db, skip_url=skip_url, days=days)
        ingested += enriched
    else:
        logger.info("Skipping Exa enrichment — crawl already ingested %s reports", ingested)
    merged = _merge_near_duplicate_community(db)
    merged += _cluster_specific_patterns(db)
    _refresh_pattern_summaries(db)

    db.add(
        DiscoveryRun(
            product_id=None,
            query="iwp-crawl+exa-grocery",
            provider=f"cseed:{provider or 'crawl'}"[:40],
            result_count=len(hits) + len(crawl.get("incidents") or []),
            notes=(
                f"ingested={ingested} rejected={rejected} "
                f"candidates={len(candidates)} enriched={enriched} merged={merged} "
                f"crawl_pages={crawl.get('pages')} crawl_listed={crawl.get('listed')} "
                f"crawl_kept={len(crawl.get('incidents') or [])} capped={crawl.get('capped')}"
            )[:1000],
        )
    )
    return {
        "ingested": ingested,
        "rejected": rejected,
        "hits": len(hits),
        "pages": len(pages),
        "candidates": len(candidates),
        "enriched": enriched,
        "merged": merged,
        "provider": provider or "crawl",
        "crawl": {
            "pages": crawl.get("pages"),
            "listed": crawl.get("listed"),
            "kept": len(crawl.get("incidents") or []),
            "capped": crawl.get("capped"),
            "error": crawl.get("error"),
        },
    }


def _norm_key(name: str, brand: str) -> str:
    titled = glance_title(brand=brand, name=name)
    if titled:
        name, brand = titled["name"], titled["brand"] or brand
    blob = re.sub(r"[^a-z0-9]+", " ", f"{name} {brand}".lower()).strip()
    return re.sub(r"\s+", " ", blob)


def _product_stem(name: str) -> str:
    """Specific product identity tokens — used to connect the same item across cities."""
    stop = {
        "the", "and", "for", "with", "from", "foods", "food", "item", "what",
        "grocery", "supermarket", "prepared", "store", "organic", "fresh",
        "unsweetened", "dried", "dry", "frozen", "raw",
    }
    tokens = [
        t for t in re.findall(r"[a-z0-9]+", (name or "").lower())
        if len(t) > 2 and t not in stop
    ]
    return " ".join(tokens)


def _stems_match(a: str, b: str) -> bool:
    """True when two product names are the same specific item (not just same food family)."""
    sa, sb = _product_stem(a), _product_stem(b)
    if not sa or not sb:
        return False
    if sa == sb:
        return True
    ta, tb = set(sa.split()), set(sb.split())
    if not ta or not tb:
        return False
    # Require high overlap — "chicken bake" ≠ "chicken wings".
    inter = len(ta & tb)
    return inter == len(ta) or inter == len(tb) or (inter / max(len(ta), len(tb)) >= 0.8 and inter >= 2)


def _find_or_create_community_product(db: Session, *, name: str, brand: str) -> Product:
    """Reuse an existing community product with the same specific shelf identity."""
    titled = glance_title(brand=brand, name=name)
    if titled:
        name = titled["name"]
        brand = titled["brand"] or brand or "Unknown"
    # Reject ultra-generic bucket leftovers from older seeds.
    if re.match(
        r"^(grocery foods?|prepared foods?|produce|snacks?|dairy|meat.*poultry)$",
        name or "",
        re.I,
    ):
        name = name  # still createable only if glance already rejected; keep as-is for cleanup later

    key = _norm_key(name, brand)
    slug_base = re.sub(r"[^a-z0-9]+", "-", f"{name}-{brand}".lower()).strip("-")[:80]
    slug = f"web-{slug_base or 'community-food'}"[:160]
    product = db.query(Product).filter(Product.slug == slug).first()
    if product:
        product.name = name[:180]
        product.brand = (brand or "Unknown")[:120]
        return product
    brand_l = (brand or "").lower().strip()
    for cand in (
        db.query(Product)
        .filter(Product.category == "Food", Product.slug.like("web-%"))
        .order_by(Product.id.desc())
        .limit(120)
        .all()
    ):
        if _norm_key(cand.name or "", cand.brand or "") == key:
            cand.name = name[:180]
            cand.brand = (brand or cand.brand or "Unknown")[:120]
            return cand
        # Same brand + same specific product stem (across different cities/URLs).
        if brand_l and (cand.brand or "").lower().strip() == brand_l and _stems_match(cand.name or "", name):
            return cand
    product = Product(
        slug=slug,
        brand=(brand or "Unknown")[:120],
        name=name[:180],
        category="Food",
        summary="Open-web pattern: linked grocery illness reports for this product.",
    )
    db.add(product)
    db.flush()
    return product


def _merge_near_duplicate_community(db: Session) -> int:
    """Move reports onto a canonical product when brand+name keys collide."""
    products = (
        db.query(Product)
        .filter(Product.category == "Food", Product.slug.like("web-%"))
        .order_by(Product.id.asc())
        .all()
    )
    by_key: dict[str, Product] = {}
    moved = 0
    for product in products:
        key = _norm_key(product.name or "", product.brand or "")
        if not key:
            continue
        if key not in by_key:
            by_key[key] = product
            continue
        keep = by_key[key]
        if keep.id == product.id:
            continue
        reports = db.query(Report).filter(Report.product_id == product.id).all()
        for report in reports:
            report.product_id = keep.id
            moved += 1
        db.flush()
        _hard_delete_product(db, product)
    if moved:
        db.flush()
    return moved


def _cluster_specific_patterns(db: Session) -> int:
    """
    Connect dots: merge reports that name the same specific product · brand
    (e.g. Chicken Bake · Costco in Eugene + Glendale). Never collapse into
    generic buckets like 'Prepared foods' or 'Grocery foods'.
    """
    products = (
        db.query(Product)
        .filter(Product.category == "Food", Product.slug.like("web-%"))
        .order_by(Product.id.asc())
        .all()
    )
    # Drop legacy ultra-generic shells first.
    generic = re.compile(
        r"^(grocery foods?|prepared foods?|produce|snacks?|dairy|meat\s*&\s*poultry|grocery item)$",
        re.I,
    )
    for product in list(products):
        if generic.match((product.name or "").strip()):
            # Re-home reports onto specific products parsed from each report title.
            for report in db.query(Report).filter(Report.product_id == product.id).all():
                from .pipeline.evidence_schema import split_grocery_identity

                brand_g, name_g = split_grocery_identity(
                    report.title or report.excerpt or product.name
                )
                if not name_g or generic.match(name_g.strip()):
                    continue
                target = _find_or_create_community_product(
                    db, name=name_g, brand=brand_g or product.brand or "Unknown"
                )
                if target.id == product.id:
                    continue
                url_key = (report.source_id or report.source_url or "")[:240]
                exists = (
                    db.query(Report)
                    .filter(Report.product_id == target.id, Report.source_id == url_key)
                    .first()
                    if url_key
                    else None
                )
                if exists:
                    _hard_delete_report(db, report)
                else:
                    report.product_id = target.id
            db.flush()
            left = db.query(Report).filter(Report.product_id == product.id).count()
            if left == 0:
                _hard_delete_product(db, product)
    db.flush()

    products = (
        db.query(Product)
        .filter(Product.category == "Food", Product.slug.like("web-%"))
        .order_by(Product.id.asc())
        .all()
    )
    groups: dict[tuple[str, str], list[Product]] = {}
    for product in products:
        brand = (product.brand or "").lower().strip()
        stem = _product_stem(product.name or "")
        if not brand or brand == "unknown" or not stem:
            continue
        if generic.match((product.name or "").strip()):
            continue
        groups.setdefault((brand, stem), []).append(product)

    moved = 0
    for (_brand, _stem), members in groups.items():
        if len(members) < 2:
            continue
        # Prefer the most specific (longest) shelf name with the most URLs.
        members.sort(
            key=lambda p: (
                -db.query(Report).filter(Report.product_id == p.id, Report.source_url.isnot(None)).count(),
                -len(p.name or ""),
                p.id,
            )
        )
        keep = members[0]
        for other in members[1:]:
            for report in db.query(Report).filter(Report.product_id == other.id).all():
                url_key = (report.source_id or report.source_url or "")[:240]
                exists = (
                    db.query(Report)
                    .filter(Report.product_id == keep.id, Report.source_id == url_key)
                    .first()
                    if url_key
                    else None
                )
                if exists:
                    _hard_delete_report(db, report)
                else:
                    report.product_id = keep.id
                    moved += 1
            db.flush()
            _hard_delete_product(db, other)
    if moved:
        db.flush()
    return moved


def _refresh_pattern_summaries(db: Session) -> None:
    """Write glanceable pattern blurbs: N linked reports · M places."""
    for product in (
        db.query(Product)
        .filter(Product.category == "Food", Product.slug.like("web-%"))
        .all()
    ):
        reports = (
            db.query(Report)
            .filter(Report.product_id == product.id, Report.source_url.isnot(None))
            .all()
        )
        if not reports:
            continue
        places = {
            (r.location_label or "").strip()
            for r in reports
            if (r.location_label or "").strip()
        }
        n = len({(r.source_url or "").split("#")[0].rstrip("/") for r in reports if r.source_url})
        report_word = "report" if n == 1 else "reports"
        if places:
            place_word = "place" if len(places) == 1 else "places"
            product.summary = (
                f"Open-web pattern: {n} linked {report_word}"
                f" across {len(places)} {place_word}."
            )
        else:
            product.summary = f"Open-web pattern: {n} linked grocery illness {report_word}."


def _enrich_community_products(db: Session, *, skip_url, days: int) -> int:
    """Find additional linked sources so no community card rests on a single URL."""
    from .agents.triage_agent import should_ingest_as_internet_evidence, triage_complaint
    from .agents.geo_agent import correlate_location
    from .data_sources.web_search import search_web
    from .pipeline.evidence_schema import (
        is_allowed_iwaspoisoned_url,
        parse_observed_at,
        source_label_for_url,
        split_grocery_identity,
        validate_community_evidence,
    )
    from .pipeline.cluster import attach_and_dedupe
    from .data_sources.page_fetch import domain_of

    settings = get_settings()
    # Cap hard — this path is optional multi-URL enrichment, not the primary corpus.
    min_urls = max(2, settings.community_min_url_reports)
    added = 0
    web_products = (
        db.query(Product)
        .filter(Product.category == "Food", Product.slug.like("web-%"))
        .order_by(Product.id.desc())
        .limit(8)
        .all()
    )
    for product in web_products:
        urls = {
            (r.source_url or "").split("#")[0].rstrip("/")
            for r in db.query(Report).filter(Report.product_id == product.id).all()
            if r.source_url
        }
        if len(urls) >= min_urls:
            continue
        label = f"{product.name} {product.brand}".strip()
        year = datetime.utcnow().year
        follow = [
            f'site:iwaspoisoned.com/incident "{product.name}" {product.brand} {year}',
            f'site:iwaspoisoned.com/incident {product.brand} {_product_stem(product.name)} (illness OR sick) {year}',
        ]
        hits = search_web(follow, limit_per_query=4) or []
        name_l = (product.name or "").lower()
        brand_l = (product.brand or "").lower()
        for hit in hits:
            url = (hit.url or "").split("#")[0].rstrip("/")
            if not url or url in urls or skip_url(url):
                continue
            blob = f"{hit.title or ''}\n{hit.snippet or ''}".lower()
            # Require the primary food token (not filler words) to appear in the hit.
            stop = {"the", "and", "for", "with", "from", "foods", "food", "item", "what"}
            name_tokens = [
                t
                for t in re.findall(r"[a-z0-9]+", name_l)
                if len(t) > 2 and t not in stop
            ]
            if not name_tokens:
                continue
            if not any(t in blob or t in url.lower() for t in name_tokens):
                continue
            if brand_l and brand_l not in {"unknown", ""} and brand_l not in blob and brand_l not in url.lower():
                continue
            if "iwaspoisoned.com" in url.lower() and not is_allowed_iwaspoisoned_url(
                url, title=hit.title or "", snippet=hit.snippet or ""
            ):
                continue
            text = f"{hit.title}\n{hit.snippet}"
            observed = parse_observed_at(
                text=text, url=url, published=getattr(hit, "published_date", None)
            )
            if not observed:
                continue
            verdict = triage_complaint(
                text=text,
                title=hit.title,
                product_hint=label,
                url=url,
                has_official_recall=False,
                recency_days=days,
            )
            if "iwaspoisoned.com" in url.lower() and not verdict.get("stale"):
                verdict = {
                    **verdict,
                    "label": "first_person_complaint",
                    "score": max(float(verdict.get("score") or 0), 0.55),
                }
            if not should_ingest_as_internet_evidence(verdict, has_official_recall=False):
                continue
            brand_g, name_g = split_grocery_identity(hit.title or product.name)
            # Prefer the product we're enriching; don't rename mid-enrich.
            evidence, _reason = validate_community_evidence(
                {
                    "source_url": url,
                    "excerpt": _strip_headline_excerpt(hit.snippet or text)[:500],
                    "brand": product.brand or brand_g,
                    "name": product.name or name_g,
                    "observed_at": observed,
                    "confidence": float(verdict.get("score") or 0.5),
                }
            )
            if not evidence:
                continue
            geo = correlate_location(text, hit.title)
            loc = geo.get("location_label") if geo.get("location_source") == "inferred" else None
            if loc and loc.lower() not in text.lower():
                loc = None
            url_key = url[:240]
            if db.query(Report).filter(Report.product_id == product.id, Report.source_id == url_key).first():
                continue
            report = Report(
                product_id=product.id,
                source=source_label_for_url(url),
                source_id=url_key,
                source_url=str(evidence.source_url)[:700],
                title=(hit.title or "")[:200] or None,
                text=text[:4000],
                excerpt=evidence.excerpt[:220],
                created_at=datetime.utcnow(),
                incident_date=evidence.observed_at,
                is_user_generated=False,
                location_label=loc,
                location_precision="city" if loc else "none",
                location_source="inferred" if loc else "none",
                extra_json=f'{{"confidence":{evidence.confidence},"method":"enrich"}}',
            )
            db.add(report)
            db.flush()
            attach_and_dedupe(db, report)
            urls.add(url)
            added += 1
            if len(urls) >= min_urls:
                break
    return added


def _overlay_fsis_recalls(db: Session, limit: int = 25) -> None:
    """Attach active USDA-FSIS recalls as grocery-style product items."""
    settings = get_settings()
    recalls = fetch_fsis_recalls(
        limit=max(limit, 80),
        max_age_days=settings.official_recall_max_age_days,
    )
    if not recalls:
        logger.warning("FSIS overlay: no active recalls fetched")
        return
    watch = {p.slug: p for p in db.query(Product).filter(Product.category == "Food").all()}
    fsis_extra = 0
    max_extra = max(limit, 60)
    for item in recalls:
        # Always keep item titles short / generic.
        polished = simplify_food_item(
            brand=item.get("brand"),
            name=item.get("name"),
            fallback="Meat / poultry",
        )
        item["brand"] = polished["brand"]
        item["name"] = polished["name"]

        matched = _match_watch_product(watch, item)
        if matched:
            _attach_recall(db, matched, item)
            continue
        existing = db.query(Product).filter(Product.slug == item["slug"]).first()
        if existing:
            existing.brand = item["brand"][:120]
            existing.name = item["name"][:180]
            if item.get("summary"):
                existing.summary = item["summary"][:500]
            _attach_recall(db, existing, item)
            continue
        if fsis_extra >= max_extra:
            continue
        product = Product(
            slug=item["slug"][:160],
            brand=item["brand"],
            name=item["name"],
            category="Food",
            summary=(
                item.get("summary")
                or f"Active USDA-FSIS recall: {item.get('hazard')}"
            )[:500],
        )
        db.add(product)
        db.flush()
        _attach_recall(db, product, item)
        watch[product.slug] = product
        fsis_extra += 1
    polish_catalog_titles(db)
    logger.info("FSIS overlay attached (extra SKUs=%s, pool=%s)", fsis_extra, len(recalls))


def _overlay_outbreaks(db: Session, limit: int = 20) -> None:
    """Upsert FDA outbreak investigation cards as food items — no fake Recall rows."""
    rows = fetch_active_outbreaks(limit=limit)
    for item in rows:
        slug = item["slug"][:160]
        polished = simplify_food_item(
            brand=item.get("brand"),
            name=item.get("name"),
            fallback="Food item",
        )
        brand = polished["brand"] if polished["brand"] not in {"Unknown"} else "FDA watch"
        name = polished["name"]
        product = db.query(Product).filter(Product.slug == slug).first()
        if not product:
            product = Product(
                slug=slug,
                brand=brand[:120],
                name=name[:180],
                category="Food",
                summary=item["summary"][:500],
            )
            db.add(product)
            db.flush()
        else:
            product.summary = item["summary"][:500]
            product.name = name[:180]
            product.brand = brand[:120]

        meta = (
            f"ref:{item['ref_id']}|pathogen:{item['pathogen']}|"
            f"cases:{item.get('case_count') or ''}|product:{item.get('product_status') or ''}|"
            f"active:true"
        )
        exists = (
            db.query(Report)
            .filter(Report.source == "fda_outbreak", Report.source_id == item["ref_id"])
            .first()
        )
        if exists:
            exists.text = meta
            exists.excerpt = item["summary"][:220]
            exists.source_url = item["source_url"]
            exists.title = f"FDA outbreak #{item['ref_id']}: {item['pathogen']}"
            continue
        report = Report(
            product_id=product.id,
            source="fda_outbreak",
            source_id=item["ref_id"],
            source_url=item["source_url"],
            title=f"FDA outbreak #{item['ref_id']}: {item['pathogen']}",
            text=meta,
            excerpt=item["summary"][:220],
            created_at=item.get("date_posted") or datetime.utcnow(),
            is_user_generated=False,
            display_name="FDA Outbreak Table",
            location_label=None,
            location_precision="unknown",
            location_source="system",
        )
        db.add(report)
    polish_catalog_titles(db)
    logger.info("Outbreak overlay upserted %s active investigations", len(rows))


def polish_catalog_titles(db: Session) -> int:
    """Rewrite long notice-style titles already in SQLite into short item names."""
    changed = 0
    products = (
        db.query(Product)
        .filter(
            Product.category == "Food",
            Product.slug.like("fsis-%")
            | Product.slug.like("outbreak-%")
            | Product.slug.like("caers-%")
            | Product.slug.like("search-%"),
        )
        .all()
    )
    for product in products:
        titled = glance_title(brand=product.brand, name=product.name)
        if not titled:
            continue
        brand, name = titled["brand"], titled["name"]
        if product.slug.startswith("outbreak-") and brand in {"Unknown", ""}:
            brand = "FDA watch"
        if (product.brand or "") != brand or (product.name or "") != name:
            product.brand = brand[:120]
            product.name = name[:180]
            changed += 1
    if changed:
        logger.info("Polished %s catalog item titles", changed)
    return changed


def scrub_catalog_quality(db: Session) -> dict:
    """
    One-shot quality pass:
    - purge invented community / ancient evidence
    - purge recalls older than official_recall_max_age_days
    - delete junk / legalese products (Unidentified food, ineligible import, etc.)
    - rewrite surviving titles to glanceable form
    """
    from .models import Embedding

    settings = get_settings()
    fake = purge_fake_community_data(db)
    purged_recalls = purge_non_ongoing_recalls(db)

    doomed: list[Product] = []
    for product in db.query(Product).filter(Product.category == "Food").all():
        slug = product.slug or ""
        source_brand = product.brand
        source_name = product.name

        # Watchlist shells without URL evidence should be deleted, not protected.
        if slug in {item["slug"] for item in FOOD_WATCHLIST}:
            url_n = (
                db.query(Report)
                .filter(Report.product_id == product.id, Report.source_url.isnot(None))
                .count()
            )
            has_official = db.query(Recall).filter(Recall.product_id == product.id).count() > 0
            if not url_n and not has_official:
                doomed.append(product)
                continue
            titled = glance_title(brand=source_brand, name=source_name)
            if titled:
                product.brand = titled["brand"][:120]
                product.name = titled["name"][:180]
            continue
        if not is_sensible_product(source_brand, source_name, slug=slug):
            doomed.append(product)
            continue
        titled = glance_title(brand=source_brand, name=source_name)
        if not titled:
            doomed.append(product)
            continue
        product.brand = titled["brand"][:120]
        product.name = titled["name"][:180]

    deleted = 0
    for product in doomed:
        _hard_delete_product(db, product)
        deleted += 1

    polish_catalog_titles(db)

    # Collapse exact brand+name duplicates (keep newest recall / highest id).
    deduped = _dedupe_shelf_products(db)

    logger.info(
        "Catalog scrub: fake=%s purged_recalls=%s deleted_products=%s deduped=%s",
        fake,
        purged_recalls,
        deleted,
        deduped,
    )
    return {
        "purged_recalls": purged_recalls,
        "deleted_products": deleted + deduped,
        "fake_purged": fake,
    }


def _hard_delete_product(db: Session, product: Product) -> None:
    """Delete a product and all dependent rows (SQLite FK-safe)."""
    from .models import Embedding, TimelineEvent, DiscoveryRun

    reports = db.query(Report).filter(Report.product_id == product.id).all()
    report_ids = [r.id for r in reports]
    if report_ids:
        db.query(Report).filter(Report.duplicate_of_id.in_(report_ids)).update(
            {Report.duplicate_of_id: None}, synchronize_session=False
        )
        db.query(Post).filter(Post.report_id.in_(report_ids)).update(
            {Post.report_id: None}, synchronize_session=False
        )
        try:
            db.query(Embedding).filter(Embedding.report_id.in_(report_ids)).delete(
                synchronize_session=False
            )
        except Exception:
            pass
        db.query(ReportIssue).filter(ReportIssue.report_id.in_(report_ids)).delete(
            synchronize_session=False
        )
        for report in reports:
            db.delete(report)

    posts = db.query(Post).filter(Post.product_id == product.id).all()
    post_ids = [p.id for p in posts]
    if post_ids:
        db.query(Comment).filter(Comment.post_id.in_(post_ids)).delete(synchronize_session=False)
        db.query(Like).filter(Like.post_id.in_(post_ids)).delete(synchronize_session=False)
        db.query(Post).filter(Post.id.in_(post_ids)).delete(synchronize_session=False)

    db.query(Recall).filter(Recall.product_id == product.id).delete(synchronize_session=False)
    try:
        db.query(TimelineEvent).filter(TimelineEvent.product_id == product.id).delete(
            synchronize_session=False
        )
        db.query(DiscoveryRun).filter(DiscoveryRun.product_id == product.id).delete(
            synchronize_session=False
        )
    except Exception:
        pass
    db.delete(product)


def _dedupe_shelf_products(db: Session) -> int:
    """Keep one product per glance brand+name for official/outbreak/caers rows."""
    from collections import defaultdict

    groups: dict[str, list[Product]] = defaultdict(list)
    for product in db.query(Product).filter(Product.category == "Food").all():
        slug = product.slug or ""
        if not (
            slug.startswith("fsis-")
            or slug.startswith("outbreak-")
            or slug.startswith("caers-")
            or slug.startswith("search-")
        ):
            continue
        brand = (product.brand or "").strip().lower()
        name = (product.name or "").strip().lower()
        name = re.sub(r"^(raw|frozen)\s+", "", name)
        # Collapse near-identical brands (corte argentino usa vs corte argentino)
        brand = re.sub(r"\b(usa|llc|inc|co)\b", "", brand)
        brand = re.sub(r"\s+", " ", brand).strip()
        key = f"{brand}|{name}"
        groups[key].append(product)

    removed = 0
    for items in groups.values():
        if len(items) < 2:
            continue

        def score(p: Product) -> tuple:
            has_recall = db.query(Recall).filter(Recall.product_id == p.id).count() > 0
            return (1 if has_recall else 0, p.id)

        keep = max(items, key=score)
        for product in items:
            if product.id == keep.id:
                continue
            _hard_delete_product(db, product)
            removed += 1
    return removed


def _overlay_caers(db: Session) -> None:
    """Ingest CAERS events, upsert products, score spikes, Gemini-summarize spikes only."""
    settings = get_settings()
    events = fetch_caers_events(
        lookback_days=settings.caers_lookback_days,
        fetch_limit=settings.caers_fetch_limit,
    )
    if not events:
        logger.warning("CAERS overlay: no events fetched")
        return

    # Aggregate by product key; keep top entities by volume for the demo shelf.
    buckets: dict[str, list[dict]] = {}
    for event in events:
        key = caers_product_key(event["brand"], event["name"])
        buckets.setdefault(key, []).append(event)

    ranked = sorted(buckets.items(), key=lambda kv: len(kv[1]), reverse=True)
    # Cap entity count so SQLite stays snappy — but keep a large grocery shelf.
    top = ranked[:200]
    spiked = 0
    for key, items in top:
        sample = items[0]
        slug = f"caers-{key}"[:160]
        polished = glance_title(
            brand=sample["brand"],
            name=sample["name"],
        )
        if not polished:
            continue
        # Skip FOIA / nonsense labels that slipped through.
        if re.search(r"\bexemption\s*4\b", f"{polished['brand']} {polished['name']}", re.I):
            continue
        product = db.query(Product).filter(Product.slug == slug).first()
        if not product:
            product = Product(
                slug=slug,
                brand=polished["brand"][:120],
                name=polished["name"][:180],
                category="Food",
                summary="FDA CAERS adverse event reports on file — not an official recall.",
            )
            db.add(product)
            try:
                db.flush()
            except Exception:
                db.rollback()
                product = db.query(Product).filter(Product.slug == slug).first()
                if not product:
                    continue
        if product:
            product.brand = polished["brand"][:120]
            product.name = polished["name"][:180]

        for event in items:
            source_id = f"{event['report_number']}:{key}"
            exists = (
                db.query(Report)
                .filter(Report.source == "caers", Report.source_id == source_id)
                .first()
            )
            if exists:
                continue
            reactions = ", ".join(event.get("reactions") or []) or "adverse event"
            text = (
                f"CAERS report {event['report_number']} for {event['label']}. "
                f"Reported reactions: {reactions}."
            )
            report = Report(
                product_id=product.id,
                source="caers",
                source_id=source_id,
                source_url=event["source_url"],
                title=f"CAERS: {event['label'][:120]}",
                text=text[:4000],
                excerpt=text[:220],
                created_at=event["date"],
                is_user_generated=False,
                display_name="FDA CAERS",
                location_label=None,
                location_precision="unknown",
                location_source="system",
            )
            db.add(report)
        db.flush()

        spike = score_caers_spike(db, product.id)
        if spike.get("is_spike"):
            spiked += 1
            samples = (
                db.query(Report)
                .filter(Report.product_id == product.id, Report.source == "caers")
                .order_by(Report.created_at.desc())
                .limit(8)
                .all()
            )
            label = f"{product.brand} {product.name}".strip()
            product.summary = summarize_caers_spike(label, [r.text for r in samples])[:500]

    polish_catalog_titles(db)
    logger.info(
        "CAERS overlay: %s events → %s entities, %s spikes",
        len(events),
        len(top),
        spiked,
    )


def purge_non_ongoing_recalls(db: Session) -> int:
    """Remove terminated / completed / stale / unknown historical recalls — only recent Ongoing stays."""
    settings = get_settings()
    max_age = settings.official_recall_max_age_days
    cutoff = datetime.utcnow() - timedelta(days=max(14, max_age))
    doomed: list[Recall] = []
    for recall in db.query(Recall).filter(Recall.official.is_(True)).all():
        status = "unknown"
        reason = recall.reason or ""
        # Repair stringified-list reasons from older FSIS parses.
        if reason.startswith("['") or reason.startswith('["'):
            cleaned = reason.strip("[]'\" ")
            recall.reason = f"[Ongoing] {cleaned}"[:2000]
            reason = recall.reason
        if reason.startswith("[") and "]" in reason[:40]:
            status = reason[1 : reason.index("]")].strip().lower()
        else:
            # FSIS/FDA rows missing the Ongoing stamp — keep USDA-FSIS and re-stamp.
            if (recall.agency or "").upper().find("FSIS") >= 0:
                recall.reason = f"[Ongoing] {reason}"[:2000]
                status = "ongoing"
            else:
                status = "unknown"
        # Age out resolved / no-longer-urgent notices from the home shelf.
        if recall.recall_date and recall.recall_date < cutoff:
            doomed.append(recall)
            continue
        if status == "ongoing":
            continue
        doomed.append(recall)
    for recall in doomed:
        db.delete(recall)
    if doomed:
        logger.info("Purged %s non-Ongoing or stale official recalls", len(doomed))
    return len(doomed)


def _attach_recall(db: Session, product: Product, item: dict) -> None:
    status = (item.get("status") or "Unknown").strip()
    if status.lower() != "ongoing":
        return
    exists = (
        db.query(Recall)
        .filter(Recall.product_id == product.id, Recall.source_url == item["source_url"])
        .first()
    )
    reason = str(item.get("reason") or "").strip()
    # Persist openFDA/FSIS status in reason prefix so UI can distinguish Ongoing vs past
    # without a schema migration.
    if reason.startswith("[") and "]" in reason[:40]:
        # Re-stamp known Ongoing attachments so agency overlays stay visible.
        inner = reason[1 : reason.index("]")].strip().lower()
        if inner != "ongoing":
            reason = reason[reason.index("]") + 1 :].strip()
            reason = f"[Ongoing] {reason}"
    else:
        reason = f"[Ongoing] {reason}" if reason else "[Ongoing] Official recall"
    if exists:
        exists.agency = item["agency"]
        exists.reason = reason[:2000]
        exists.hazard = item["hazard"]
        exists.nationwide = item.get("nationwide", True)
        return
    db.add(
        Recall(
            product_id=product.id,
            agency=item["agency"],
            recall_date=item["recall_date"],
            reason=reason[:2000],
            hazard=item["hazard"],
            source_url=item["source_url"],
            official=True,
            nationwide=item.get("nationwide", True),
        )
    )
    if not product.summary or "watching" in (product.summary or "").lower():
        product.summary = (
            f"People are posting illness reports about this product. "
            f"An Ongoing {item['agency']} notice also exists ({item['hazard']})."
        )[:500]


def ensure_recall_from_discovery(db: Session, product: Product, coverage_pages: list[dict]) -> bool:
    """
    When triage finds recall_coverage pages, confirm against openFDA and attach if real.
    Never invent a recall from blog text alone.
    """
    if not coverage_pages:
        return False
    if (
        db.query(Recall)
        .filter(Recall.product_id == product.id, Recall.official.is_(True))
        .count()
    ):
        return False

    blob = " ".join(
        f"{(p.get('title') or '')} {(p.get('snippet') or '')[:200]}" for p in coverage_pages[:5]
    ).lower()
    # Brand/product hints from coverage text for a targeted openFDA search.
    needles = []
    for token in (
        "premier",
        "lyons",
        "magnus",
        "protein",
        "cantaloupe",
        "romaine",
        "lettuce",
        "alfalfa",
        "queso",
        "turkey",
        "deli",
    ):
        if token in blob or token in f"{product.brand} {product.name}".lower():
            needles.append(token)
    if not needles:
        needles = [w for w in re.findall(r"[a-z]{4,}", f"{product.brand} {product.name}".lower())[:4]]

    import httpx
    from .data_sources.fda import FDA_FOOD_ENFORCEMENT, _normalize

    search = " AND ".join(needles[:3])
    # Only confirm Ongoing openFDA rows — never invent or attach terminated history.
    queries = [f'(status:"Ongoing") AND ({search})']
    try:
        with httpx.Client(timeout=30, follow_redirects=True, trust_env=False) as client:
            for q in queries:
                response = client.get(
                    FDA_FOOD_ENFORCEMENT,
                    params={"search": q, "sort": "report_date:desc", "limit": 20},
                )
                if response.status_code >= 400:
                    continue
                watch = {product.slug: product}
                for row in response.json().get("results") or []:
                    item = _normalize(row)
                    if not item or (item.get("status") or "").lower() != "ongoing":
                        continue
                    matched = _match_watch_product(watch, item)
                    if matched or _loose_product_match(product, item):
                        _attach_recall(db, product, item)
                        logger.info("Attached Ongoing openFDA recall to %s from discovery", product.slug)
                        return True
    except Exception:
        logger.exception("ensure_recall_from_discovery failed for %s", product.slug)
    return False


def _loose_product_match(product: Product, item: dict) -> bool:
    """Fallback when watch rules miss but names clearly overlap (e.g. protein + shake)."""
    prod = f"{product.brand} {product.name}".lower()
    blob = f"{item.get('name','')} {item.get('hazard','')} {item.get('reason','')}".lower()
    tokens = [t for t in re.findall(r"[a-z]{4,}", prod) if t not in {"watch", "food", "style", "ready", "drink"}]
    if len(tokens) < 1:
        return False
    hits = sum(1 for t in tokens if t in blob)
    return hits >= max(1, min(2, len(tokens) // 2))


def _ensure_pre_recall_reports(db: Session, product: Product, recall_date: datetime) -> None:
    """No-op: never invent pre-recall community notes."""
    del db, product, recall_date
    return


def _clear_catalog(db: Session) -> None:
    from .models import Embedding, TimelineEvent

    db.query(Like).delete()
    db.query(Comment).delete()
    db.query(Post).delete()
    db.query(Embedding).delete()
    db.query(ReportIssue).delete()
    db.query(Report).delete()
    db.query(DiscoveryRun).delete()
    db.query(TimelineEvent).delete()
    db.query(Recall).delete()
    db.query(Product).delete()
    db.commit()


def seed_fake_posts(db: Session, products: list[Product]) -> None:
    """Generic neighbor posts when no live scrape has run yet."""
    templates = [
        ("Watching this page for any real links people find online.", "Same — waiting for sources, not just vibes."),
        ("Still no shelf tag at my store. Looking for public threads with URLs.", "We tossed ours last night."),
        ("Glad early chatter is collected in one place.", "This is the whole point."),
        ("Official notice may catch up later. Looking for the internet trail first.", "Bookmarking this product page."),
    ]
    for index, product in enumerate(products):
        if db.query(Post).filter(Post.product_id == product.id).count() >= 2:
            continue
        body, reply = templates[index % len(templates)]
        post = Post(
            product_id=product.id,
            display_name=["Alex", "Sam", "Jordan", "Riley", "Casey"][index % 5],
            body=body,
            location_label=CITIES[index % len(CITIES)],
            created_at=datetime.utcnow() - timedelta(hours=index),
        )
        db.add(post)
        db.flush()
        db.add(Comment(post_id=post.id, display_name=["Maya", "Chris", "Taylor"][index % 3], body=reply))
        db.add(Like(post_id=post.id, display_name="Neighbor"))
    db.commit()


def seed_posts_from_ingest(db: Session, product: Product, findings: list[dict]) -> None:
    """
    After a successful live ingest, seed 1–2 site posts that reference real findings.
    Does not invent fake Reddit quotes — only points at scraped titles/hosts.
    """
    if not findings:
        return
    existing = (
        db.query(Post)
        .filter(Post.product_id == product.id, Post.body.contains("people are linking"))
        .count()
    )
    if existing:
        return

    first = findings[0]
    host = (first.get("host") or "the public web").replace("www.", "")
    title = (first.get("title") or "a public thread")[:80]
    bodies = [
        (
            f"Saw the same {product.name.lower()} thread people are linking — "
            f"“{title}” on {host}. Matches what neighbors here already said."
        ),
        (
            f"The internet notes on this page for {product.name} line up with what I heard locally. "
            f"Worth reading the original on {host}."
        ),
    ]
    for index, body in enumerate(bodies[: min(2, len(findings) + 1)]):
        post = Post(
            product_id=product.id,
            display_name=["Alex", "Sam", "Jordan", "Riley"][index % 4],
            body=body,
            location_label=CITIES[index % len(CITIES)],
            created_at=datetime.utcnow() - timedelta(minutes=15 * index),
        )
        db.add(post)
        db.flush()
        db.add(
            Comment(
                post_id=post.id,
                display_name=["Maya", "Chris"][index % 2],
                body="Thanks for pointing at the linked sources.",
            )
        )
    db.commit()


def home_scrape_already_done(db: Session) -> bool:
    return db.query(DiscoveryRun).filter(DiscoveryRun.query == HOME_SCRAPE_MARKER).count() > 0


def start_home_scrape_background(product_slugs: list[str]) -> None:
    settings = get_settings()
    if not settings.has_live_search() or not product_slugs:
        return

    def worker() -> None:
        from .services import run_discovery

        with SessionLocal() as db:
            if home_scrape_already_done(db):
                return
            logger.info("Starting internet-first food scrape for %s products", len(product_slugs))
            for slug in product_slugs:
                try:
                    result = run_discovery(
                        db,
                        slug,
                        max_pages=settings.home_scrape_pages,
                        max_queries=settings.home_scrape_queries,
                        force=True,
                    )
                    logger.info(
                        "Home scrape %s: ingested=%s provider=%s",
                        slug,
                        result.get("ingested"),
                        result.get("provider"),
                    )
                except Exception:
                    logger.exception("Home scrape failed for %s", slug)
            db.add(
                DiscoveryRun(
                    product_id=None,
                    query=HOME_SCRAPE_MARKER,
                    provider="bootstrap",
                    result_count=len(product_slugs),
                    notes="internet-first food scrape completed",
                )
            )
            db.commit()

    threading.Thread(target=worker, name="home-scrape-food", daemon=True).start()
