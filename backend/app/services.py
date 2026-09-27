from __future__ import annotations

import re
from datetime import datetime, timedelta

from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

import httpx

from .auth import AuthUser
from .config import get_settings
from .data_sources.page_fetch import domain_of
from .data_sources.web_search import available_provider
from .openai_http import _verify
from .seed import CITIES as KNOWN_CITIES
from .models import Comment, DiscoveryRun, Issue, Like, Post, Product, Recall, Report, ReportIssue, TimelineEvent
from .pipeline.cluster import attach_and_dedupe
from .pipeline.embeddings import similar_reports
from .pipeline.extract import extract_report
from .pipeline.food_families import related_food_keywords
from .pipeline.signals import compute_signal, feed_cards
from .security import sanitize_text, snap_coordinate
from .serialize import post_card, product_card, product_detail, report_card

NEWS_DOMAINS = {
    "cnn.com",
    "bbc.com",
    "nytimes.com",
    "washingtonpost.com",
    "reuters.com",
    "apnews.com",
    "nbcnews.com",
    "cbsnews.com",
    "abcnews.go.com",
    "theguardian.com",
    "npr.org",
    "usatoday.com",
    "bloomberg.com",
    "forbes.com",
    "consumerreports.org",
    "cnet.com",
    "wired.com",
    "techcrunch.com",
}


def get_product(db: Session, slug: str) -> Product | None:
    return db.query(Product).filter(Product.slug == slug).one_or_none()


def list_feed(db: Session, city: str | None = None) -> dict:
    cards = feed_cards(db, visitor_city=city)
    serialized = [product_card(item["product"], item["signal"], item["local"]) for item in cards]

    official = [c for c in serialized if (c.get("source_tier") or c["signal"].get("source_tier")) == "official"]
    caers_spikes = [
        c for c in serialized if (c.get("source_tier") or c["signal"].get("source_tier")) == "caers"
    ]
    unofficial = [
        c for c in serialized if (c.get("source_tier") or c["signal"].get("source_tier")) == "unofficial"
    ]

    def _official_recency(card: dict) -> float:
        recall = (card.get("signal") or {}).get("official_recall") or {}
        date = recall.get("recall_date") or ""
        # ISO date sorts lexicographically; missing dates sink.
        return date or "0000-00-00"

    # Newest / most urgent official items first (Star Meat-class recalls before old PHAs).
    official.sort(key=_official_recency, reverse=True)
    recalls = [c for c in official if c["signal"].get("official_recall")]
    outbreaks = [c for c in official if c["signal"].get("outbreak") and not c["signal"].get("official_recall")]
    interleaved_official: list = []
    for i in range(max(len(recalls), len(outbreaks))):
        if i < len(recalls):
            interleaved_official.append(recalls[i])
        if i < len(outbreaks):
            interleaved_official.append(outbreaks[i])
    official = interleaved_official

    # Home hero: community / conjecture first, then a thin recent-official slice.
    important = (unofficial[:8] + official[:6] + caers_spikes[:4])[:18]
    nearby = [card for card in important if card["local"]]
    trending = sorted(
        [card for card in (unofficial + official) if card["signal"].get("velocity_percent")],
        key=lambda card: card["signal"]["velocity_percent"] or 0,
        reverse=True,
    )[:10]
    recent = (
        db.query(Report)
        .options(joinedload(Report.issue_links).joinedload(ReportIssue.issue), joinedload(Report.product))
        .filter(Report.source.in_(("web", "reddit", "news", "community", "iwaspoisoned", "user")))
        .order_by(Report.created_at.desc())
        .limit(20)
        .all()
    )
    # Fall back if filters emptied the list.
    if not recent:
        recent = (
            db.query(Report)
            .options(joinedload(Report.issue_links).joinedload(ReportIssue.issue), joinedload(Report.product))
            .order_by(Report.created_at.desc())
            .limit(20)
            .all()
        )
    return {
        "important": important,
        "official": official[:20],
        "caers_spikes": caers_spikes[:24],
        "unofficial": unofficial[:30],
        "nearby": nearby,
        "trending": trending,
        "recent_reports": [
            {**report_card(report), "product_slug": report.product.slug, "product_name": report.product.name}
            for report in recent
        ],
        "visitor_city": city,
        "disclaimer": (
            "Home leads with community / iWasPoisoned / Reddit-style reports. "
            "Official FDA/FSIS items are recent Ongoing notices only — resolved or stale recalls are removed. "
            "CAERS is FDA-hosted complaint data, not a recall."
        ),
    }


