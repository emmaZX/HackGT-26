from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import Report
from .embeddings import cosine, embed_text, lexical_vector, load_vector, store_embedding

# Near-duplicate threshold: quoting or reposting the same incident.
DUPLICATE_THRESHOLD = 0.92
# Same product-issue cluster, different wording.
RELATED_THRESHOLD = 0.38


def attach_and_dedupe(db: Session, report: Report) -> Report:
    """
    Embed the report, then mark likely duplicates so a repost does not count
    as a second independent incident.
    """
    store_embedding(db, report)
    db.flush()
    query_vec, _ = embed_text(f"{report.title or ''} {report.text}")

    siblings = (
        db.query(Report)
        .filter(Report.product_id == report.product_id, Report.id != report.id)
        .all()
    )
    best_id = None
    best_score = 0.0
    for sibling in siblings:
        score = cosine(query_vec, load_vector(sibling.embedding))
        if score > best_score:
            best_score = score
            best_id = sibling.id

    if best_id and best_score >= DUPLICATE_THRESHOLD:
        report.is_duplicate = True
        report.duplicate_of_id = best_id
        report.independence_weight = 0.15
    elif best_id and best_score >= 0.78:
        report.is_duplicate = False
        report.duplicate_of_id = best_id
        report.independence_weight = 0.55
    else:
        report.is_duplicate = False
        report.independence_weight = 1.0
    return report


def relatedness(text_a: str, text_b: str) -> float:
    vec_a, _ = embed_text(text_a)
    vec_b, _ = embed_text(text_b)
    return cosine(vec_a, vec_b)


def cluster_strength(texts: list[str]) -> float:
    """
    Average pairwise similarity among report texts.
    Uses local lexical vectors only — never OpenAI — so /api/feed stays fast.
    """
    if len(texts) < 2:
        return 0.15 if texts else 0.0
    vectors = [lexical_vector(text) for text in texts[:40]]
    total = 0.0
    pairs = 0
    for i, left in enumerate(vectors):
        for right in vectors[i + 1 :]:
            total += cosine(left, right)
            pairs += 1
    mean = total / max(pairs, 1)
    return min(1.0, mean)
