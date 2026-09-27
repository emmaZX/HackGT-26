from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta

from sqlalchemy.orm import Session, joinedload

from ..models import Product, Recall, Report, ReportIssue
from .cluster import cluster_strength_from_reports
from .spikes import score_caers_spike

# ---------------------------------------------------------------------------
# Signal methodology (MVP, intentionally replaceable)
#
# We do NOT publish a "danger score." We compute an internal strength in [0, 1]
# from transparent, user-visible ingredients, then map it to a label:
#
#   recent_report_velocity     how many reports arrived in the last 7 days
#                              vs the previous 7 days
#   source_diversity           unique sources / domains contributing
#   semantic_cluster_strength  how similarly independent reports describe
#                              the same issue (lexical or embedding cosine)
#   geographic_distribution    unique coarse locations (optional enrichment)
#   deviation_from_baseline    last 7 days vs the prior 30-day weekly average
#   independence               unique-ish reports after near-duplicate collapse
#
# Official recalls are a separate overlay. They never inflate this score.
# A product may have no recall and a strong community signal.
# ---------------------------------------------------------------------------

LABELS = (
    (0.75, "strong_emerging_signal", "Strong emerging signal"),
    (0.50, "emerging_signal", "Emerging safety signal"),
    (0.30, "elevated_reports", "Elevated reports"),
    (0.15, "limited_reports", "Limited reports"),
    (0.00, "no_significant_signal", "No significant signal"),
)