def product_payload(db: Session, product: Product, issue_slug: str | None = None) -> dict:
    signal = compute_signal(db, product)
    reports = (
        db.query(Report)
        .options(joinedload(Report.issue_links).joinedload(ReportIssue.issue))
        .filter(Report.product_id == product.id)
        .order_by(Report.created_at.desc())
        .all()
    )
    if issue_slug:
        reports = [r for r in reports if any(link.issue.slug == issue_slug for link in r.issue_links)]
    posts = (
        db.query(Post)
        .options(joinedload(Post.comments), joinedload(Post.likes))
        .filter(Post.product_id == product.id)
        .order_by(Post.created_at.desc())
        .all()
    )
    payload = product_detail(product, signal, reports, posts)
    payload["timeline"] = [
        {
            "day_offset": event.day_offset,
            "label": event.label,
            "event_type": event.event_type,
            "report_count": event.report_count,
            "detail": event.detail,
        }
        for event in db.query(TimelineEvent)
        .filter(TimelineEvent.product_id == product.id)
        .order_by(TimelineEvent.day_offset)
        .all()
    ]
    payload["filtered_issue"] = issue_slug
    return payload


def search_catalog(db: Session, query: str, live: bool = True) -> dict:
    settings = get_settings()
    q = sanitize_text(query, 200)
    if not q:
        return {"query": q, "products": [], "reports": [], "semantic": [], "discovery": None}

    tokens = [t for t in re.split(r"[^a-z0-9]+", q.lower()) if len(t) >= 2]
    # Synonym expansion so "raw meat" hits pork/beef/goat FSIS items.
    expanded = set(tokens)
    if "meat" in expanded:
        expanded.update({"pork", "beef", "goat", "poultry", "turkey", "chicken", "sausage"})
    if "poison" in expanded or "poisoned" in expanded:
        expanded.update({"iwaspoisoned", "sick", "vomiting", "diarrhea"})
    # Family expansion: "haagen dazs" → ice cream / dairy / gelato, etc.
    related_kws = related_food_keywords(q)
    for kw in related_kws:
        for part in re.split(r"\s+", kw.lower()):
            if len(part) >= 3:
                expanded.add(part)
    token_list = list(expanded)[:20]

    like = f"%{q}%"
    clauses = [
        Product.name.ilike(like),
        Product.brand.ilike(like),
        Product.model.ilike(like),
        Product.category.ilike(like),
        Product.upc.ilike(like),
        Product.slug.ilike(like),
        Product.summary.ilike(like),
    ]
    for token in token_list:
        tok = f"%{token}%"
        clauses.extend(
            [
                Product.name.ilike(tok),
                Product.brand.ilike(tok),
                Product.slug.ilike(tok),
                Product.summary.ilike(tok),
            ]
        )
    # Multi-word family phrases as wholes ("ice cream", "frozen yogurt").
    for kw in related_kws:
        if " " in kw:
            phrase = f"%{kw}%"
            clauses.extend(
                [
                    Product.name.ilike(phrase),
                    Product.brand.ilike(phrase),
                    Product.summary.ilike(phrase),
                ]
            )

    products = db.query(Product).filter(or_(*clauses)).limit(60).all()

    def _blob(p: Product) -> str:
        return f"{p.brand} {p.name} {p.slug} {p.summary or ''}".lower()

    def _related_hits(p: Product) -> int:
        blob = _blob(p)
        score = 0
        for kw in related_kws:
            key = kw.lower()
            if " " in key:
                if key in blob:
                    score += 2
                continue
            # Single-token family cues — skip short/ambiguous ones.
            if key in {"cream", "pint", "milk", "dairy", "dessert", "spread"}:
                continue
            if len(key) >= 4 and re.search(rf"\b{re.escape(key)}\b", blob):
                score += 1
        return score

    def _rank_product(p: Product) -> tuple:
        blob = _blob(p)
        phrase = 0 if q.lower() in blob else 1
        hits = sum(1 for t in tokens if t in blob)
        related = _related_hits(p)
        return (phrase, -hits, -related, p.id)

    products = sorted(products, key=_rank_product)

    # Strong hits = user's brand/words; related = same food family (ice cream, dairy…).
    def _is_strong(p: Product) -> bool:
        blob = _blob(p)
        if q.lower() in blob:
            return True
        if not tokens:
            return False
        hits = sum(1 for t in tokens if t in blob)
        need = max(1, (len(tokens) + 1) // 2)
        return hits >= need

    strong_products = [p for p in products if _is_strong(p)]
    related_products = [
        p for p in products if not _is_strong(p) and _related_hits(p) > 0
    ][:16]

    reports = (
        db.query(Report)
        .options(joinedload(Report.product), joinedload(Report.issue_links).joinedload(ReportIssue.issue))
        .filter(
            or_(
                Report.text.ilike(like),
                Report.title.ilike(like),
                *[Report.text.ilike(f"%{t}%") for t in tokens[:6]],
            )
        )
        .order_by(Report.created_at.desc())
        .limit(20)
        .all()
    )
    semantic = similar_reports(db, q, limit=12)
    # Weak embedding hits should not hide a true miss.
    if not strong_products and not reports:
        semantic = [(report, score) for report, score in semantic if score >= 0.72]
    semantic_products: dict[int, dict] = {}
    for report, score in semantic:
        card = semantic_products.setdefault(
            report.product_id,
            {
                "product": product_card(report.product, compute_signal(db, report.product)),
                "score": score,
                "matched_excerpt": report.excerpt or report.text[:180],
            },
        )
        card["score"] = max(card["score"], score)

    discovery = None
    catalog_miss = not strong_products
    # Discover the exact brand online on a miss — still show related family hits meanwhile.
    should_discover = available_provider() and len(q) >= 3 and (catalog_miss or live)
    if not live and strong_products:
        should_discover = False
    if should_discover and catalog_miss:
        try:
            discovery = discover_from_query(db, q)
            if discovery.get("product"):
                slug = discovery["product"].get("slug") if isinstance(discovery["product"], dict) else None
                found = get_product(db, slug) if slug else None
                if found:
                    strong_products = [found]
                    products = [found] + [p for p in products if p.id != found.id]
                    reports = (
                        db.query(Report)
                        .options(
                            joinedload(Report.product),
                            joinedload(Report.issue_links).joinedload(ReportIssue.issue),
                        )
                        .filter(Report.product_id == found.id)
                        .order_by(Report.created_at.desc())
                        .limit(20)
                        .all()
                    )
        except Exception as exc:
            discovery = {
                "provider": None,
                "ingested": 0,
                "message": f"Live search failed ({exc}). Try again in a moment.",
            }

    # Exact/strong first, then same-family related (ice cream / dairy for Häagen-Dazs, etc.).
    display_products: list[Product] = []
    seen_ids: set[int] = set()
    for p in strong_products + related_products:
        if p.id in seen_ids:
            continue
        seen_ids.add(p.id)
        display_products.append(p)
    if not display_products:
        display_products = products

    product_cards = [product_card(product, compute_signal(db, product)) for product in display_products[:24]]
    # Only promote strong semantic hits into the product list.
    seen = {card["id"] for card in product_cards}
    for item in semantic_products.values():
        if item["score"] >= 0.72 and item["product"]["id"] not in seen:
            product_cards.append(item["product"])

    related_note = None
    if related_kws and related_products and not strong_products:
        related_note = (
            f"No exact match for “{q}” — showing related {', '.join(related_kws[:4])} items."
        )
    elif related_kws and related_products and strong_products:
        related_note = f"Also showing related {', '.join(related_kws[:3])} items."

    discovery_payload = None
    if discovery:
        discovery_payload = {
            "provider": discovery.get("provider"),
            "ingested": discovery.get("ingested", 0),
            "message": discovery.get("message") or related_note,
            "skipped": discovery.get("skipped"),
        }
    elif related_note:
        discovery_payload = {
            "provider": None,
            "ingested": 0,
            "message": related_note,
            "skipped": None,
        }

    return {
        "query": q,
        "products": product_cards,
        "reports": [
            {**report_card(report), "product_slug": report.product.slug, "product_name": report.product.name}
            for report in reports
        ],
        "semantic": sorted(semantic_products.values(), key=lambda item: item["score"], reverse=True),
        "discovery": discovery_payload,
    }


def discover_from_query(db: Session, query: str) -> dict:
    """Cold-path search: create a product from the query and scrape the public web.

    Food-ish queries become Food products. Specific physical product queries
    (heater, blender, etc.) are allowed here only — they are not home-bootstrapped.
    """
    provider = available_provider()
    if not provider:
        return {"provider": None, "ingested": 0, "message": "No search API key configured.", "product": None}

    settings = get_settings()
    foodish = _query_looks_like_food(query)

    from .pipeline.product_identity import normalize_product_identity

    identity = normalize_product_identity(query, context="user search")
    brand = identity.get("brand") if identity.get("brand") not in {None, "", "Unknown"} else "Search"
    name = identity.get("name") or (query.title() if len(query) < 80 else query[:80].title())
    category = "Food" if foodish or (identity.get("category") or "").lower() == "food" else (
        identity.get("category") or "Physical"
    )
    if category == "Uncategorized":
        category = "Food" if foodish else "Physical"

    # Dedicated catalog slug for this query — don't fuzzy-merge into unrelated CAERS/official SKUs.
    slug_base = re.sub(r"[^a-z0-9]+", "-", query.lower()).strip("-")[:56] or "query"
    slug = f"search-{slug_base}"
    product = db.query(Product).filter(Product.slug == slug).first()
    if not product:
        product = Product(
            slug=slug,
            brand=str(brand)[:120],
            name=str(name)[:180],
            category=category,
            summary=(
                f"Added from search for “{query}”. "
                "Pulling iWasPoisoned / Reddit / open-web reports…"
            )[:500],
        )
        db.add(product)
        db.flush()
    else:
        product.brand = str(brand)[:120]
        product.name = str(name)[:180]
        if foodish:
            product.category = "Food"
    db.commit()

    result = run_discovery(
        db,
        product.slug,
        extra=query,
        max_pages=min(settings.search_scrape_pages, 5),
        max_queries=4,
        force=True,
    )
    # Reload so signal includes freshly ingested reports.
    db.refresh(product)
    result["product"] = product_card(product, compute_signal(db, product))
    if not result.get("message"):
        ingested = result.get("ingested") or 0
        result["message"] = (
            f"Added “{product.name}” to the catalog"
            + (f" and ingested {ingested} public page{'s' if ingested != 1 else ''}." if ingested else ".")
        )
    return result


def _query_looks_like_food(query: str) -> bool:
    text = query.lower()
    food_needles = (
        "lettuce",
        "romaine",
        "spinach",
        "cheese",
        "milk",
        "yogurt",
        "chicken",
        "beef",
        "fish",
        "salmon",
        "ice cream",
        "chocolate",
        "chips",
        "sauce",
        "soup",
        "bread",
        "egg",
        "produce",
        "food",
        "cyclospora",
        "listeria",
        "salmonella",
        "e. coli",
        "ecoli",
        "outbreak",
        "contaminated",
        "allergen",
        "undeclared",
    )
    physical_needles = (
        "heater",
        "blender",
        "purifier",
        "headphones",
        "monitor",
        "cooker",
        "blanket",
        "lamp",
        "bottle",
        "charger",
        "battery",
        "overheat",
        "burning plastic",
    )
    if any(n in text for n in physical_needles) and not any(n in text for n in food_needles):
        return False
    if any(n in text for n in food_needles):
        return True
    # Default cold search toward food for this product's demo focus.
    return True


def search_locations(query: str) -> dict:
    q = sanitize_text(query, 80)
    if len(q) < 2:
        return {"locations": []}
    needle = q.lower()
    results: list[dict] = []
    seen: set[str] = set()
    for label, (lat, lng) in KNOWN_CITIES.items():
        if needle in label.lower():
            results.append({"label": label, "latitude": lat, "longitude": lng, "detail": "United States"})
            seen.add(label.lower())
    try:
        response = httpx.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": q, "count": 8, "language": "en", "format": "json"},
            timeout=8.0,
            verify=_verify(),
        )
        response.raise_for_status()
        for row in response.json().get("results") or []:
            name = sanitize_text(str(row.get("name") or ""), 80)
            if not name:
                continue
            admin = sanitize_text(str(row.get("admin1") or ""), 80)
            country = sanitize_text(str(row.get("country") or ""), 80)
            label = f"{name}, {admin}" if admin and admin.lower() != name.lower() else name
            key = label.lower()
            if key in seen:
                continue
            results.append(
                {
                    "label": label[:160],
                    "latitude": row.get("latitude"),
                    "longitude": row.get("longitude"),
                    "detail": ", ".join(part for part in (admin, country) if part),
                }
            )
            seen.add(key)
    except Exception:
        pass
    return {"locations": results[:8]}


