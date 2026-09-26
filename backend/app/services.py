from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

import httpx

from .auth import AuthUser
from .config import get_settings
from .data_sources.page_fetch import domain_of, fetch_readable
from .data_sources.web_search import available_provider, niche_queries, search_web
from .openai_http import _verify
from .seed import CITIES as KNOWN_CITIES
from .models import Comment, DiscoveryRun, Issue, Like, Post, Product, Report, ReportIssue, TimelineEvent
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
            "Community signals are not proof that a product is unsafe. "
            "They identify patterns worth investigating."
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
    """Cold-path search: create a product from the query and scrape the public web."""
    provider = available_provider()
    if not provider:
        return {"provider": None, "ingested": 0, "message": "No search API key configured.", "product": None}

    settings = get_settings()
    product = _resolve_product(
        db,
        {
            "product_name": query.title() if len(query) < 80 else query[:80].title(),
            "brand": "Search",
            "category": "Discovered",
            "summary": f"Created from search for “{query}”.",
        },
    )
    product.summary = product.summary or f"Created from search for “{query}”."
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
                "No search API key is configured. Add BRAVE_SEARCH_API_KEY, "
                "OPENAI_API_KEY, GEMINI_API_KEY, or EXA_API_KEY to enable live discovery."
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
    queries = niche_queries(f"{product.brand} {product.name}", extra, max_queries=max_queries)
    hits = search_web(queries)
    ingested = 0
    notes: list[str] = []
    for hit in hits[:page_cap]:
        url_key = _normalize_url(hit.url)
        if _url_already_ingested(db, product.id, url_key):
            notes.append(f"dup {hit.url}")
            continue
        try:
            page = fetch_readable(hit.url)
        except Exception as exc:
            notes.append(f"skipped {hit.url}: {exc.__class__.__name__}")
            continue
        if len(page["text"]) < 40:
            notes.append(f"thin {hit.url}")
            continue
        extracted = extract_report(page["text"], f"{product.brand} {product.name}")
        source = _source_label(page["url"] or hit.url)
        report = Report(
            product_id=product.id,
            source=source,
            source_id=url_key[:240],
            source_url=(page["url"] or hit.url)[:700],
            title=page["title"],
            text=page["text"][:4000],
            excerpt=(hit.snippet or page["text"])[:220],
            is_user_generated=False,
        )
        db.add(report)
        db.flush()
        _apply_issues(db, report, extracted)
        attach_and_dedupe(db, report)
        ingested += 1
    db.add(
        DiscoveryRun(
            product_id=product.id,
            query=" | ".join(queries),
            provider=provider,
            result_count=len(hits),
            notes="; ".join(notes)[:1000],
        )
    )
    db.commit()
    return {
        "provider": provider,
        "queries": queries,
        "hits": [
            {"title": hit.title, "url": hit.url, "snippet": hit.snippet, "query": hit.query} for hit in hits
        ],
        "ingested": ingested,
        "notes": notes,
        "skipped": False,
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
    if any(host == domain or host.endswith("." + domain) for domain in NEWS_DOMAINS):
        return "news"
    if "cpsc.gov" in host or "saferproducts.gov" in host:
        return "cpsc"
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