def _label_for(score: float) -> tuple[str, str]:
    for threshold, key, title in LABELS:
        if score >= threshold:
            return key, title
    return "no_significant_signal", "No significant signal"


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def compute_signal(db: Session, product: Product, now: datetime | None = None) -> dict:
    now = now or datetime.utcnow()
    reports = (
        db.query(Report)
        .options(
            joinedload(Report.issue_links).joinedload(ReportIssue.issue),
            joinedload(Report.embedding),
        )
        .filter(Report.product_id == product.id)
        .all()
    )
    recalls = (
        db.query(Recall)
        .filter(Recall.product_id == product.id, Recall.official.is_(True))
        .order_by(Recall.recall_date.desc())
        .all()
    )

    total = len(reports)
    independent = sum(r.independence_weight for r in reports)
    unique_sources = {r.source for r in reports}
    unique_source_ids = {(r.source, r.source_id or r.source_url or r.id) for r in reports}

    week = now - timedelta(days=7)
    prev_week = now - timedelta(days=14)
    month = now - timedelta(days=30)
    recent = [r for r in reports if r.created_at >= week]
    previous = [r for r in reports if prev_week <= r.created_at < week]
    baseline = [r for r in reports if month <= r.created_at < week]

    recent_count = len(recent)
    previous_count = len(previous)
    velocity_ratio = recent_count / max(previous_count, 1)
    weekly_baseline = len(baseline) / 3.3 if baseline else 0.0
    baseline_ratio = recent_count / max(weekly_baseline, 1)

    geo_labels = [r.location_label for r in reports if r.location_label]
    geo_count = len(set(geo_labels))

    semantic = cluster_strength_from_reports([r for r in reports if not r.is_duplicate])

    source_div = _clamp(len(unique_sources) / 5.0)
    geo_component = _clamp(geo_count / 5.0)
    velocity_component = _clamp((velocity_ratio - 1.0) / 4.0) if recent_count else 0.0
    if recent_count >= 8 and previous_count == 0:
        velocity_component = max(velocity_component, 0.7)
    baseline_component = _clamp((baseline_ratio - 1.0) / 3.0)
    volume_component = _clamp(independent / 25.0)
    independence_component = _clamp(independent / max(total, 1))

    strength = (
        0.22 * velocity_component
        + 0.18 * source_div
        + 0.18 * semantic
        + 0.12 * geo_component
        + 0.18 * baseline_component
        + 0.12 * volume_component
    )
    # Independence is a multiplier so quote-repost storms cannot manufacture a signal.
    strength = _clamp(strength * (0.55 + 0.45 * independence_component))

    key, title = _label_for(strength)
    # Prefer Ongoing openFDA notices only — never surface terminated history.
    ongoing = [
        r
        for r in recalls
        if (r.reason or "").lower().startswith("[ongoing]")
    ]
    official = ongoing[0] if ongoing else None

    issue_counts: dict[str, dict] = {}
    for report in reports:
        for link in report.issue_links:
            bucket = issue_counts.setdefault(
                link.issue.slug,
                {"slug": link.issue.slug, "name": link.issue.name, "icon": link.issue.icon, "count": 0},
            )
            bucket["count"] += 1
    issues = sorted(issue_counts.values(), key=lambda item: item["count"], reverse=True)

    geo_buckets = Counter(geo_labels)
    geo_coords: dict[str, tuple[float | None, float | None]] = {}
    for report in reports:
        if report.location_label and report.location_label not in geo_coords:
            geo_coords[report.location_label] = (report.latitude, report.longitude)
    geography = [
        {
            "label": label,
            "count": count,
            "latitude": geo_coords.get(label, (None, None))[0],
            "longitude": geo_coords.get(label, (None, None))[1],
        }
        for label, count in geo_buckets.most_common(8)
    ]

    velocity_display = 0
    if previous_count:
        velocity_display = round(((recent_count - previous_count) / previous_count) * 100)
    elif recent_count:
        velocity_display = None

    why = _explain(
        title=title,
        recent_count=recent_count,
        previous_count=previous_count,
        independent=independent,
        total=total,
        geo_count=geo_count,
        issues=issues,
        official=official,
        internet_before_official=False,
    )

    internet_before_official = False
    if official and reports:
        internet_before_official = any(r.created_at.date() < official.recall_date.date() for r in reports)
        if internet_before_official:
            why = (
                f"Public and community reports were already clustering before the "
                f"{official.agency} notice on {official.recall_date.date().isoformat()}. "
                f"About {int(round(independent))} independent-looking reports describe "
                f"{(issues[0]['name'] if issues else 'the same problem').lower()}. "
                "Official recall status is shown separately and does not replace the community signal."
            )
        else:
            why = (
                f"{title} from community and public web reports. "
                f"An official {official.agency} recall is also on record — shown separately, "
                "not as proof that early posts predicted the recall."
            )

    outbreak = _outbreak_from_reports(reports, product)
    spike = None
    caers_reports = [r for r in reports if r.source == "caers"]
    if caers_reports:
        spike = score_caers_spike(db, product.id, now=now)
        if not spike.get("is_spike"):
            spike = {**spike, "is_spike": False}

    source_tier = _source_tier(
        official=official,
        outbreak=outbreak,
        spike=spike,
        caers_count=len(caers_reports),
        slug=product.slug or "",
    )

    if outbreak and not official:
        why = (
            f"FDA outbreak investigation #{outbreak['ref']} ({outbreak['pathogen']}) is active. "
            f"Linked product status: {outbreak.get('product_status') or 'see advisory'}. "
            "This is an official investigation watch — not the same as a product recall "
            "unless a recall was separately initiated."
        )
    elif spike and spike.get("is_spike") and source_tier == "caers":
        why = (
            product.summary
            or (
                f"CAERS adverse-event reports rose to {spike['recent_count']} in the last "
                f"{spike['window_days']} days vs a weekly baseline of {spike['baseline_weekly']} "
                f"({spike['velocity_ratio']}×). Not an official recall — reports are unverified."
            )
        )

    return {
        "signal_type": key,
        "severity_key": key,
        "severity_label": title,
        "internal_strength": round(strength, 3),
        "report_count": total,
        "independent_count": int(round(independent)),
        "recent_report_count": recent_count,
        "previous_report_count": previous_count,
        "velocity_percent": velocity_display,
        "source_diversity": len(unique_sources),
        "unique_source_ids": len(unique_source_ids),
        "geographic_count": geo_count,
        "geography": geography,
        "issues": issues,
        "explanation": why,
        "official_recall": _serialize_recall(official) if official else None,
        "internet_before_official": internet_before_official,
        "source_tier": source_tier,
        "spike": spike if (spike and spike.get("is_spike")) else None,
        "outbreak": outbreak,
        "components": {
            "recent_report_velocity": round(velocity_component, 3),
            "source_diversity": round(source_div, 3),
            "semantic_cluster_strength": round(semantic, 3),
            "geographic_distribution": round(geo_component, 3),
            "deviation_from_historical_baseline": round(baseline_component, 3),
            "independence": round(independence_component, 3),
        },
    }