def create_user_report(db: Session, payload: dict, user: AuthUser) -> dict:
    product = _resolve_product(db, payload)
    text = sanitize_text(payload.get("text") or "", 4000)
    if len(text) < 12:
        raise ValueError("Please describe what happened in a bit more detail.")
    display = user.display_name
    city = sanitize_text(payload.get("location_label") or "", 160) or None
    lat = snap_coordinate(payload.get("latitude"))
    lng = snap_coordinate(payload.get("longitude"))
    extracted = extract_report(text, f"{product.brand} {product.name}")
    report = Report(
        product_id=product.id,
        source="user_report",
        source_id=None,
        source_url=None,
        title=sanitize_text(payload.get("title") or "", 200) or None,
        text=text,
        excerpt=text[:220],
        incident_date=_parse_date(payload.get("incident_date")),
        latitude=lat if city else None,
        longitude=lng if city else None,
        location_label=city,
        location_precision="city" if city else "none",
        location_source="user" if city else "none",
        is_user_generated=True,
        display_name=display,
        user_sub=user.sub,
        extra_json=None,
    )
    db.add(report)
    db.flush()
    _apply_issues(db, report, extracted)
    attach_and_dedupe(db, report)

    post = Post(
        product_id=product.id,
        report_id=report.id,
        display_name=display,
        user_sub=user.sub,
        title=report.title or text[:72],
        body=text,
        location_label=city,
    )
    db.add(post)
    db.commit()
    db.refresh(product)
    return {
        "message": "Thank you — your report contributes to the community signal for this product.",
        "product": product_payload(db, product),
        "report": report_card(report),
        "extraction": extracted,
    }


