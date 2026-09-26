from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta

from sqlalchemy.orm import Session, joinedload

from ..models import Product, Recall, Report, ReportIssue
from .cluster import cluster_strength_from_reports

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
        "components": {
            "recent_report_velocity": round(velocity_component, 3),
            "source_diversity": round(source_div, 3),
            "semantic_cluster_strength": round(semantic, 3),
            "geographic_distribution": round(geo_component, 3),
            "deviation_from_historical_baseline": round(baseline_component, 3),
            "independence": round(independence_component, 3),
        },
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
    # Home feed is food / watchlist first — keep the payload small and fast.
    products = (
        db.query(Product)
        .filter(Product.category == "Food")
        .order_by(Product.id)
        .limit(40)
        .all()
    )
    for product in products:
        signal = compute_signal(db, product)
        if signal["severity_key"] == "no_significant_signal" and not signal["official_recall"]:
            continue
        local = False
        if visitor_city:
            local = any(visitor_city.lower() == g["label"].lower() for g in signal["geography"])
        cards.append({"product": product, "signal": signal, "local": local})

    def sort_key(item: dict) -> tuple:
        signal = item["signal"]
        key = signal["severity_key"]
        official = bool(signal.get("official_recall"))
        emerging = key in {"strong_emerging_signal", "emerging_signal", "elevated_reports"}
        humanish = signal.get("source_diversity", 0) >= 0.2 or signal.get("report_count", 0) >= 3
        # Internet-first: emerging without FDA, then emerging FDA later confirmed,
        # then official-only shelves. Prefer cards that still look human-sourced.
        if emerging and not official:
            tier = 0
        elif emerging and official:
            tier = 1
        elif official:
            tier = 2
        else:
            tier = 3
        before = 0 if signal.get("internet_before_official") else 1
        human = 0 if humanish else 1
        return (tier, human, before, -signal.get("internal_strength", 0), -signal.get("report_count", 0))

    cards.sort(key=sort_key)
    return cards
