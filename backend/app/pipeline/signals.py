from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta

from sqlalchemy.orm import Session, joinedload

from ..models import Product, Recall, Report, ReportIssue
from .cluster import cluster_strength

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
        .options(joinedload(Report.issue_links).joinedload(ReportIssue.issue))
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

    texts = [r.text for r in reports if not r.is_duplicate]
    semantic = cluster_strength(texts)

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
    official = recalls[0] if recalls else None

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
    geography = [{"label": label, "count": count} for label, count in geo_buckets.most_common(8)]

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
    )

    return {
        "signal_type": "official_recall" if official else key,
        "severity_key": "official_recall" if official else key,
        "severity_label": "Official recall" if official else title,
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
        "components": {
            "recent_report_velocity": round(velocity_component, 3),
            "source_diversity": round(source_div, 3),
            "semantic_cluster_strength": round(semantic, 3),
            "geographic_distribution": round(geo_component, 3),
            "deviation_from_historical_baseline": round(baseline_component, 3),
            "independence": round(independence_component, 3),
        },
    }


def _explain(*, title, recent_count, previous_count, independent, total, geo_count, issues, official) -> str:
    if official:
        return (
            f"An official recall is on record from {official.agency}. "
            "Community reports are shown separately as supporting context, not as proof of the recall."
        )
    top = issues[0]["name"] if issues else "the same problem"
    if previous_count:
        ratio = recent_count / max(previous_count, 1)
        return (
            f"{title} because about {int(round(independent))} independent reports "
            f"(of {total} total) describe {top.lower()}. "
            f"Reports increased {ratio:.1f}× over the previous 7 days"
            + (f", across {geo_count} places." if geo_count else ".")
        )
    if total == 0:
        return "No community reports are associated with this product in connected sources yet."
    return (
        f"{title} based on {int(round(independent))} independent-looking reports "
        f"describing {top.lower()}. This is a pattern in public and community reports, "
        "not a determination that the product is unsafe."
    )


def _serialize_recall(recall: Recall) -> dict:
    return {
        "agency": recall.agency,
        "recall_date": recall.recall_date.date().isoformat(),
        "reason": recall.reason,
        "hazard": recall.hazard,
        "source_url": recall.source_url,
        "nationwide": recall.nationwide,
    }


def feed_cards(db: Session, visitor_city: str | None = None) -> list[dict]:
    cards = []
    for product in db.query(Product).all():
        signal = compute_signal(db, product)
        if signal["severity_key"] == "no_significant_signal" and not signal["official_recall"]:
            continue
        local = False
        if visitor_city:
            local = any(visitor_city.lower() == g["label"].lower() for g in signal["geography"])
        cards.append({"product": product, "signal": signal, "local": local})
    rank = {
        "official_recall": 0,
        "strong_emerging_signal": 1,
        "emerging_signal": 2,
        "elevated_reports": 3,
        "limited_reports": 4,
    }
    cards.sort(key=lambda item: (rank.get(item["signal"]["severity_key"], 9), -item["signal"]["report_count"]))
    return cards