def create_post(db: Session, payload: dict, user: AuthUser) -> dict:
    product = get_product(db, payload["product_slug"])
    if not product:
        raise ValueError("Unknown product")
    body = sanitize_text(payload.get("body") or "", 4000)
    if len(body) < 4:
        raise ValueError("Write a short post first.")
    display = user.display_name
    city = sanitize_text(payload.get("location_label") or "", 160) or None
    as_report = bool(payload.get("counts_as_report", True))
    report = None
    if as_report:
        extracted = extract_report(body, f"{product.brand} {product.name}")
        report = Report(
            product_id=product.id,
            source="community",
            text=body,
            excerpt=body[:220],
            is_user_generated=True,
            display_name=display,
            user_sub=user.sub,
            location_label=city,
            location_precision="city" if city else "none",
            location_source="user" if city else "none",
            latitude=snap_coordinate(payload.get("latitude")) if city else None,
            longitude=snap_coordinate(payload.get("longitude")) if city else None,
        )
        db.add(report)
        db.flush()
        _apply_issues(db, report, extracted)
        attach_and_dedupe(db, report)
    post = Post(
        product_id=product.id,
        report_id=report.id if report else None,
        display_name=display,
        user_sub=user.sub,
        title=sanitize_text(payload.get("title") or "", 200) or None,
        body=body,
        location_label=city,
    )
    db.add(post)
    db.commit()
    db.refresh(post)
    return {"post": post_card(post), "product_slug": product.slug}


