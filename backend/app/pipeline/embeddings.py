from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter

from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Embedding, Report

TOKEN_RE = re.compile(r"[a-z0-9]{3,}")
STOP = {
    "the", "and", "for", "that", "this", "with", "from", "have", "has", "was",
    "were", "been", "after", "about", "just", "like", "when", "then", "they",
    "them", "your", "mine", "into", "over", "only", "very", "also", "than",
}


def tokenize(text: str) -> list[str]:
    return [tok for tok in TOKEN_RE.findall(text.lower()) if tok not in STOP]


def lexical_vector(text: str) -> list[float]:
    tokens = tokenize(text)
    counts = Counter(tokens)
    if not counts:
        return [0.0]
    vocab = sorted(counts)
    raw = [float(counts[token]) for token in vocab]
    norm = math.sqrt(sum(v * v for v in raw)) or 1.0
    # Store a portable hashed bag so two similar texts share dimensions.
    dims = [0.0] * 256
    for token, weight in counts.items():
        bucket = int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16) % 256
        dims[bucket] += weight / norm
    length = math.sqrt(sum(v * v for v in dims)) or 1.0
    return [v / length for v in dims]


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    n = min(len(a), len(b))
    dot = sum(a[i] * b[i] for i in range(n))
    na = math.sqrt(sum(x * x for x in a[:n])) or 1.0
    nb = math.sqrt(sum(x * x for x in b[:n])) or 1.0
    return max(0.0, min(1.0, dot / (na * nb)))


def embed_text(text: str) -> tuple[list[float], str]:
    """
    Prefer a hosted embedding model when a key is present.
    Fall back to a local hashed bag-of-words so the demo never depends on a vendor.
    """
    settings = get_settings()
    if settings.openai_api_key:
        try:
            return _openai_embed(text, settings.openai_api_key, settings.openai_embedding_model), settings.openai_embedding_model
        except Exception:
            pass
    return lexical_vector(text), "lexical-v1"


def _openai_embed(text: str, api_key: str, model: str) -> list[float]:
    import httpx

    response = httpx.post(
        "https://api.openai.com/v1/embeddings",
        headers={"Authorization": f"Bearer {api_key}"},
        json={"model": model, "input": text[:8000]},
        timeout=20,
    )
    response.raise_for_status()
    return response.json()["data"][0]["embedding"]


def store_embedding(db: Session, report: Report) -> Embedding:
    vector, model = embed_text(f"{report.title or ''} {report.text}")
    existing = db.query(Embedding).filter(Embedding.report_id == report.id).one_or_none()
    payload = json.dumps(vector)
    if existing:
        existing.vector_json = payload
        existing.model = model
        return existing
    row = Embedding(report_id=report.id, vector_json=payload, model=model)
    db.add(row)
    return row


def load_vector(row: Embedding | None) -> list[float]:
    if not row:
        return []
    return json.loads(row.vector_json)


def similar_reports(db: Session, text: str, product_id: int | None = None, limit: int = 8) -> list[tuple[Report, float]]:
    query_vec, _ = embed_text(text)
    q = db.query(Report, Embedding).join(Embedding, Embedding.report_id == Report.id)
    if product_id:
        q = q.filter(Report.product_id == product_id)
    scored: list[tuple[Report, float]] = []
    for report, embedding in q.all():
        scored.append((report, cosine(query_vec, load_vector(embedding))))
    scored.sort(key=lambda item: item[1], reverse=True)
    return [item for item in scored if item[1] >= 0.35][:limit]
