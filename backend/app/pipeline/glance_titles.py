"""
Glanceable food titles + quality gate.

Keep names short (grocery-shelf style). Reject regulator legalese and junk.
"""

from __future__ import annotations

import re

from ..security import sanitize_text

# Hard reject — these should never appear on the home feed.
_REJECT_NAME = re.compile(
    r"("
    r"unidentified|"
    r"not yet identified|"
    r"not identified|"
    r"\bineligible\b|"
    r"without the benefit|"
    r"without benefit|"
    r"illegally imported|"
    r"imported from|"
    r"imported without|"
    r"fda[- ]regulated|"
    r"containing fda|"
    r"\bvarious\b|"
    r"public health alert|"
    r"produced without|"
    r"\bpha[- ]|"
    r"exemption\s*4|"
    r"plumbus|"
    r"zyzzx|"
    r"no upc"
    r")",
    re.I,
)

_STRIP_PHRASES = [
    r"^FSIS\s+Issues\s+Public\s+Health\s+Alert\s+for\s+",
    r"^FSIS\s+Issues\s+Public\s+Health\s+Alert\s+",
    r"^Public\s+Health\s+Alert\s+for\s+",
    r"^USDA[- ]?FSIS\s+",
    r"\bnot[- ]?ready[- ]?to[- ]?eat\b",
    r"\bready[- ]?to[- ]?eat\b",
    r"\(nrte\)",
    r"\bnrte\b",
    r"\bfully\s+cooked\b",
    r"^frozen,\s*",  # FSIS "Frozen, Raw …" prefix only
    r"^raw,\s*",
    r"\bimported\b.*$",
    r"\bproduced without\b.*$",
    r"\bcontaining\b.*$",
    r"\bthat may be\b.*$",
    r"\bdue to\b.*$",
    r"\blinked to\b.*$",
    r"\bassociated with\b.*$",
    r"\bwithout the benefit\b.*$",
    r"\bwithout benefit\b.*$",
    r"\billegally\b.*$",
    r"\bfrom the (people|republic|united|kingdom|people's).*$",
]

_WEAK_BRAND = re.compile(
    r"^(whole|baby|dr|del|the|a|an|organic|fresh|coconut|fusilli|maple|unknown|"
    r"caers|search|fda|fsis|generic)$",
    re.I,
)

_FOOD_WORD = re.compile(
    r"\b("
    r"chicken|turkey|beef|pork|goat|lamb|meat|poultry|sausage|deli|ham|bacon|"
    r"nugget|chorizo|carnitas|dumpling|empanada|chili|soup|salad|wrap|"
    r"cheese|milk|cream|yogurt|butter|ice\s*cream|gelato|"
    r"lettuce|romaine|spinach|sprout|alfalfa|cantaloupe|melon|blueberry|mango|"
    r"pepper|jalapeño|jalapeno|onion|mushroom|shrimp|salmon|fish|oyster|seafood|"
    r"shake|protein|gushers|snack|candy|tamales|pasta|soda|crackers|chips?|"
    r"burrito|taco|sandwich|soup|stew|pizza|burger|nuggets|wings|bake|"
    r"hummus|hotdog|hot\s*dog|cookie|meal|produce|grocery|fruit|vegetable|"
    r"yogurt|smoothie|juice|bread|bagel|muffin|rice|bean|noodle|"
    r"prepared|snacks?|dairy|poultry|foods|store|purchase"
    r")\b",
    re.I,
)

_NEWS_CHROME = re.compile(
    r"\b("
    r"causes?\s*(?:illness|sickness|vomiting|diarrhea|cramping)?|"
    r"illness(?:\s+report)?|"
    r"food\s+poisoning(?:\s+(?:report|incident|reports))?|"
    r"severe\s+(?:reaction\s+to|diarrhea|vomiting)|"
    r"stomach\s+issues?\s*(?:post-?)?|"
    r"digestive\s+issues?|"
    r"twice\s+sick\s+from|"
    r"recall\s+alert:?|"
    r"report\s+it\s+now!?|"
    r"cyclospor(?:i)?a\s+symptoms\s+after|"
    r"symptoms\s+after|"
    r"diarrhea\s+alert:?"
    r")\b",
    re.I,
)