def add_comment(db: Session, post_id: int, payload: dict, user: AuthUser) -> dict:
    post = db.query(Post).filter(Post.id == post_id).one_or_none()
    if not post:
        raise ValueError("Post not found")
    body = sanitize_text(payload.get("body") or "", 2000)
    if len(body) < 2:
        raise ValueError("Comment is empty")
    comment = Comment(
        post_id=post.id,
        display_name=user.display_name,
        user_sub=user.sub,
        body=body,
    )
    db.add(comment)
    db.commit()
    post = (
        db.query(Post)
        .options(joinedload(Post.comments), joinedload(Post.likes))
        .filter(Post.id == post_id)
        .one()
    )
    return {"post": post_card(post)}


def toggle_like(db: Session, post_id: int, user: AuthUser) -> dict:
    post = (
        db.query(Post)
        .options(joinedload(Post.comments), joinedload(Post.likes))
        .filter(Post.id == post_id)
        .one_or_none()
    )
    if not post:
        raise ValueError("Post not found")
    existing = next((like for like in post.likes if like.user_sub == user.sub), None)
    if existing:
        db.delete(existing)
    else:
        db.add(Like(post_id=post.id, display_name=user.display_name, user_sub=user.sub))
    db.commit()
    post = (
        db.query(Post)
        .options(joinedload(Post.comments), joinedload(Post.likes))
        .filter(Post.id == post_id)
        .one()
    )
    return {"post": post_card(post)}


