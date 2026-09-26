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
from .database import SessionLocal
from .models import Comment, DiscoveryRun, Issue, Like, Post, Product, Recall, Report, ReportIssue
from .pipeline.cluster import attach_and_dedupe
from .seed import ISSUES, seed

logger = logging.getLogger(__name__)

HOME_SCRAPE_MARKER = "__home_scrape_food__"
CITIES = ["Atlanta", "Chicago", "Austin", "Boston", "Seattle", "Marietta", "Decatur"]

# Demo watchlist: food items people talk about online before (or without) an FDA notice.
FOOD_WATCHLIST = [
    {
        "slug": "romaine-lettuce-cyclospora-watch",
        "brand": "Romaine / leafy greens",
        "name": "Romaine and garden salad mixes",
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
        "brand": "Whole / cut cantaloupe",
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
        "brand": "Prepackaged deli meats",
        "name": "Turkey and ham deli slices",
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
        "brand": "Soft cheeses",
        "name": "Soft / queso-style cheeses",
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
        "brand": "Protein powders / shakes",
        "name": "Protein powder and ready-to-drink shakes",
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
        "brand": "Meal-kit chicken",
        "name": "Meal-kit / prepared chicken dishes",
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
    """Build an internet-first food watchlist, then overlay matching FDA recalls."""
    settings = get_settings()
    ensure_issue_taxonomy(db)
    purged = purge_placeholder_reports(db)
    if purged:
        logger.info("Removed %s placeholder example.com reports", purged)

    if settings.seed_demo:
        from .seed import seed_if_empty

        seed_if_empty(db)
        return db.query(Product).all()

    watch_existing = (
        db.query(Product)
        .filter(Product.slug.in_([item["slug"] for item in FOOD_WATCHLIST]))
        .count()
    )
    if not watch_existing:
        if db.query(Product).count():
            logger.info("Rebuilding catalog around emerging food watchlist…")
            _clear_catalog(db)
        logger.info("Seeding food watchlist (internet-first)…")
        for item in FOOD_WATCHLIST:
            _seed_watch_product(db, item)
        db.commit()
    else:
        # Seed any newly added watchlist slugs without wiping the catalog.
        for item in FOOD_WATCHLIST:
            if db.query(Product).filter(Product.slug == item["slug"]).one_or_none():
                continue
            logger.info("Seeding new watch product %s", item["slug"])
            _seed_watch_product(db, item)
        db.commit()

    purge_agency_internet_reports(db)

    # Always refresh FDA overlay in the background so recall status stays accurate.
    start_fda_overlay_background()

    home = (
        db.query(Product)
        .filter(Product.category == "Food")
        .order_by(Product.id)
        .limit(settings.home_scrape_products)
        .all()
    )
    if settings.seed_fake_posts:
        seed_fake_posts(db, home)
    return home


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
        if r.source_url and any(bit in r.source_url.lower() for bit in agency_bits)
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
    product = Product(
        slug=item["slug"],
        brand=item["brand"],
        name=item["name"],
        category="Food",
        summary=item["summary"],
    )
    db.add(product)
    db.flush()

    issue = db.query(Issue).filter(Issue.slug == item["issue"]).one_or_none()
    now = datetime.utcnow()
    names = ["alex.r", "sam", "jordan.k", "riley", "casey", "maya", "devon", "harper"]
    # Site-only seed reports — internet evidence comes from live Exa/Brave ingest.
    for index, text in enumerate(item["templates"]):
        created = now - timedelta(days=(index % 5), hours=3 * index)
        report = Report(
            product_id=product.id,
            source="community",
            source_id=f"watch-{item['slug']}-{index}",
            source_url=None,
            title=None,
            text=text,
            excerpt=text[:220],
            created_at=created,
            is_user_generated=True,
            display_name=names[index % len(names)],
            location_label=CITIES[index % len(CITIES)],
            location_precision="city",
            location_source="inferred",
            latitude=None,
            longitude=None,
        )
        db.add(report)
        db.flush()
        if issue:
            db.add(ReportIssue(report_id=report.id, issue_id=issue.id, confidence=0.8))
        attach_and_dedupe(db, report)
    return product

def _overlay_fda_recalls(db: Session, limit: int = 25) -> None:
    """Attach only Ongoing FDA recalls onto watchlist products when product+hazard match."""
    purge_non_ongoing_recalls(db)
    recalls = fetch_recent_food_recalls(limit=max(limit, 40))
    pool = [item for item in recalls if (item.get("status") or "").lower() == "ongoing"]
    # Extra targeted Ongoing searches for watch products still unmatched.
    pool.extend(
        item
        for item in _targeted_watch_recalls()
        if (item.get("status") or "").lower() == "ongoing"
    )
    watch = {p.slug: p for p in db.query(Product).filter(Product.category == "Food").all()}
    matched_slugs: set[str] = set()

    for item in pool:
        if (item.get("status") or "").lower() != "ongoing":
            continue
        matched = _match_watch_product(watch, item)
        if matched:
            _attach_recall(db, matched, item)
            matched_slugs.add(matched.slug)
            continue

        # Don't flood the home shelf with every Taylor Farms SKU variant —
        # watchlist cards already carry the FDA RECALL overlay when matched.
        if matched_slugs:
            continue
        if db.query(Product).filter(Product.slug == item["slug"]).one_or_none():
            continue
        hazard = (item.get("hazard") or "").lower()
        if not any(n in hazard for n in ("cyclospora", "salmonella", "listeria", "e. coli", "contamination")):
            continue
        official_only = (
            db.query(Product)
            .filter(Product.category == "Food", ~Product.slug.in_(list(watch.keys())))
            .count()
        )
        if official_only >= 3:
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
    """Refresh FDA recall attachments without blocking API startup."""

    def worker() -> None:
        settings = get_settings()
        with SessionLocal() as db:
            try:
                _overlay_fda_recalls(db, limit=settings.fda_food_recall_limit)
                db.commit()
                logger.info("FDA overlay refresh complete")
            except Exception:
                logger.exception("Background FDA overlay failed")
                db.rollback()

    threading.Thread(target=worker, name="fda-overlay", daemon=True).start()


def purge_non_ongoing_recalls(db: Session) -> int:
    """Remove terminated / completed / unknown historical recalls — only Ongoing stays."""
    doomed: list[Recall] = []
    for recall in db.query(Recall).filter(Recall.official.is_(True)).all():
        status = "unknown"
        reason = recall.reason or ""
        if reason.startswith("[") and "]" in reason[:40]:
            status = reason[1 : reason.index("]")].strip().lower()
        else:
            status = "unknown"
        if status == "ongoing":
            continue
        doomed.append(recall)
    for recall in doomed:
        db.delete(recall)
    if doomed:
        logger.info("Purged %s non-Ongoing FDA recalls", len(doomed))
    return len(doomed)


def _attach_recall(db: Session, product: Product, item: dict) -> None:
    status = (item.get("status") or "Unknown").strip()
    if status.lower() != "ongoing":
        return
    exists = (
        db.query(Recall)
        .filter(Recall.product_id == product.id, Recall.source_url == item["source_url"])
        .one_or_none()
    )
    if exists:
        return
    reason = item["reason"]
    # Persist openFDA status in reason prefix so UI can distinguish Ongoing vs past
    # without a schema migration.
    if status and not reason.startswith("["):
        reason = f"[{status}] {reason}"
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
    """Guarantee at least a few site notes dated before the official recall."""
    pre = (
        db.query(Report)
        .filter(Report.product_id == product.id, Report.created_at < recall_date)
        .count()
    )
    if pre >= 3:
        return
    issue = db.query(Issue).filter(Issue.slug.in_(("cyclospora", "salmonella", "listeria", "food-contamination"))).first()
    for i in range(3 - pre):
        created = recall_date - timedelta(days=10 + i * 2)
        report = Report(
            product_id=product.id,
            source="community",
            source_id=f"pre-recall-{product.slug}-{i}",
            source_url=None,
            text=(
                "Posting this before any official recall page existed. "
                "Several independent people described the same illness pattern."
            ),
            excerpt="Several independent people described the same illness pattern before any official recall.",
            created_at=created,
            is_user_generated=True,
            display_name=["early.signal", "forum.user", "neighbor"][i % 3],
            location_label=CITIES[i % len(CITIES)],
            location_precision="city",
            location_source="inferred",
        )
        db.add(report)
        db.flush()
        if issue:
            db.add(ReportIssue(report_id=report.id, issue_id=issue.id, confidence=0.75))
        attach_and_dedupe(db, report)

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
