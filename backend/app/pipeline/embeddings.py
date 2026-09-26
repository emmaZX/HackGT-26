from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter

from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Embedding, Report
from ..openai_http import openai_post

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


def corpus_embedding_model(db: Session) -> str | None:
    row = db.query(Embedding.model).first()
    return row[0] if row else None


def embed_text(text: str, *, force_model: str | None = None) -> tuple[list[float], str]:
    """
    Stay in one vector space. If the database already has lexical embeddings,
    keep using those even when an OpenAI key is present.
    """
    if force_model == "lexical-v1":
        return lexical_vector(text), "lexical-v1"
    settings = get_settings()
    want_openai = force_model not in {None, "lexical-v1"} or (
        force_model is None and bool(settings.openai_api_key)
    )
    if want_openai and settings.openai_api_key:
        try:
            model = force_model or settings.openai_embedding_model
            return _openai_embed(text, settings.openai_api_key, model), model
        except Exception:
            if force_model and force_model != "lexical-v1":
                raise
    return lexical_vector(text), "lexical-v1"


def _openai_embed(text: str, api_key: str, model: str) -> list[float]:
    data = openai_post(
        "/v1/embeddings",
        api_key,
        {"model": model, "input": text[:8000]},
        timeout=20,
    )
    return data["data"][0]["embedding"]


def store_embedding(db: Session, report: Report) -> Embedding:
    vector, model = embed_text(
        f"{report.title or ''} {report.text}",
        force_model=corpus_embedding_model(db),
    )
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
    model = corpus_embedding_model(db) or "lexical-v1"
    query_vec, _ = embed_text(text, force_model=model)
    q = db.query(Report, Embedding).join(Embedding, Embedding.report_id == Report.id)
    if product_id:
        q = q.filter(Report.product_id == product_id)
    scored: list[tuple[Report, float]] = []
    for report, embedding in q.all():
        if embedding.model != model:
            continue
        scored.append((report, cosine(query_vec, load_vector(embedding))))
    scored.sort(key=lambda item: item[1], reverse=True)
    return [item for item in scored if item[1] >= 0.35][:limit]