def run_discovery(
    db: Session,
    product_slug: str,
    extra: str | None = None,
    max_pages: int | None = None,
    max_queries: int | None = None,
    force: bool = False,
) -> dict:
    settings = get_settings()
    product = get_product(db, product_slug)
    if not product:
        raise ValueError("Unknown product")
    provider = available_provider()
    if not provider:
        return {
            "provider": None,
            "message": (
                "No search API key is configured. Add EXA_API_KEY "
                "(or BRAVE_SEARCH_API_KEY / GEMINI_API_KEY / OPENAI_API_KEY) to enable live discovery."
            ),
            "hits": [],
            "ingested": 0,
            "skipped": False,
        }

    if not force and _discovery_on_cooldown(db, product.id, settings.discovery_cooldown_minutes):
        return {
            "provider": provider,
            "message": "Discovery recently ran for this product; skipped to save search quota.",
            "hits": [],
            "ingested": 0,
            "skipped": True,
            "product": product_payload(db, product),
        }

    page_cap = max_pages if max_pages is not None else settings.search_scrape_pages
    official = (
        db.query(Recall)
        .filter(Recall.product_id == product.id, Recall.official.is_(True))
        .order_by(Recall.recall_date.desc())
        .first()
    )

    from .agents import run_agent_pipeline

    pipeline = run_agent_pipeline(
        product=product,
        extra=extra,
        max_pages=page_cap,
        max_queries=max_queries,
        already_ingested=lambda url: _url_already_ingested(db, product.id, _normalize_url(url)),
        is_ingestible=_is_ingestible_url,
        is_agency=_is_agency_host,
        rank_url=_human_source_rank,
        official_recall=official,
    )
    provider = pipeline.get("provider")
    if not provider:
        return {
            "provider": None,
            "message": (
                "No search API key is configured. Add EXA_API_KEY "
                "(or BRAVE_SEARCH_API_KEY / GEMINI_API_KEY) to enable live discovery."
            ),
            "hits": [],
            "ingested": 0,
            "skipped": False,
            "agent_log": pipeline.get("agent_log") or [],
        }

    queries = pipeline.get("queries") or []
    hits = pipeline.get("hits") or []
    notes = list(pipeline.get("notes") or [])
    ingested = 0
    findings: list[dict] = []

    for item in pipeline.get("candidates") or []:
        final_url = item["final_url"]
        url_key = _normalize_url(final_url)
        if _url_already_ingested(db, product.id, url_key):
            notes.append(f"dup {final_url}")
            continue
        extracted = extract_report(item["text"], f"{product.brand} {product.name}")
        source = _source_label(final_url)
        geo = item.get("geo") or {}
        triage = item.get("triage") or {}
        excerpt = (item.get("snippet") or item["text"])[:220]
        if triage.get("label"):
            excerpt = f"[{triage.get('label')}] {excerpt}"[:220]
        report = Report(
            product_id=product.id,
            source=source,
            source_id=url_key[:240],
            source_url=final_url[:700],
            title=item.get("title"),
            text=item["text"][:4000],
            excerpt=excerpt,
            is_user_generated=False,
            location_label=geo.get("location_label"),
            location_precision=geo.get("location_precision") or "none",
            location_source=geo.get("location_source") or "none",
        )
        db.add(report)
        db.flush()
        _apply_issues(db, report, extracted)
        attach_and_dedupe(db, report)
        ingested += 1
        findings.append(
            {
                "title": item.get("title") or final_url,
                "url": final_url,
                "host": item.get("host") or domain_of(final_url),
                "source": source,
                "triage": triage.get("label"),
            }
        )

    # Confirm official status when triage saw recall coverage.
    coverage = pipeline.get("recall_coverage") or []
    if coverage:
        from .bootstrap import ensure_recall_from_discovery

        if ensure_recall_from_discovery(db, product, coverage):
            notes.append("openfda:recall-attached-from-coverage")
        else:
            notes.append("openfda:coverage-unconfirmed")

    agent_bits = []
    for step in pipeline.get("agent_log") or []:
        name = step.get("agent")
        if "queries" in step:
            agent_bits.append(f"{name}:{len(step['queries'])}q")
        elif "hit_count" in step:
            agent_bits.append(f"{name}:{step['hit_count']}hits")
        elif "fetched" in step:
            agent_bits.append(f"{name}:{step['fetched']}pages")
        elif "kept" in step:
            agent_bits.append(
                f"{name}:kept{step['kept']}/cov{step.get('coverage', 0)}/rej{step.get('rejected', 0)}"
            )
        elif "located" in step:
            agent_bits.append(f"{name}:{step['located']}geo")
    agent_summary = ", ".join(agent_bits)
    db.add(
        DiscoveryRun(
            product_id=product.id,
            query=" | ".join(queries)[:900],
            provider=f"agents:{provider}",
            result_count=len(hits),
            notes=(agent_summary + " | " + "; ".join(notes))[:1000],
        )
    )
    db.commit()
    if ingested and settings.seed_fake_posts:
        from .bootstrap import seed_posts_from_ingest

        seed_posts_from_ingest(db, product, findings)
    return {
        "provider": provider,
        "queries": queries,
        "hits": [
            {"title": hit.title, "url": hit.url, "snippet": hit.snippet, "query": hit.query} for hit in hits
        ],
        "ingested": ingested,
        "notes": notes,
        "skipped": False,
        "agent_log": pipeline.get("agent_log") or [],
        "product": product_payload(db, product),
    }