def _source_tier(*, official, outbreak, spike, caers_count: int = 0, slug: str = "") -> str:
    if official or outbreak:
        return "official"
    # CAERS-backed grocery items belong in the CAERS tier (spike is a tag, not the only entry).
    if caers_count > 0 or slug.startswith("caers-"):
        return "caers"
    if spike and spike.get("is_spike"):
        return "caers"
    return "unofficial"


def _outbreak_from_reports(reports: list[Report], product: Product) -> dict | None:
    outbreak_reports = [r for r in reports if r.source == "fda_outbreak"]
    if not outbreak_reports and not (product.slug or "").startswith("outbreak-"):
        return None
    ref = (product.slug or "").replace("outbreak-", "", 1) if (product.slug or "").startswith("outbreak-") else ""
    pathogen = ""
    cases = None
    product_status = None
    source_url = None
    active = True
    for report in outbreak_reports:
        source_url = source_url or report.source_url
        title = report.title or ""
        if "ref:" in (report.text or ""):
            # text may be "ref:1417|pathogen:…|cases:…|product:…"
            parts = dict(
                part.split(":", 1) for part in (report.text or "").split("|") if ":" in part
            )
            ref = parts.get("ref", ref)
            pathogen = parts.get("pathogen", pathogen)
            cases = parts.get("cases") or cases
            product_status = parts.get("product") or product_status
            if parts.get("active", "true").lower() in {"0", "false", "no"}:
                active = False
        elif not pathogen and title:
            pathogen = title
    if not ref and product.slug and product.slug.startswith("outbreak-"):
        ref = product.slug.split("outbreak-", 1)[-1]
    if not ref:
        return None
    if not pathogen:
        # Fall back to product name "Pathogen — Product"
        pathogen = (product.name or "").split("—")[0].strip() or "Foodborne pathogen"
    return {
        "ref": ref,
        "pathogen": pathogen,
        "cases": cases,
        "active": active,
        "product_status": product_status,
        "source_url": source_url,
    }


def _explain(*, title, recent_count, previous_count, independent, total, geo_count, issues, official, internet_before_official) -> str:
    top = issues[0]["name"] if issues else "the same problem"
    if total == 0 and official:
        return (
            f"An official recall is on record from {official.agency}. "
            "No earlier community cluster is loaded for this product yet."
        )
    if previous_count:
        ratio = recent_count / max(previous_count, 1)
        return (
            f"{title} because about {int(round(independent))} independent reports "
            f"(of {total} total) describe {top.lower()}. "
            f"Reports increased {ratio:.1f}× over the previous 7 days"
            + (f", across {geo_count} places." if geo_count else ".")
            + " No official recall is required for a pattern to be worth watching."
        )
    if total == 0:
        return "No community reports are associated with this product in connected sources yet."
    return (
        f"{title} based on {int(round(independent))} independent-looking reports "
        f"describing {top.lower()}. This is a pattern in public and community reports — "
        "often visible before any official recall page exists."
    )


def _serialize_recall(recall: Recall) -> dict:
    status = "Unknown"
    reason = recall.reason or ""
    if reason.startswith("[") and "]" in reason[:40]:
        status = reason[1 : reason.index("]")]
        reason = reason[reason.index("]") + 1 :].strip()
    # Date fallback: older than ~6 months treated as past unless marked Ongoing.
    age_days = (datetime.utcnow() - recall.recall_date).days if recall.recall_date else 9999
    if status.lower() == "ongoing":
        phase = "ongoing"
    elif status.lower() in {"terminated", "completed"} or age_days > 180:
        phase = "past"
    else:
        phase = "ongoing" if age_days <= 120 else "past"
    return {
        "agency": recall.agency,
        "recall_date": recall.recall_date.date().isoformat(),
        "reason": reason,
        "hazard": recall.hazard,
        "source_url": recall.source_url,
        "nationwide": recall.nationwide,
        "status": status,
        "phase": phase,
    }


