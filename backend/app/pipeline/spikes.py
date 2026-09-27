"""
Deterministic CAERS velocity / spike scoring. No LLM in this module.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from ..config import get_settings
from ..grok import ai_text, grok_available
from ..models import Report


def score_caers_spike(
    db: Session,
    product_id: int,
    *,
    now: datetime | None = None,
    window_days: int = 14,
    baseline_weeks: int = 6,
    reports: list[Report] | None = None,
) -> dict:
    """
    Compare recent CAERS report count to a prior weekly baseline.

    Returns:
      recent_count, baseline_weekly, velocity_ratio, window_days, is_spike
    """
    settings = get_settings()
    now = now or datetime.utcnow()
    min_n = settings.caers_spike_min_reports
    velocity_floor = settings.caers_spike_velocity

    if reports is None:
        reports = (
            db.query(Report)
            .filter(Report.product_id == product_id, Report.source == "caers")
            .all()
        )
    else:
        reports = [r for r in reports if r.source == "caers"]
    # openFDA CAERS often lags wall-clock time — anchor velocity to the newest
    # report date so spikes are visible in the ingested distribution.
    dated = [r.created_at for r in reports if r.created_at]
    now = now or datetime.utcnow()
    if dated:
        newest = max(dated)
        if (now - newest).days > 21:
            now = newest

    recent_start = now - timedelta(days=window_days)
    baseline_end = recent_start
    baseline_start = baseline_end - timedelta(weeks=baseline_weeks)

    recent = [r for r in reports if r.created_at and r.created_at >= recent_start]
    baseline = [
        r
        for r in reports
        if r.created_at and baseline_start <= r.created_at < baseline_end
    ]
    recent_count = len(recent)
    baseline_weekly = len(baseline) / max(baseline_weeks, 1)
    velocity_ratio = recent_count / max(baseline_weekly, 1.0)
    is_spike = recent_count >= min_n and velocity_ratio >= velocity_floor

    return {
        "recent_count": recent_count,
        "baseline_weekly": round(baseline_weekly, 2),
        "velocity_ratio": round(velocity_ratio, 2),
        "window_days": window_days,
        "is_spike": is_spike,
    }


def summarize_caers_spike(product_label: str, sample_texts: list[str]) -> str:
    """Gemini summary for a confirmed spike only. Falls back to a factual template."""
    settings = get_settings()
    samples = [t.strip() for t in sample_texts if t and t.strip()][:8]
    fallback = (
        f"CAERS (FDA-hosted adverse event) reports for {product_label} rose above "
        f"the recent baseline. This is not an official recall — reports are unverified "
        f"and do not prove the product caused harm."
    )
    if not (settings.gemini_api_key or grok_available()) or not samples:
        return fallback[:500]

    try:
        import httpx

        joined = "\n---\n".join(s[:400] for s in samples)
        prompt = (
            "You summarize FDA CAERS food adverse-event spikes for a consumer safety feed. "
            "Be factual and cautious. Do NOT call this a recall. Do NOT assert causation. "
            "Mention that CAERS reports are voluntary/unverified. "
            "Write 2 short sentences. Product: "
            f"{product_label}\n\nSample report excerpts:\n{joined}"
        )
        raw = (ai_text(prompt, timeout=30) or "").strip()
        return (raw or fallback)[:500]
    except Exception:
        return fallback[:500]
