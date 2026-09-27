"""
Merge duplicate products. Two products are the same when they have the same brand and either:
  - the same name once sizes, lot numbers and the "(variety …)" part are stripped
    ("Black Pepper 4 oz" / "Black Pepper Lot 22A"; "Pepper Jack Cheese Varieties (Snack Pack…)"), or
  - the same official recall notice (one recall listed once per variety or size).

Everything that points at a duplicate (reports, recalls, posts, timeline, discovery runs, and
any table added later with a product foreign key) is moved to the kept product, then the
duplicates are deleted. Splitting one product four ways also split its reports, so merging
makes the signal stronger, not just the search results tidier.
"""

from __future__ import annotations

import re
from collections import defaultdict

from sqlalchemy import update
from sqlalchemy.orm import Session

from .database import Base
from .models import Product, Recall, Report

SIZE = re.compile(
    r"\b\d+(?:[.,]\d+)?\s*(?:oz|ounces?|lbs?|pounds?|g|grams?|kg|ml|l|liters?|fl\.?\s*oz|ct|count|pk|pack|pcs?)\b",
    re.I,
)
LOT = re.compile(r"\b(?:lot|batch|upc|sku|item|code)\s*(?:#|no\.?|number)?\s*[\w-]+", re.I)


COMPANY = re.compile(r"\b(?:llp|llc|inc|co|corp|company|ltd)\b\.?", re.I)


