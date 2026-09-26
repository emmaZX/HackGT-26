from .models import Post, Product, Report
from .security import iso, public_location


def product_card(product: Product, signal: dict, local: bool = False) -> dict:
    tags = _tags(signal, local)
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
    }


def product_detail(product: Product, signal: dict, reports: list[Report], posts: list[Post]) -> dict:
    return {
        **product_card(product, signal, local=False),
        "official_status": _official_status(signal),
        "reports": [report_card(report) for report in reports],
        "posts": [post_card(post) for post in posts],
        "disclaimer": (
            "Community signals are not proof that a product is unsafe. "
            "They identify patterns worth investigating. "
            "No official recall does not mean a product is safe."
        ),
    }


def report_card(report: Report) -> dict:
    location = public_location(report.location_label, report.latitude, report.longitude)
    return {
        "id": report.id,
        "source": report.source,
        "source_url": report.source_url,
        "title": report.title,
        "text": report.text,
        "excerpt": report.excerpt or report.text[:220],
        "created_at": iso(report.created_at),
        "location": location,
        "is_user_generated": report.is_user_generated,
        "is_duplicate": report.is_duplicate,
        "independence_weight": report.independence_weight,
        "display_name": report.display_name,
        "issues": [
            {"slug": link.issue.slug, "name": link.issue.name, "icon": link.issue.icon}
            for link in report.issue_links
        ],
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
        return {
            "state": "official_recall",
            "headline": "Official recall",
            "detail": f"Recalled by {recall['agency']} because of {recall['hazard'].lower()}.",
            "recall": recall,
        }
    return {
        "state": "no_official_recall",
        "headline": "No official recall found",
        "detail": "No official recall currently identified in our connected sources. That is not a safety determination.",
        "recall": None,
    }


def _tags(signal: dict, local: bool) -> list[str]:
    tags: list[str] = []
    key = signal.get("severity_key")
    mapping = {
        "official_recall": "OFFICIAL RECALL",
        "strong_emerging_signal": "STRONG SIGNAL",
        "emerging_signal": "EMERGING SIGNAL",
        "elevated_reports": "ELEVATED REPORTS",
        "limited_reports": "LIMITED REPORTS",
    }
    if key in mapping:
        tags.append(mapping[key])
    if local:
        tags.append("LOCAL")
    elif signal.get("official_recall"):
        tags.append("NATIONWIDE")
    if signal.get("velocity_percent") and signal["velocity_percent"] >= 80:
        tags.append("TRENDING")
    if signal.get("official_recall"):
        tags.append(signal["official_recall"]["agency"])
    return tags