def glance_title(*, brand: str | None, name: str | None) -> dict | None:
    """
    Return {brand, name} with a very short grocery title, or None if junk.
    """
    brand_s = _clean(brand)
    name_s = _clean(name) or brand_s
    if not name_s:
        return None

    blob = name_s
    for pat in _STRIP_PHRASES:
        blob = re.sub(pat, " ", blob, flags=re.I)

    # "Company Recalls PRODUCT …"
    m = re.match(r"^(.*?)\s+Recalls?\s+(.*)$", blob, re.I)
    if m and len(m.group(2).strip()) >= 3:
        if not brand_s or brand_s.lower() in {"unknown", "fsis", "fda watch"}:
            brand_s = _brand(m.group(1))
        blob = m.group(2)

    blob = re.sub(r"\s+", " ", blob).strip(" ,.-/")
    # Drop leading articles / filler
    blob = re.sub(r"^(a|an|the)\s+", "", blob, flags=re.I)

    # Keep first short clause
    if "," in blob:
        first, rest = blob.split(",", 1)
        # Keep "pork, beef, and goat" style lists if short
        if len(blob) <= 36 and re.search(r"\b(and|&)\b", blob, re.I):
            pass
        else:
            blob = first.strip()

    item = _title_case(blob)
    item = re.sub(r"\bproducts?\b", "", item, flags=re.I)
    item = re.sub(r"\s+", " ", item).strip(" ,.-")

    # Cap hard for glanceability — never cut mid-word.
    if len(item) > 32:
        cut = item[:32].rsplit(" ", 1)[0].strip()
        item = cut if len(cut) >= 6 else item[:32].rstrip()
    # Don't leave dangling connectors / prepositions
    item = re.sub(
        r"\s+(and|or|of|with|for|the|a|an|in|on|from|to)$",
        "",
        item,
        flags=re.I,
    ).strip(" ,/-")
    # Drop leading Raw/Frozen for shelf glance (food is still clear)
    item = re.sub(r"^(Raw|Frozen)\s+", "", item, flags=re.I).strip()

    # Strip report chrome from iWasPoisoned / news titles → shelf label
    item = re.sub(
        r"\s*[–—-]\s*(Frenchy's|Grand Fiesta|DoubleTree|Athens|Clearwater).*$",
        "",
        item,
        flags=re.I,
    )
    item = _NEWS_CHROME.sub(" ", item)
    item = re.sub(r"\s+", " ", item).strip(" ,.-–—")
    # Drop dangling "Cause(s)" / "To" left after chrome removal
    item = re.sub(r"\s+(causes?|to)$", "", item, flags=re.I).strip(" ,.-–—")
    if item.lower() in {"meal", "costco meal", "prepared meal"}:
        item = "Prepared meal"
    if item.lower() in {"in-store food", "instore food", "store food", "grocery purchase"}:
        item = "In-store food"
    if item.lower() in {"milk cheese", "milk cheeses"}:
        item = "Raw milk cheese"
    if item.lower() in {"soft cheeses", "soft / queso-style cheeses", "soft cheese"}:
        item = "Soft cheese"
    if item.lower().startswith("romaine"):
        item = "Romaine salad mix"
    if "protein powder" in item.lower():
        item = "Protein powder"

    brand_out = _brand(brand_s)
    if brand_out.lower() in {"unknown", "fda watch", "search", "caers report", "fsis"}:
        brand_out = ""

    # Weak one-word "brands" are usually part of the product name (Whole Milk, Baby Spinach).
    if brand_out and _WEAK_BRAND.match(brand_out):
        item = _title_case(f"{brand_out} {item}".strip())
        brand_out = ""
        if len(item) > 32:
            item = item[:32].rsplit(" ", 1)[0].strip()
        item = re.sub(
            r"\s+(and|or|of|with|for|the|a|an|in|on|from|to)$",
            "",
            item,
            flags=re.I,
        ).strip(" ,/-")

    # Avoid "Brand · Brand"
    if brand_out and item.lower() == brand_out.lower():
        return None

    if not _is_sensible(item):
        return None
    # Must look like a food, not a company name alone.
    if not _FOOD_WORD.search(item):
        return None
    if brand_out and not _is_sensible(brand_out) and len(brand_out) > 28:
        brand_out = ""

    # Still-weak leftovers after merge (e.g. "Del Real Foods Chicken Tamales")
    if re.search(r"\bDel Real Foods\b", item, re.I):
        item = re.sub(r"^.*?\bDel Real Foods\s*", "", item, flags=re.I).strip() or "Chicken Tamales"
        brand_out = "Del Real"
    if re.match(r"^Hill\b", item, re.I) and not brand_out:
        item = "Maple Hill Milk"
        brand_out = "Maple Hill"
    # Trim farm-raised / kit fluff
    item = re.sub(r"\s+Farm Raised\b.*$", "", item, flags=re.I).strip()
    item = re.sub(r"\s+Salad Kit\b$", " Salad", item, flags=re.I).strip()

    return {"brand": brand_out or "", "name": item}


