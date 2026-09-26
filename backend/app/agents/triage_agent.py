"""Agent 4 — Semantic triage: first-person complaint vs recall coverage vs noise."""

from __future__ import annotations

import json
import re
from datetime import datetime

from ..config import get_settings

# Strong first-person / outbreak language.
COMPLAINT_PATTERNS = [
    r"\b(threw up|throwing up|vomit(?:ing|ed)?|diarrhea|diarrh[o]?ea)\b",
    r"\b(food poisoning|got sick|violently ill|emergency room|ER|urgent care)\b",
    r"\b(batch|lot\s*#?|lot code|use[- ]by|best[- ]by)\b",
    r"\b(three people|whole family|my kids|household|everyone who ate|both of us)\b",
    r"\b(i|we|my|our)\b.{0,40}\b(sick|vomiting|diarrhea|poisoning)\b",
]

RECALL_COVERAGE_PATTERNS = [
    r"\b(expands? recall|announced a recall|issued a recall|recalling firm|voluntary recall)\b",
    r"\b(fda|usda|cpsc|fsai|food safety authority)\b.{0,40}\brecall\b",
    r"\b(recalled (dozens|thousands|products|lots|units))\b",
    r"\b(press release|recalling firm|enforcement report|food alerts?)\b",
    r"\b(recall of various|ready[- ]meals? due to|possible presence of)\b",
]

NOISE_PATTERNS = [
    r"\b(taste[sd]? (gross|bad|weird|off)|never buying|waste of money|overpriced)\b",
    r"\b(recipe|how to make|ingredients list|nutrition facts)\b",
    r"\b(unboxing|haul|sponsored|affiliate)\b",
    r"\b(why do(?:es)?|causes diarrhea|digestive issues|side effects)\b",
    r"\b(how to tell if|warning signs|is .+ bad|spoiled protein|gone bad)\b",
    r"\b(answered!|explore this topic|share this article|diet & nutrition)\b",
    r"\b(author manuscript|published in final|clin infect dis|doi:)\b",
    r"\b(can (?:you|i) (?:get|drink|eat)|unraveling the truth|experts? explain|myths? (?:vs|about))\b",
    r"\b(fridge for a week|left out overnight|shelf[- ]life|storage guide)\b",
    r"\b(last year|a year ago|years ago|months later|update\s*[:—-].{0,40}year)\b",
]

# Years clearly outside a ~90-day window relative to "now" (2026 → anything ≤2025).
OLD_YEAR_RE = re.compile(r"\b(20(?:1\d|2[0-5]))\b")

REGULATOR_HOST_NEEDLES = (
    "fda.gov",
    "cdc.gov",
    "fsis.usda.gov",
    "foodsafety.gov",
    "fsai.ie",
    "food.gov.uk",
    "canada.ca",
    "inspection.gc.ca",
    "who.int",
    "efsa.europa.eu",
)


def triage_complaint(
    *,
    text: str,
    title: str | None,
    product_hint: str,
    url: str | None = None,
    has_official_recall: bool = False,
    recency_days: int | None = None,
) -> dict:
    """
    Classify a page as:
      first_person_complaint | recall_coverage | noise | uncertain
    """
    blob = f"{title or ''}\n{text[:3500]}"
    settings = get_settings()
    days = recency_days if recency_days is not None else settings.discovery_recency_days

    # Regulator / official recall hosts are never "neighbor evidence".
    if url and _is_regulator_url(url):
        return {
            "label": "recall_coverage",
            "score": 0.95,
            "reason": "Official regulator / food-safety authority page.",
            "method": "url-host",
            "stale": False,
        }

    heuristic = _heuristic_triage(blob, has_official_recall=has_official_recall, recency_days=days)
    llm = _llm_triage(blob, product_hint, url)
    if llm:
        # Never let LLM upgrade noise/uncertain SEO into complaints.
        if heuristic["label"] in {"noise", "uncertain"} and llm["label"] in {
            "first_person_complaint",
            "signal",
        }:
            return {**heuristic, "method": "heuristic+llm-override"}
        if heuristic["label"] == "noise" and llm["label"] == "uncertain":
            return {**heuristic, "method": "heuristic+llm-override"}
        if heuristic["label"] == "first_person_complaint" and llm["label"] == "noise":
            return {**heuristic, "method": "heuristic+llm-override"}
        if heuristic["label"] == "recall_coverage" and llm["label"] == "first_person_complaint":
            return {**heuristic, "method": "heuristic+llm-override"}
        # Prefer freshness from heuristic when LLM misses "last year" memoir.
        if heuristic.get("stale") and llm["label"] == "first_person_complaint":
            return {
                "label": "noise",
                "score": 0.2,
                "reason": "Looks like an older personal story, not a fresh emerging cluster.",
                "method": "heuristic+stale-override",
                "stale": True,
            }
        return llm
    return heuristic


def should_ingest_as_internet_evidence(result: dict, *, has_official_recall: bool) -> bool:
    """Only recent first-person complaints count as internet evidence."""
    del has_official_recall  # coverage is never ingested as neighbor evidence
    label = result.get("label")
    score = float(result.get("score") or 0)
    if result.get("stale"):
        return False
    if label == "first_person_complaint" and score >= 0.42:
        return True
    return False


def is_recall_coverage(result: dict) -> bool:
    return result.get("label") == "recall_coverage" and float(result.get("score") or 0) >= 0.4