def feed_cards(db: Session, visitor_city: str | None = None) -> list[dict]:
    cards = []
    # Prefer products that already have official / outbreak / CAERS evidence,
    # then fill with remaining food SKUs.
    from sqlalchemy import or_

    from ..models import Recall

    official_ids = {
        r.product_id
        for r in db.query(Recall.product_id).filter(Recall.official.is_(True)).all()
    }
    clauses = [
        Product.slug.like("outbreak-%"),
        Product.slug.like("fsis-%"),
        Product.slug.like("caers-%"),
    ]
    if official_ids:
        clauses.insert(0, Product.id.in_(official_ids))
    special = (
        db.query(Product)
        .filter(Product.category == "Food", or_(*clauses))
        .order_by(Product.id)
        .limit(200)
        .all()
    )
    special_ids = [p.id for p in special] or [-1]
    extras = (
        db.query(Product)
        .filter(Product.category == "Food", ~Product.id.in_(special_ids))
        .order_by(Product.id)
        .limit(80)
        .all()
    )
    products = special + extras
    for product in products:
        reports = (
            db.query(Report)
            .filter(Report.product_id == product.id, Report.is_duplicate.is_(False))
            .all()
        )
        signal = compute_signal(db, product)
        tier = signal.get("source_tier") or "unofficial"
        # Keep official, CAERS grocery items, and unofficial clusters with signal.
        if tier == "official":
            pass
        elif tier == "caers":
            # Drop FOIA noise / empty shells.
            if (product.slug or "").startswith("caers-") and signal.get("report_count", 0) < 1:
                continue
            if re.search(r"exemption\s*4", f"{product.brand} {product.name}", re.I):
                continue
            # CAERS home items must still be within lookback (use newest report date).
            from ..config import get_settings as _gs
            from .evidence_schema import within_recency

            newest = max((r.incident_date or r.created_at for r in reports), default=None)
            if newest and not within_recency(newest, days=_gs().caers_lookback_days):
                continue
        else:
            if (product.slug or "").startswith("caers-"):
                continue
            # Unofficial: require URL-backed recent evidence — never invented community seeds.
            from ..config import get_settings as _gs
            from .evidence_schema import within_recency

            settings = _gs()
            url_reports = [
                r
                for r in reports
                if r.source_url
                and r.source in {"web", "reddit", "news", "iwaspoisoned", "x", "community"}
                and within_recency(
                    r.incident_date or r.created_at,
                    days=settings.discovery_recency_days,
                )
            ]
            hosts = {(r.source_url or "") for r in url_reports}
            # Surface specific products from the scrape; multi-URL patterns rank higher.
            if len(hosts) < max(1, settings.community_min_url_reports):
                continue
            if not url_reports:
                continue
        local = False
        if visitor_city:
            local = any(visitor_city.lower() == g["label"].lower() for g in signal["geography"])
        # Final quality gate — never show legalese / unidentified junk on home.
        from .glance_titles import is_sensible_product

        if not is_sensible_product(product.brand, product.name, slug=product.slug):
            continue
        # Attach reports so product_card can serialize linked evidence URLs.
        product.reports = reports  # type: ignore[attr-defined]
        cards.append({"product": product, "signal": signal, "local": local})

    def sort_key(item: dict) -> tuple:
        signal = item["signal"]
        tier = signal.get("source_tier") or "unofficial"
        tier_rank = {"official": 0, "caers": 1, "unofficial": 2}.get(tier, 3)
        spike_ratio = -((signal.get("spike") or {}).get("velocity_ratio") or 0)
        # Mix outbreak watches and recalls (don't bury FSIS under outbreaks).
        has_outbreak = 0 if signal.get("outbreak") else 1
        has_recall = 0 if signal.get("official_recall") else 1
        # Prefer items that have either official signal; among them prefer recalls slightly
        # so meat/poultry FSIS cards aren't crowded out by every outbreak row.
        official_kind = 0 if signal.get("official_recall") else (1 if signal.get("outbreak") else 2)
        recall_date = ""
        if signal.get("official_recall"):
            recall_date = signal["official_recall"].get("recall_date") or ""
        return (
            tier_rank,
            official_kind,
            has_outbreak,
            has_recall,
            spike_ratio,
            # Newer recall dates first (ISO strings sort lexicographically).
            f"_{recall_date}",
            # Unofficial: multi-source patterns first, then by volume.
            -signal.get("unique_source_ids", 0) if tier == "unofficial" else 0,
            -signal.get("geographic_count", 0) if tier == "unofficial" else 0,
            -signal.get("internal_strength", 0),
            -signal.get("report_count", 0),
        )

    return sorted(cards, key=sort_key)