def _discovery_on_cooldown(db: Session, product_id: int, minutes: int) -> bool:
    if minutes <= 0:
        return False
    cutoff = datetime.utcnow() - timedelta(minutes=minutes)
    latest = (
        db.query(DiscoveryRun)
        .filter(DiscoveryRun.product_id == product_id, DiscoveryRun.created_at >= cutoff)
        .order_by(DiscoveryRun.created_at.desc())
        .first()
    )
    return latest is not None


def _normalize_url(url: str) -> str:
    return (url or "").split("#")[0].rstrip("/")


def _is_ingestible_url(url: str | None) -> bool:
    if not url:
        return False
    lowered = url.strip().lower()
    if not (lowered.startswith("http://") or lowered.startswith("https://")):
        return False
    host = domain_of(url)
    if not host or host == "example.com" or host.endswith(".example.com"):
        return False
    return True


def _is_agency_host(url: str | None) -> bool:
    host = domain_of(url or "")
    host = host[4:] if host.startswith("www.") else host
    needles = (
        "cdc.gov",
        "fda.gov",
        "accessdata.fda.gov",
        "fsis.usda.gov",
        "canada.ca",
        "foodsafety.gov",
        "who.int",
        "fsai.ie",
        "food.gov.uk",
        "inspection.gc.ca",
        "efsa.europa.eu",
    )
    return any(host == n or host.endswith("." + n) for n in needles)


def _human_source_rank(url: str) -> int:
    """Lower is better — Reddit / iWasPoisoned / social first; agency last."""
    host = domain_of(url or "")
    host = host[4:] if host.startswith("www.") else host
    if "reddit.com" in host or host.endswith(".reddit.com"):
        return 0
    if "iwaspoisoned.com" in host:
        return 0
    if any(
        x in host
        for x in (
            "facebook.com",
            "nextdoor.com",
            "discord.com",
            "tiktok.com",
            "x.com",
            "twitter.com",
            "threads.net",
        )
    ):
        return 1
    if _is_agency_host(url):
        return 9
    if any(host == d or host.endswith("." + d) for d in NEWS_DOMAINS):
        return 4
    return 3


def _url_already_ingested(db: Session, product_id: int, url_key: str) -> bool:
    if not url_key:
        return False
    return (
        db.query(Report)
        .filter(
            Report.product_id == product_id,
            or_(Report.source_url == url_key, Report.source_id == url_key[:240]),
        )
        .count()
        > 0
    )


def _source_label(url: str) -> str:
    host = domain_of(url)
    host = host[4:] if host.startswith("www.") else host
    if "reddit.com" in host:
        return "reddit"
    if "iwaspoisoned.com" in host:
        return "web"
    if any(host == domain or host.endswith("." + domain) for domain in NEWS_DOMAINS):
        return "news"
    if "cpsc.gov" in host or "saferproducts.gov" in host:
        return "cpsc"
    if "fda.gov" in host or "accessdata.fda.gov" in host:
        return "fda"
    return "web"


def _resolve_product(db: Session, payload: dict) -> Product:
    from .pipeline.product_identity import normalize_product_identity

    context = sanitize_text(payload.get("text") or "", 800)
    if payload.get("product_slug"):
        product = get_product(db, payload["product_slug"])
        if product:
            if _product_needs_polish(product):
                identity = normalize_product_identity(
                    product.name,
                    brand=product.brand if (product.brand or "").lower() not in {"unknown", "search"} else None,
                    context=context,
                )
                _polish_product_identity(product, identity)
            return product
    name = sanitize_text(payload.get("product_name") or "", 200)
    brand = sanitize_text(payload.get("brand") or "", 120)
    if not name:
        raise ValueError("A product is required")

    identity = normalize_product_identity(
        name,
        brand=brand or None,
        context=context,
    )
    matched = _find_matching_product(db, identity, raw_name=name)
    if matched:
        _polish_product_identity(matched, identity)
        return matched

    slug = _slugify(f"{identity['brand']} {identity['name']}")
    # Avoid colliding with an existing slug from a different naming path.
    existing = get_product(db, slug)
    if existing:
        _polish_product_identity(existing, identity)
        return existing

    product = Product(
        slug=slug[:160],
        brand=identity["brand"] or "Unknown",
        name=identity["name"],
        model=sanitize_text(payload.get("model") or "", 80) or None,
        category=sanitize_text(payload.get("category") or identity.get("category") or "Uncategorized", 80),
        upc=sanitize_text(payload.get("upc") or "", 32) or None,
        summary=sanitize_text(
            payload.get("summary") or f"Community reports about {identity['brand']} {identity['name']}.",
            500,
        ),
    )
    db.add(product)
    db.flush()
    return product