def is_sensible_product(brand: str | None, name: str | None, *, slug: str | None = None) -> bool:
    """True if this row is OK to show on the home feed."""
    titled = glance_title(brand=brand, name=name)
    if not titled:
        return False
    slug_s = (slug or "").lower()
    if slug_s.startswith("outbreak-") and re.search(
        r"unidentified|not-yet|nyi", f"{brand} {name} {slug_s}", re.I
    ):
        return False
    # Junk search experiments
    if slug_s.startswith("search-") and re.search(r"plumbus|zyzzx", slug_s):
        return False
    return True


def _is_sensible(text: str) -> bool:
    if not text or len(text) < 3:
        return False
    if _REJECT_NAME.search(text):
        return False
    # Truncated word endings (impor, benefi, conta, reass)
    if re.search(r"\b[a-z]{3,}(impor|benefi|conta|reass|inspec|regulat)\b", text, re.I):
        return False
    if text.rstrip().endswith(("impor", "benefi", "conta", "reass", "inspec")):
        return False
    # All-caps legalese residue
    if text.isupper() and len(text) > 20:
        return False
    return True


def _clean(value: str | None) -> str:
    text = sanitize_text(str(value or ""), 240)
    if text.startswith("[") and "]" in text[:80]:
        inner = text.strip("[]")
        parts = [p.strip(" '\"") for p in inner.split(",") if p.strip(" '\"")]
        text = parts[0] if parts else text
    text = re.sub(r"^\[\s*'|^\[\s*\"|'\]\s*$|\"\]\s*$", "", text).strip(" '\"")
    return re.sub(r"\s+", " ", text).strip()


def _brand(value: str) -> str:
    text = _clean(value)
    if not text:
        return ""
    text = re.sub(
        r",?\s*\b(LLC|L\.L\.C\.|Inc\.?|Incorporated|Corp\.?|Corporation|Co\.|Ltd\.?|Dba)\b\.?\s*$",
        "",
        text,
        flags=re.I,
    ).strip()
    # Drop trailing "Foods" / "Food Services" noise for glance brands
    text = re.sub(r"\s+(Food Services|Homestyle Foods|Fresh Foods|Foods|Delivery)\s*$", "", text, flags=re.I).strip()
    text = re.sub(r"\s+\b(Usa|U\.S\.A\.|US)\b\.?\s*$", "", text, flags=re.I).strip()
    text = re.sub(r"\s*/\s*$", "", text).strip()
    if len(text) > 22:
        text = text[:22].rsplit(" ", 1)[0].strip() or text[:22]
        text = text.rstrip(" /")
    return _title_case(text)


def _title_case(value: str) -> str:
    small = {"of", "and", "the", "a", "an", "or", "for", "with", "in"}
    words = re.split(r"(\s+|-)", value.strip())
    out: list[str] = []
    for i, word in enumerate(words):
        if not word or word.isspace() or word == "-":
            out.append(word)
            continue
        lower = word.lower()
        if i > 0 and lower in small:
            out.append(lower)
        else:
            out.append(lower[:1].upper() + lower[1:] if lower else word)
    return "".join(out) or value