def _norm_brand(brand: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", COMPANY.sub(" ", (brand or "").lower())).strip()


def clean_name(name: str, brand: str | None = None) -> str:
    """Readable product name: no brand prefix, sizes, lot codes, "(variety…)" or trailing "…"."""
    n = name or ""
    b = _norm_brand(brand)
    if b:
        # "Clover Hill Dairy LLP, Pepper Jack..." → "Pepper Jack..."
        n = re.sub(rf"^\s*{re.escape(brand or '')}(?:\s*(?:llp|llc|inc|co|corp)\.?)?\s*[,:-]?\s*", "", n, flags=re.I)
    n = n.split("(")[0]
    n = SIZE.sub(" ", n)
    n = LOT.sub(" ", n)
    n = re.sub(r",?\s*(?:sold in|packaged in|repackaged into)\b.*$", "", n, flags=re.I)
    n = re.sub(r",?\s*\bnet\s*(?:wt|weight)\b.*$", "", n, flags=re.I)  # "net weight 24 lbs"
    n = re.sub(r"\b\d+\s*x\b", " ", n, flags=re.I)  # "8 x 3 lb" pack counts
    n = re.sub(r"\b(?:pouch(?:es)?|cases?|cartons?)\b", " ", n, flags=re.I)
    n = re.sub(r"[…]+|\.\.\.", "", n)
    return re.sub(r"\s+", " ", n).strip(" ,-") or (name or "").strip()


def product_key(product: Product) -> str:
    name = re.sub(r"[^a-z0-9]+", " ", clean_name(product.name, product.brand).lower()).strip()
    return f"{_norm_brand(product.brand)}|{name}"


def _tables_pointing_at_products():
    """(table, column) for every foreign key to products.id, including tables added later."""
    for table in Base.metadata.sorted_tables:
        for column in table.columns:
            for fk in column.foreign_keys:
                if fk.column.table.name == "products" and fk.column.name == "id":
                    yield table, column


def find_duplicate_groups(db: Session) -> list[list[Product]]:
    products = db.query(Product).all()
    parent = {p.id: p.id for p in products}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        parent[find(a)] = find(b)

    by_key: dict[str, int] = {}
    for p in products:
        key = product_key(p)
        if not key.split("|", 1)[1]:
            continue
        if key in by_key:
            union(p.id, by_key[key])
        else:
            by_key[key] = p.id

    # Same brand + same recall notice
    by_recall: dict[tuple[str, str], int] = {}
    brands = {p.id: _norm_brand(p.brand) for p in products}
    for recall in db.query(Recall).all():
        brand = brands.get(recall.product_id)
        if not brand or not recall.source_url:
            continue
        key = (brand, recall.source_url)
        if key in by_recall:
            union(recall.product_id, by_recall[key])
        else:
            by_recall[key] = recall.product_id

    groups: dict[int, list[Product]] = defaultdict(list)
    for p in products:
        groups[find(p.id)].append(p)
    return [g for g in groups.values() if len(g) > 1]


WEAK_WORDS = {
    "variety", "varieties", "assorted", "and", "with", "the", "a", "of", "on", "in",
    "cooked", "fresh", "frozen", "organic", "flavored", "smoked", "raw", "mild", "sharp",
    "plain", "original", "classic", "new", "net", "wt", "upc", "oz",
}


def display_brand(brand: str | None) -> str:
    """"Taylor Farms de Mexico, S. de R.L. de C.V." → "Taylor Farms de Mexico"; "Canteen Inc" → "Canteen"."""
    b = (brand or "").split(",")[0]
    # Mexican company suffixes ("S. de R.L. de C.V.", "S.A. de C.V."); the dots are required so "Sam" survives
    b = re.sub(r"\bS\.\s*(?:A\.|de\s+R\.\s*L\.?)\s*(?:de\s+C\.\s*V\.?)?", "", b, flags=re.I)
    b = re.sub(r"\b(?:llp|llc|inc|co|corp|company|ltd)\b\.?", "", b, flags=re.I)
    return re.sub(r"\s+", " ", b).strip(" .-")


def _tidy_case(text: str) -> str:
    return text.title() if text.isupper() else text


def merged_name(group: list[Product], keeper: Product) -> str:
    """One name for the group: the words every variety shares, or the brand when they share too few."""
    names = [clean_name(p.name, p.brand) for p in group]
    if len({n.lower() for n in names}) == 1:
        return _tidy_case(names[0])
    n = len(group)
    word_sets = [set(re.findall(r"[a-z0-9']+", x.lower())) for x in names]
    shared = set.intersection(*word_sets)
    keeper_words = [w.strip(",") for w in clean_name(keeper.name, keeper.brand).split()]
    common = [w for w in keeper_words if w.lower() in shared]
    strong = [w for w in common if w.lower() not in WEAK_WORDS and not w.isdigit()]
    brand = display_brand(keeper.brand)
    if len(strong) >= 2:  # e.g. "Ready Care Shake", "Spring Mulberry Chocolate"
        return f"{_tidy_case(' '.join(common))} ({n} varieties)"
    if len(strong) == 1 and brand:  # e.g. "Clover Hill Dairy cheese"
        return f"{brand} {strong[0].lower()} ({n} varieties)"
    return f"{brand or 'Recalled'} products ({n} varieties)"


def _pick_keeper(group: list[Product], db: Session) -> Product:
    def score(p: Product):
        reports = db.query(Report).filter(Report.product_id == p.id).count()
        return (bool(p.image_url), reports, -p.id)

    return max(group, key=score)


def merge_duplicate_products(db: Session, dry_run: bool = False) -> dict:
    groups = find_duplicate_groups(db)
    merged = 0
    details = []
    for group in groups:
        keeper = _pick_keeper(group, db)
        dupes = [p for p in group if p.id != keeper.id]
        details.append({"kept": keeper.slug, "name": merged_name(group, keeper), "merged": [p.slug for p in dupes]})
        if dry_run:
            continue
        dupe_ids = [p.id for p in dupes]
        for table, column in _tables_pointing_at_products():
            db.execute(update(table).where(column.in_(dupe_ids)).values({column.name: keeper.id}))
        # Keep the best image; name the group by what the varieties share; list every variety
        # in the summary so searching any of them (e.g. "pepper jack") still finds it
        if not keeper.image_url:
            keeper.image_url = next((p.image_url for p in dupes if p.image_url), None)
        varieties = list(dict.fromkeys(clean_name(p.name, p.brand) for p in group))
        keeper.name = merged_name(group, keeper)[:240]
        if len(varieties) > 1:
            listing = "Includes: " + "; ".join(varieties)
            keeper.summary = f"{keeper.summary}\n{listing}" if keeper.summary else listing
        db.flush()
        for p in dupes:
            db.delete(p)
        merged += len(dupes)
    if not dry_run:
        # The same recall notice attached once per size is now repeated on one product
        seen = set()
        for recall in db.query(Recall).order_by(Recall.id).all():
            key = (recall.product_id, recall.source_url)
            if key in seen:
                db.delete(recall)
            else:
                seen.add(key)
        db.commit()
    return {"groups": len(groups), "products_merged": merged, "details": details}
