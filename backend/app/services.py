from __future__ import annotations

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
    important = [product_card(item["product"], item["signal"], item["local"]) for item in cards[:8]]
    nearby = [card for card in important if card["local"]]
    trending = sorted(
        [card for card in important if card["signal"].get("velocity_percent")],
        key=lambda card: card["signal"]["velocity_percent"] or 0,
        reverse=True,
    )[:6]
    recent = (
        db.query(Report)
        .options(joinedload(Report.issue_links).joinedload(ReportIssue.issue), joinedload(Report.product))
        .order_by(Report.created_at.desc())
        .limit(10)
        .all()
    )
    return {
        "important": important,
        "nearby": nearby,
        "trending": trending,
        "recent_reports": [
            {**report_card(report), "product_slug": report.product.slug, "product_name": report.product.name}
            for report in recent
        ],
        "visitor_city": city,
        "disclaimer": (
            "Early internet clusters are a heads-up, not a verdict. "
            "Official recalls stay official. The point is seeing the pattern before — or without — an FDA page."
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

    like = f"%{q}%"
    products = (
        db.query(Product)
        .filter(
            or_(
                Product.name.ilike(like),
                Product.brand.ilike(like),
                Product.model.ilike(like),
                Product.category.ilike(like),
                Product.upc.ilike(like),
                Product.slug.ilike(like),
                Product.summary.ilike(like),
            )
        )
        .all()
    )
    reports = (
        db.query(Report)
        .options(joinedload(Report.product), joinedload(Report.issue_links).joinedload(ReportIssue.issue))
        .filter(or_(Report.text.ilike(like), Report.title.ilike(like)))
        .order_by(Report.created_at.desc())
        .limit(20)
        .all()
    )
    semantic = similar_reports(db, q, limit=12)
    # Weak embedding hits should not hide a true miss.
    if not products and not reports:
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
    if live and available_provider() and len(q) >= 3:
        if products:
            target = products[0]
            web_count = (
                db.query(Report)
                .filter(
                    Report.product_id == target.id,
                    Report.source.in_(("web", "reddit", "news")),
                )
                .count()
            )
            if web_count < 4:
                discovery = run_discovery(
                    db,
                    target.slug,
                    extra=q,
                    max_pages=settings.search_scrape_pages,
                    force=False,
                )
                refreshed = get_product(db, target.slug)
                if refreshed:
                    products = [refreshed] + [p for p in products if p.id != target.id]
        else:
            discovery = discover_from_query(db, q)
            if discovery.get("product"):
                slug = discovery["product"]["slug"]
                found = get_product(db, slug)
                if found:
                    products = [found]

    product_cards = [product_card(product, compute_signal(db, product)) for product in products]
    # Only promote strong semantic hits into the product list.
    seen = {card["id"] for card in product_cards}
    for item in semantic_products.values():
        if item["score"] >= 0.72 and item["product"]["id"] not in seen:
            product_cards.append(item["product"])

    if discovery and discovery.get("ingested"):
        reports = (
            db.query(Report)
            .options(joinedload(Report.product), joinedload(Report.issue_links).joinedload(ReportIssue.issue))
            .filter(or_(Report.text.ilike(like), Report.title.ilike(like)))
            .order_by(Report.created_at.desc())
            .limit(20)
            .all()
        )

    return {
        "query": q,
        "products": product_cards,
        "reports": [
            {**report_card(report), "product_slug": report.product.slug, "product_name": report.product.name}
            for report in reports
        ],
        "semantic": sorted(semantic_products.values(), key=lambda item: item["score"], reverse=True),
        "discovery": {
            "provider": discovery.get("provider") if discovery else None,
            "ingested": discovery.get("ingested", 0) if discovery else 0,
            "message": discovery.get("message") if discovery else None,
            "skipped": discovery.get("skipped") if discovery else None,
        }
        if discovery
        else None,
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
    product = _resolve_product(
        db,
        {
            "product_name": query.title() if len(query) < 80 else query[:80].title(),
            "brand": "Search",
            "category": "Food" if foodish else "Physical",
            "summary": f"Created from search for “{query}”.",
        },
    )
    product.summary = product.summary or f"Created from search for “{query}”."
    if foodish:
        product.category = "Food"
    db.commit()

    result = run_discovery(
        db,
        product.slug,
        extra=query,
        max_pages=settings.search_scrape_pages,
        max_queries=3,
        force=True,
    )
    result["product"] = product_card(product, compute_signal(db, product))
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
    if payload.get("product_slug"):
        product = get_product(db, payload["product_slug"])
        if product:
            return product
    name = sanitize_text(payload.get("product_name") or "", 200)
    brand = sanitize_text(payload.get("brand") or "", 120)
    if not name:
        raise ValueError("A product is required")
    slug = _slugify(f"{brand} {name}")
    existing = get_product(db, slug)
    if existing:
        return existing
    named = db.query(Product).filter(Product.name.ilike(name))
    if brand:
        named = named.filter(Product.brand.ilike(brand))
    existing_named = named.first()
    if existing_named:
        return existing_named
    product = Product(
        slug=slug,
        brand=brand or "Unknown",
        name=name,
        model=sanitize_text(payload.get("model") or "", 80) or None,
        category=sanitize_text(payload.get("category") or "Uncategorized", 80),
        upc=sanitize_text(payload.get("upc") or "", 32) or None,
        summary=sanitize_text(payload.get("summary") or "Created from a community report.", 500),
    )
    db.add(product)
    db.flush()
    return product


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
