from .models import Post, Product, Report
from .security import iso, public_location


def product_card(product: Product, signal: dict, local: bool = False) -> dict:
    tags = _tags(signal, local)
    evidence = _evidence_links(product, signal)
    return {
        "id": product.id,
        "slug": product.slug,
        "brand": product.brand,
        "name": product.name,
        "model": product.model,
        "category": product.category,
        "upc": product.upc,
        "manufacturer": product.manufacturer,
        "summary": product.summary,
        "image_url": product.image_url,
        "signal": signal,
        "local": local,
        "tags": tags,
        "source_tier": signal.get("source_tier") or "unofficial",
        "evidence_count": len(evidence),
        "evidence": evidence,
    }


def _evidence_links(product: Product, signal: dict, reports: list | None = None) -> list[dict]:
    """Linked public URLs for the card — never invent."""
    if reports is None:
        reports = getattr(product, "reports", None) or []
    out: list[dict] = []
    seen: set[str] = set()
    for report in reports:
        url = (report.source_url or "").strip()
        if not url or url in seen:
            continue
        if report.is_duplicate:
            continue
        seen.add(url)
        out.append(
            {
                "source_url": url,
                "source": report.source,
                "observed_at": iso(report.incident_date) if report.incident_date else None,
                "excerpt": (report.excerpt or report.text or "")[:180],
            }
        )
    # Official recall URL if present and not already listed
    recall = signal.get("official_recall") or {}
    rurl = (recall.get("source_url") or "").strip()
    if rurl and rurl not in seen:
        out.insert(
            0,
            {
                "source_url": rurl,
                "source": recall.get("agency") or "official",
                "observed_at": recall.get("recall_date"),
                "excerpt": recall.get("hazard") or "",
            },
        )
    return out[:12]


def product_detail(product: Product, signal: dict, reports: list[Report], posts: list[Post]) -> dict:
    tier = signal.get("source_tier") or "unofficial"
    if tier == "caers":
        disclaimer = (
            "CAERS entries are FDA-hosted adverse event reports — not an official recall. "
            "Reports are largely voluntary and unverified; they do not prove the product caused harm."
        )
    elif tier == "official":
        disclaimer = (
            "Official notices come from Ongoing FDA/FSIS recalls or active FDA outbreak investigations. "
            "Outbreak watches are not the same as a product recall unless a recall was initiated."
        )
    else:
        disclaimer = (
            "Community signals are not proof that a product is unsafe. "
            "They identify patterns worth investigating — often before an official recall exists. "
            "No official recall does not mean a product is safe."
        )
    # Attach reports so product_card / _evidence_links can include official + community URLs.
    product.reports = reports
    card = product_card(product, signal, local=False)
    card["evidence"] = _evidence_links(product, signal, reports=reports)
    card["evidence_count"] = len(card["evidence"])
    return {
        **card,
        "official_status": _official_status(signal),
        "reports": [report_card(report) for report in reports],
        "posts": [post_card(post) for post in posts],
        "disclaimer": disclaimer,
    }


def report_card(report: Report) -> dict:
    location = public_location(report.location_label, report.latitude, report.longitude)
    observed = report.incident_date or (None if not report.is_user_generated else report.created_at)
    conf = None
    method = None
    if report.extra_json:
        try:
            import json

            meta = json.loads(report.extra_json)
            conf = meta.get("confidence")
            method = meta.get("method")
        except Exception:
            pass
    if conf is None and report.issue_links:
        conf = max((link.confidence for link in report.issue_links), default=None)
    return {
        "id": report.id,
        "source": report.source,
        "source_url": report.source_url,
        "title": report.title,
        "text": report.text,
        "excerpt": report.excerpt or report.text[:220],
        "created_at": iso(report.created_at),
        "incident_date": iso(observed) if observed else None,
        "observed_at": iso(observed) if observed else None,
        "confidence": conf,
        "confidence_method": method,
        "location": location,
        "is_user_generated": report.is_user_generated,
        "is_duplicate": report.is_duplicate,
        "independence_weight": report.independence_weight,
        "display_name": report.display_name,
        "issues": [
            {"slug": link.issue.slug, "name": link.issue.name, "icon": link.issue.icon}
            for link in report.issue_links
        ],
        "product_slug": report.product.slug if getattr(report, "product", None) else None,
        "product_name": report.product.name if getattr(report, "product", None) else None,
    }