def _is_regulator_url(url: str) -> bool:
    try:
        from urllib.parse import urlparse

        host = (urlparse(url).hostname or "").lower()
        host = host[4:] if host.startswith("www.") else host
    except Exception:
        return False
    return any(host == n or host.endswith("." + n) for n in REGULATOR_HOST_NEEDLES)


# Back-compat for older callers
def is_signal(result: dict, min_score: float = 0.45) -> bool:
    if result.get("label") == "first_person_complaint":
        return float(result.get("score") or 0) >= min_score
    if result.get("label") == "signal":
        return float(result.get("score") or 0) >= min_score
    return False


def _heuristic_triage(blob: str, *, has_official_recall: bool, recency_days: int) -> dict:
    del has_official_recall
    lowered = blob.lower()
    complaint_hits = sum(1 for pat in COMPLAINT_PATTERNS if re.search(pat, lowered, re.I))
    coverage_hits = sum(1 for pat in RECALL_COVERAGE_PATTERNS if re.search(pat, lowered, re.I))
    noise_hits = sum(1 for pat in NOISE_PATTERNS if re.search(pat, lowered, re.I))
    stale = _looks_stale(blob, recency_days)

    if coverage_hits >= 1 and complaint_hits < 2:
        return {
            "label": "recall_coverage",
            "score": 0.7 if not stale else 0.55,
            "reason": "Looks like press/FDA recall coverage, not a first-person illness report.",
            "method": "heuristic",
            "stale": stale,
        }

    # SEO explainers ("why do shakes give me diarrhea") mention illness words —
    # still noise unless multi-person / batch cluster language is present.
    if noise_hits and complaint_hits < 2:
        return {
            "label": "noise",
            "score": 0.12,
            "reason": "Ordinary taste/quality or educational content without illness cluster detail.",
            "method": "heuristic",
            "stale": stale,
        }

    if complaint_hits >= 2 or (complaint_hits >= 1 and ("batch" in lowered or "lot" in lowered)):
        if stale:
            return {
                "label": "noise",
                "score": 0.2,
                "reason": "Older personal story / dated year — not fresh emerging chatter.",
                "method": "heuristic",
                "stale": True,
            }
        return {
            "label": "first_person_complaint",
            "score": max(0.55 if complaint_hits >= 2 else 0.48, min(1.0, 0.22 * complaint_hits)),
            "reason": f"Matched {complaint_hits} first-person illness/cluster patterns.",
            "method": "heuristic",
            "stale": False,
        }

    if complaint_hits == 1:
        return {
            "label": "uncertain",
            "score": 0.35,
            "reason": "Weak illness language — not enough for emerging evidence.",
            "method": "heuristic",
            "stale": stale,
        }

    return {
        "label": "noise",
        "score": 0.1,
        "reason": "No first-person illness, batch, or multi-person complaint language.",
        "method": "heuristic",
        "stale": stale,
    }


def _looks_stale(blob: str, recency_days: int) -> bool:
    """True if text looks like a year-old memoir or pre-dates the recency window."""
    lowered = blob.lower()
    if re.search(r"\b(last year|a year ago|years ago|two years ago)\b", lowered):
        return True
    years = [int(y) for y in OLD_YEAR_RE.findall(blob)]
    if not years:
        return False
    current = datetime.utcnow().year
    # Any year strictly before the current calendar year is outside a ~90-day window.
    if max(years) < current:
        return True
    del recency_days
    return False


def _llm_triage(blob: str, product_hint: str, url: str | None) -> dict | None:
    settings = get_settings()
    if not settings.gemini_api_key:
        return None
    try:
        import httpx
    except Exception:
        return None

    prompt = (
        "You are the Triage agent for Recall Me Maybe.\n"
        "Classify this page as ONE of:\n"
        '- "first_person_complaint": RECENT consumer illness report (this year / last ~90 days; vomiting, multi-person, batch/lot).\n'
        '- "recall_coverage": news/press/regulator page about an official recall.\n'
        '- "noise": taste gripes, recipes, SEO, or stories about illness from last year / older.\n'
        '- "uncertain": unclear.\n'
        "If the story happened last year or earlier, label noise with stale=true.\n\n"
        "Return ONLY JSON: "
        '{"label":"...","score":0-1,"reason":"...","stale":true|false}\n'
        f"Product: {product_hint}\nURL: {url or ''}\n\nPAGE:\n{blob[:2800]}"
    )
    try:
        response = httpx.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{settings.gemini_model}:generateContent",
            headers={"x-goog-api-key": settings.gemini_api_key},
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=30,
        )
        if response.status_code >= 400:
            return None
        text = ""
        for candidate in response.json().get("candidates", []):
            for part in candidate.get("content", {}).get("parts", []):
                text += part.get("text") or ""
        match = re.search(r"\{[\s\S]*\}", text)
        if not match:
            return None
        data = json.loads(match.group(0))
        label = str(data.get("label") or "uncertain").lower()
        allowed = {"first_person_complaint", "recall_coverage", "noise", "uncertain", "signal"}
        if label not in allowed:
            label = "uncertain"
        if label == "signal":
            label = "first_person_complaint"
        return {
            "label": label,
            "score": float(data.get("score") or 0.5),
            "reason": str(data.get("reason") or "")[:240],
            "method": "gemini",
            "stale": bool(data.get("stale")),
        }
    except Exception:
        return None