def _product_needs_polish(product: Product) -> bool:
    brand = (product.brand or "").strip().lower()
    name = product.name or ""
    return brand in {"", "unknown", "search"} or name == name.lower() or name == name.upper()


def _find_matching_product(db: Session, identity: dict, *, raw_name: str) -> Product | None:
    """Prefer an existing catalog row over creating a near-duplicate."""
    brand = (identity.get("brand") or "").strip()
    name = (identity.get("name") or "").strip()
    aliases = [a for a in (identity.get("aliases") or []) if a]
    needles = {raw_name.lower(), name.lower()}
    needles.update(a.lower() for a in aliases)
    if brand and brand.lower() != "unknown":
        needles.add(f"{brand} {name}".lower())
        needles.add(brand.lower())

    # Exact name (case-insensitive), optionally with brand.
    named = db.query(Product).filter(Product.name.ilike(name))
    if brand and brand.lower() != "unknown":
        branded = named.filter(Product.brand.ilike(brand)).first()
        if branded:
            return branded
    exact = named.first()
    if exact:
        return exact

    # Raw typed name exact.
    raw_hit = db.query(Product).filter(Product.name.ilike(raw_name)).first()
    if raw_hit:
        return raw_hit

    # Containment / alias match against a bounded catalog scan.
    products = db.query(Product).order_by(Product.id.desc()).limit(400).all()
    compact_needles = [n for n in needles if len(n) >= 4]

    best: Product | None = None
    best_score = 0
    for product in products:
        blob = f"{product.brand} {product.name}".lower()
        score = 0
        for needle in compact_needles:
            if needle == product.name.lower() or needle == f"{product.brand} {product.name}".lower():
                score = max(score, 100)
            elif needle in blob or product.name.lower() in needle:
                score = max(score, 40 + min(len(needle), 20))
        if score > best_score:
            best_score = score
            best = product
    if best and best_score >= 40:
        return best
    return None


def _polish_product_identity(product: Product, identity: dict) -> None:
    """Upgrade placeholder catalog rows (Unknown / all-lowercase) to normalized identity."""
    brand = (identity.get("brand") or "").strip()
    name = (identity.get("name") or "").strip()
    category = (identity.get("category") or "").strip()
    if not name:
        return
    dirty_brand = (product.brand or "").strip().lower() in {"", "unknown", "search"}
    dirty_name = product.name == product.name.lower() or product.name == product.name.upper()
    if dirty_brand and brand and brand.lower() != "unknown":
        product.brand = brand
    if dirty_name:
        product.name = name
    if category and (not product.category or product.category == "Uncategorized"):
        product.category = category
    if dirty_brand or dirty_name:
        # Keep slug stable if already referenced; only refresh summary when placeholder-ish.
        if not product.summary or "community report" in (product.summary or "").lower():
            product.summary = f"Community reports about {product.brand} {product.name}."[:500]


def _apply_issues(db: Session, report: Report, extracted: dict) -> None:
    names = []
    if extracted.get("issues"):
        names = [item.get("issue") for item in extracted["issues"] if item.get("issue")]
    elif extracted.get("issue"):
        names = [extracted["issue"]]
    for raw in names:
        slug = _slugify(raw)
        issue = db.query(Issue).filter(Issue.slug == slug).one_or_none()
        if not issue:
            issue = Issue(
                slug=slug,
                name=raw.title(),
                description="Community-described issue",
                category=extracted.get("category") or "community",
                icon="•",
            )
            db.add(issue)
            db.flush()
        exists = (
            db.query(ReportIssue)
            .filter(ReportIssue.report_id == report.id, ReportIssue.issue_id == issue.id)
            .one_or_none()
        )
        if not exists:
            db.add(ReportIssue(report_id=report.id, issue_id=issue.id, confidence=0.7))


def _slugify(value: str) -> str:
    import re

    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "product"


def _parse_date(value) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", ""))
    except ValueError:
        return None