def post_card(post: Post) -> dict:
    return {
        "id": post.id,
        "product_id": post.product_id,
        "display_name": post.display_name,
        "title": post.title,
        "body": post.body,
        "location_label": post.location_label,
        "created_at": iso(post.created_at),
        "like_count": len(post.likes),
        "liked_by": [like.display_name for like in post.likes],
        "liked_by_subs": [like.user_sub for like in post.likes if like.user_sub],
        "comments": [
            {
                "id": comment.id,
                "display_name": comment.display_name,
                "body": comment.body,
                "created_at": iso(comment.created_at),
            }
            for comment in sorted(post.comments, key=lambda c: c.created_at)
        ],
    }


def _official_status(signal: dict) -> dict:
    recall = signal.get("official_recall")
    if recall:
        # Never surface terminated / historical notices — only Ongoing.
        phase = recall.get("phase") or "ongoing"
        if phase == "past":
            return {
                "state": "no_official_recall",
                "headline": "No official recall found yet",
                "detail": (
                "No Ongoing FDA/FSIS recall is attached right now. "
                "That does not mean the product is safe — "
                "and it does not mean early internet clusters are proof of harm."
                ),
                "recall": None,
            }
        if signal.get("internet_before_official"):
            return {
                "state": "official_recall",
                "headline": "Official recall — after the internet noticed",
                "detail": (
                    f"Community and public web reports were already clustering before the "
                    f"{recall['agency']} notice on {recall['recall_date']}. "
                    f"Official reason: {recall['hazard']}."
                ),
                "recall": recall,
            }
        return {
            "state": "official_recall",
            "headline": "Official recall on record",
            "detail": f"Recalled by {recall['agency']} because of {recall['hazard'].lower()}.",
            "recall": recall,
        }
    return {
        "state": "no_official_recall",
        "headline": "No official recall found yet",
        "detail": (
            "No FDA/FSIS/CPSC recall is attached right now. That does not mean the product is safe — "
            "and it does not mean early internet clusters are proof of harm."
        ),
        "recall": None,
    }


def _tags(signal: dict, local: bool) -> list[str]:
    tags: list[str] = []
    key = signal.get("severity_key")
    mapping = {
        "strong_emerging_signal": "STRONG SIGNAL",
        "emerging_signal": "EMERGING SIGNAL",
        "elevated_reports": "ELEVATED REPORTS",
        "limited_reports": "LIMITED REPORTS",
    }
    tier = signal.get("source_tier") or "unofficial"
    if signal.get("outbreak"):
        tags.append("OUTBREAK WATCH")
    if signal.get("spike") and signal["spike"].get("is_spike"):
        tags.append("CAERS SPIKE")
    if signal.get("internet_before_official"):
        tags.append("INTERNET FIRST")
    if key in mapping and tier == "unofficial":
        tags.append(mapping[key])
    if signal.get("official_recall"):
        agency = (signal["official_recall"].get("agency") or "").upper()
        phase = signal["official_recall"].get("phase") or "ongoing"
        if phase == "past":
            pass  # Never tag past/terminated recalls.
        elif agency == "FDA":
            tags.append("FDA RECALL")
        elif agency == "CPSC":
            tags.append("CPSC RECALL")
        elif "FSIS" in agency or agency.startswith("USDA"):
            tags.append("OFFICIAL RECALL")
            tags.append("USDA-FSIS")
        else:
            tags.append("OFFICIAL RECALL")
            if agency and agency not in tags:
                tags.append(agency)
    if tier == "unofficial" and "UNOFFICIAL" not in tags and not signal.get("official_recall"):
        tags.append("UNOFFICIAL")
    if local:
        tags.append("LOCAL")
    if signal.get("velocity_percent") and signal["velocity_percent"] >= 80:
        tags.append("TRENDING")
    return tags
