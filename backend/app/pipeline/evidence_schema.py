"""
Fail-closed community evidence contract.

Unofficial / open-web reports must carry a real URL + observed_at within the
recency window. No inventing brand/name/city/dates.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field, HttpUrl, ValidationError, field_validator, model_validator

from ..config import get_settings
from .glance_titles import glance_title, is_sensible_product

REGULATOR_HOSTS = (
    "fda.gov",
    "cdc.gov",
    "fsis.usda.gov",
    "usda.gov",
    "foodsafety.gov",
    "accessdata.fda.gov",
)

VAGUE_NAMES = re.compile(
    r"^(prepared\s+chicken|meal[- ]?kit.*|food\s+item|various|unidentified|"
    r"product|item|food|unknown|grocery(\s+(item|foods))?|grocery\s+or\s+supermarket.*|"
    r"got\s+sick.*|what\s+you\s+need.*|prepared\s+foods?|produce|snacks?|"
    r"dairy|meat\s*&\s*poultry|store\s+foods?)$",
    re.I,
)

YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")
# Common date patterns in pages / URLs
DATE_PATTERNS = [
    re.compile(
        r"\b(20\d{2})[-/](0?[1-9]|1[0-2])[-/](0?[1-9]|[12]\d|3[01])\b"
    ),
    re.compile(
        r"\b(0?[1-9]|1[0-2])[-/](0?[1-9]|[12]\d|3[01])[-/](20\d{2})\b"
    ),
    re.compile(
        r"\b(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
        r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|"
        r"Nov(?:ember)?|Dec(?:ember)?)\s+(\d{1,2}),?\s+(20\d{2})\b",
        re.I,
    ),
]

_MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}


class CommunityEvidence(BaseModel):
    """Grounded first-person complaint — persist only if this validates."""

    source_url: HttpUrl
    excerpt: str = Field(min_length=24, max_length=2000)
    brand: str = Field(default="", max_length=120)
    name: str = Field(min_length=3, max_length=180)
    observed_at: datetime
    triage_label: Literal["first_person_complaint"] = "first_person_complaint"
    confidence: float = Field(ge=0.42, le=1.0)
    confidence_method: Literal["heuristic", "gemini", "user"] = "heuristic"
    location_label: str | None = None
    source_host: str = ""

    @field_validator("excerpt")
    @classmethod
    def _strip_excerpt(cls, value: str) -> str:
        return re.sub(r"\s+", " ", (value or "").strip())

    @field_validator("location_label")
    @classmethod
    def _clean_location(cls, value: str | None) -> str | None:
        text = (value or "").strip()
        return text[:160] if text else None

    @model_validator(mode="after")
    def _enforce_contract(self) -> "CommunityEvidence":
        settings = get_settings()
        cutoff = datetime.utcnow() - timedelta(days=max(14, settings.discovery_recency_days))

        host = _host(str(self.source_url))
        object.__setattr__(self, "source_host", host)
        if not host:
            raise ValueError("source_url has no host")
        if _is_regulator(host):
            raise ValueError(f"regulator host not allowed as community evidence: {host}")

        # Compare calendar dates so a publish day on the cutoff boundary is kept.
        if self.observed_at.replace(tzinfo=None).date() < cutoff.date():
            raise ValueError(
                f"observed_at {self.observed_at.date()} older than "
                f"{settings.discovery_recency_days}d cutoff"
            )

        titled = glance_title(brand=self.brand, name=self.name)
        if not titled or not is_sensible_product(titled["brand"], titled["name"]):
            raise ValueError("brand/name failed glance quality gate")
        if VAGUE_NAMES.match(titled["name"].strip()):
            raise ValueError(f"vague product name: {titled['name']}")
        object.__setattr__(self, "brand", titled["brand"] or "Unknown")
        object.__setattr__(self, "name", titled["name"])

        # Ancient years in excerpt are an automatic reject even if publish date is recent.
        if text_has_ancient_year(self.excerpt, cutoff):
            raise ValueError("excerpt references a year before the recency cutoff")

        return self


def validate_community_evidence(payload: dict) -> tuple[CommunityEvidence | None, str | None]:
    """Return (evidence, None) or (None, reason)."""
    try:
        return CommunityEvidence.model_validate(payload), None
    except (ValidationError, ValueError) as exc:
        return None, str(exc)[:240]


def parse_observed_at(
    *,
    text: str = "",
    url: str = "",
    published: datetime | str | None = None,
) -> datetime | None:
    """
    Best-effort observation date. Returns None if unknown — callers must fail closed.
    Never invents "now" as a substitute.
    """
    if isinstance(published, datetime):
        return published.replace(tzinfo=None)
    if isinstance(published, str) and published.strip():
        parsed = _parse_isoish(published.strip())
        if parsed:
            return parsed

    blob = f"{url}\n{text}"
    for pat in DATE_PATTERNS:
        m = pat.search(blob)
        if not m:
            continue
        groups = m.groups()
        try:
            if len(groups) == 3 and groups[0].isdigit() and len(groups[0]) == 4:
                y, mo, d = int(groups[0]), int(groups[1]), int(groups[2])
                return datetime(y, mo, d)
            if len(groups) == 3 and groups[2].isdigit() and len(groups[2]) == 4:
                if groups[0].isdigit():
                    mo, d, y = int(groups[0]), int(groups[1]), int(groups[2])
                    return datetime(y, mo, d)
                mo = _MONTHS.get(groups[0].lower()[:3]) or _MONTHS.get(groups[0].lower())
                if mo:
                    return datetime(int(groups[2]), mo, int(groups[1]))
        except ValueError:
            continue
    return None


def text_has_ancient_year(text: str, cutoff: datetime | None = None) -> bool:
    """True if text mentions a calendar year before the recency window."""
    settings = get_settings()
    if cutoff is None:
        cutoff = datetime.utcnow() - timedelta(days=max(14, settings.discovery_recency_days))
    floor_year = cutoff.year
    for match in YEAR_RE.findall(text or ""):
        year = int(match)
        if year < floor_year:
            return True
    return False


def within_recency(when: datetime | None, *, days: int | None = None) -> bool:
    if when is None:
        return False
    settings = get_settings()
    window = days if days is not None else settings.discovery_recency_days
    cutoff = datetime.utcnow() - timedelta(days=max(14, window))
    return when.replace(tzinfo=None).date() >= cutoff.date()


def source_label_for_url(url: str) -> str:
    host = _host(url)
    if "iwaspoisoned.com" in host:
        return "iwaspoisoned"
    if "reddit.com" in host:
        return "reddit"
    if any(x in host for x in ("news", "cnn.com", "nytimes.com", "washingtonpost.com")):
        return "news"
    return "web"


# Grocery-only iWasPoisoned — never restaurants / QSR biz pages.
IWP_GROCERY_PATH = "iwaspoisoned.com/industry/grocery_or_supermarket"
_IWP_RESTAURANT_REJECT = re.compile(
    r"iwaspoisoned\.com/(biz/|industry/(restaurant|fast_food|cafe|bar|hotel|cruise)|"
    r"tag/(wendy|mcdonald|burger|kfc|taco-bell|chipotle|subway|in-n-out|dunkin))",
    re.I,
)
_GROCERY_HINT = re.compile(
    r"\b(grocery|supermarket|costco|walmart|kroger|publix|aldi|trader\s*joe|"
    r"safeway|whole\s*foods|food\s*lion|heb|meijer|target|sams\s*club|"
    r"sprouts|wegmans|harris\s*teeter|giant\s*eagle|kirkland|neighborhood\s*market|"
    r"marketplace|supercenter)\b",
    re.I,
)

_GROCERY_BRANDS = re.compile(
    r"\b(Costco|Walmart|Kroger|Publix|Aldi|Trader\s*Joe'?s?|Safeway|Whole\s*Foods|"
    r"Food\s*Lion|H-?E-?B|Meijer|Target|Sam'?s\s*Club|Sprouts|Wegmans|"
    r"Harris\s*Teeter|Giant\s*Eagle|Lid[l]|ShopRite|Albertsons|Fred\s*Meyer|"
    r"Kirkland(?:\s+Signature)?)\b",
    re.I,
)

# iWasPoisoned title chrome — strip so we keep a shelf product name, not a headline.
_IWP_CHROME = re.compile(
    r"\b("
    r"food\s+poisoning(?:\s+reports?|\s+incident)?|"
    r"illness(?:\s+report)?|"
    r"causes?\s+(?:sickness|illness|vomiting|diarrhea|cramping)|"
    r"severe\s+(?:reaction\s+to|diarrhea|vomiting|cramping)|"
    r"stomach\s+issues?\s*(?:post-?)?|"
    r"digestive\s+issues?|"
    r"twice\s+sick\s+from|"
    r"recall\s+alert:?|"
    r"got\s+sick(?:\s+from)?|"
    r"report\s+it\s+now!?|"
    r"suspected|"
    r"incident|"
    r"reports?"
    r")\b",
    re.I,
)
_CITY_TAIL = re.compile(
    r",\s*[A-Z][A-Za-z .'-]+(?:,?\s*(?:AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|"
    r"LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|"
    r"UT|VT|VA|WA|WV|WI|WY|Alabama|Alaska|Arizona|Arkansas|California|Colorado|"
    r"Connecticut|Delaware|Florida|Georgia|Hawaii|Idaho|Illinois|Indiana|Iowa|"
    r"Kansas|Kentucky|Louisiana|Maine|Maryland|Massachusetts|Michigan|Minnesota|"
    r"Mississippi|Missouri|Montana|Nebraska|Nevada|New\s+Hampshire|New\s+Jersey|"
    r"New\s+Mexico|New\s+York|North\s+Carolina|North\s+Dakota|Ohio|Oklahoma|Oregon|"
    r"Pennsylvania|Rhode\s+Island|South\s+Carolina|South\s+Dakota|Tennessee|Texas|"
    r"Utah|Vermont|Virginia|Washington|West\s+Virginia|Wisconsin|Wyoming))?\s*$",
    re.I,
)


def split_grocery_identity(raw_title: str) -> tuple[str, str]:
    """
    Return (brand/company, general product name).
    Shelf display is always `name · brand` via frontend fullName.
    Parses iWasPoisoned patterns like:
      "Chicken Bake Illness Report - Costco, Eugene Oregon"
      "Hot Wings Cause Illness - Walmart, Florence South Carolina"
    """
    text = re.sub(r"\s+", " ", (raw_title or "").strip())
    brand = ""
    left = text
    right = ""

    # "Product chrome - Brand, City State"
    if " - " in text:
        left, right = text.split(" - ", 1)
        bm = _GROCERY_BRANDS.search(right) or _GROCERY_BRANDS.search(left)
        if bm:
            brand = bm.group(0)
        left = _CITY_TAIL.sub("", left).strip(" ,.-–—")
    else:
        bm = _GROCERY_BRANDS.search(text)
        if bm:
            brand = bm.group(0)
            left = (text[: bm.start()] + " " + text[bm.end() :]).strip(" ,.-–—")

    # Drop brand echo left in the product clause ("Costco Meal …")
    if brand:
        left = re.sub(re.escape(brand), " ", left, flags=re.I)
    left = _IWP_CHROME.sub(" ", left)
    left = _CITY_TAIL.sub("", left)
    left = re.sub(r"\s+", " ", left).strip(" ,.-–—:;")
    # Trailing "Cause(s)" residue after chrome strip
    left = re.sub(r"\s+causes?\s*$", "", left, flags=re.I).strip(" ,.-–—")

    # Fallback product when title is brand-only illness chrome
    if len(left) < 3:
        left = "Grocery item"

    from .glance_titles import glance_title

    titled = glance_title(brand=brand, name=left)
    if titled:
        out_brand = titled["brand"] if titled["brand"] not in {"", "Unknown"} else brand
        return (out_brand or brand or "", titled["name"])
    # Soft fallback — still prefer a short cleaned left over a news headline
    soft = left[:40].strip(" ,.-–—") or "Grocery item"
    return (brand, soft)


def is_allowed_iwaspoisoned_url(url: str, *, title: str = "", snippet: str = "") -> bool:
    """
    True if this iWasPoisoned URL is grocery/supermarket industry evidence.
    Restaurant / QSR / hotel biz pages are always rejected.
    Grocery-store biz/tag/incident pages are allowed when the store is named.
    """
    lowered = (url or "").lower()
    if "iwaspoisoned.com" not in lowered:
        return True
    blob = f"{url}\n{title}\n{snippet}"
    groceryish = bool(_GROCERY_HINT.search(blob) or _GROCERY_BRANDS.search(blob))
    # Restaurant / QSR paths — reject unless URL itself is clearly a grocery banner.
    if _IWP_RESTAURANT_REJECT.search(lowered):
        # /biz/costco-… and /biz/walmart-… are grocery, not restaurants.
        if "/biz/" in lowered and groceryish:
            return True
        return False
    if IWP_GROCERY_PATH in lowered:
        # Industry index page itself is a listing, not a product report.
        path = urlparse(url).path.rstrip("/").lower()
        if path.endswith("/industry/grocery_or_supermarket"):
            return False
        return True
    if re.search(r"iwaspoisoned\.com/(incident|report|product|tag)/", lowered):
        return groceryish
    return False


def _host(url: str) -> str:
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return ""
    return host[4:] if host.startswith("www.") else host


def _is_regulator(host: str) -> bool:
    return any(host == h or host.endswith("." + h) for h in REGULATOR_HOSTS)


def _parse_isoish(value: str) -> datetime | None:
    text = value.strip()
    if re.match(r"^\d{8}$", text):
        try:
            return datetime.strptime(text, "%Y%m%d")
        except ValueError:
            return None
    cleaned = text.replace("Z", "")
    if "T" in cleaned:
        cleaned = cleaned[:19]
        try:
            return datetime.strptime(cleaned, "%Y-%m-%dT%H:%M:%S")
        except ValueError:
            pass
        try:
            return datetime.strptime(cleaned[:16], "%Y-%m-%dT%H:%M")
        except ValueError:
            pass
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d")
    except ValueError:
        return None
