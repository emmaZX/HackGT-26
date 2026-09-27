"""
Grok case summary for a product page: 2-3 plain sentences on what people are describing and
why the reports look related, with every claim tied to the report IDs it came from.

GET /api/products/{slug}/summary
  → {"summary": str, "cited_ids": [int], "report_count": int, "model": str} or {"summary": null}

- Generated once per product and cached (memory + data/case_summaries.json). It regenerates
  only when the product's set of reports changes, so page views don't cost credit.
- Cited IDs are checked against the reports actually sent; invented IDs are dropped.
- Needs at least 2 reports; with fewer there's nothing to relate.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from pathlib import Path

from fastapi import APIRouter

from .database import SessionLocal
from .grok import DEFAULT_TEXT_MODEL, grok_available, output_text, respond
from .models import Product, Report

logger = logging.getLogger(__name__)
router = APIRouter()

CACHE_FILE = Path(__file__).resolve().parents[1] / "data" / "case_summaries.json"
MAX_REPORTS = 12
_cache: dict[str, dict] = {}

PROMPT = """You write a short case summary for a food safety app. Below are public reports about ONE product.

Write 2-3 plain sentences for a worried shopper:
- what people describe (symptoms, what they found, timing), and
- why these reports look related, or say plainly if they don't.
Cite the reports you rely on with their IDs in square brackets, like [12] or [12, 15].
Rules: only use what the reports say. Do not say the product caused anything. Do not diagnose.
Do not mention recalls unless a report does. Do not invent details.

Answer with ONLY JSON: {{"summary": "...", "cited_ids": [numbers]}}

Product: {product}

Reports:
{reports}"""


def _load() -> None:
    if _cache or not CACHE_FILE.exists():
        return
    try:
        _cache.update(json.loads(CACHE_FILE.read_text()))
    except Exception:
        pass


def _save() -> None:
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(json.dumps(_cache))
    except Exception:
        logger.warning("Could not write case summary cache")


def _signature(reports: list[Report]) -> str:
    return hashlib.sha1(",".join(str(r.id) for r in sorted(reports, key=lambda r: r.id)).encode()).hexdigest()


def generate(product: Product, reports: list[Report]) -> dict | None:
    lines = []
    for r in reports[:MAX_REPORTS]:
        when = (r.incident_date or r.created_at)
        text = re.sub(r"\s+", " ", (r.excerpt or r.text or ""))[:400]
        lines.append(f"[{r.id}] ({r.source}{', ' + when.strftime('%Y-%m-%d') if when else ''}) {text}")
    label = product.name if not product.brand or product.brand == "Unknown" else f"{product.brand} {product.name}"
    response = respond(
        PROMPT.format(product=label, reports="\n".join(lines)),
        timeout=60,
        model=os.getenv("XAI_TEXT_MODEL", DEFAULT_TEXT_MODEL),
    )
    text = output_text(response)
    match = re.search(r"\{[\s\S]*\}", text or "")
    if not match:
        return None
    data = json.loads(match.group(0))
    summary = str(data.get("summary") or "").strip()
    if not summary:
        return None
    sent = {r.id for r in reports[:MAX_REPORTS]}
    cited = [int(i) for i in data.get("cited_ids") or [] if str(i).isdigit() and int(i) in sent]
    # Also drop any [id] in the text that wasn't one of the reports we sent
    summary = re.sub(
        r"\[([\d,\s]+)\]",
        lambda m: (lambda ids: f"[{', '.join(ids)}]" if ids else "")(
            [i.strip() for i in m.group(1).split(",") if i.strip().isdigit() and int(i) in sent]
        ),
        summary,
    ).strip()
    cited = sorted(set(cited) | {int(i) for i in re.findall(r"\d+", " ".join(re.findall(r"\[[\d,\s]+\]", summary)))})
    return {"summary": summary[:900], "cited_ids": cited, "report_count": len(reports), "model": os.getenv("XAI_TEXT_MODEL", DEFAULT_TEXT_MODEL)}


@router.get("/api/products/{slug}/summary")
def product_summary(slug: str):
    _load()
    with SessionLocal() as db:
        product = db.query(Product).filter(Product.slug == slug).one_or_none()
        if not product:
            return {"summary": None}
        reports = (
            db.query(Report)
            .filter(Report.product_id == product.id, Report.is_duplicate.is_(False))
            .order_by(Report.created_at.desc())
            .all()
        )
        reports = [r for r in reports if (r.text or r.excerpt)]
        if len(reports) < 2 or not grok_available():
            return {"summary": None}
        sig = _signature(reports)
        cached = _cache.get(slug)
        if cached and cached.get("sig") == sig:
            return {k: v for k, v in cached.items() if k != "sig"}
        try:
            result = generate(product, reports)
        except Exception as exc:
            logger.warning("Case summary failed for %s: %s", slug, str(exc)[:120])
            result = None
        if not result:
            return {"summary": None}
        _cache[slug] = {**result, "sig": sig}
        _save()
        return result
