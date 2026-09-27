from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .x_sweep_job import router as x_sweep_router
from .categories import router as categories_router
from .case_summary import router as case_summary_router

from .bootstrap import bootstrap_catalog, start_home_scrape_background
from .cpsc_sync import start_cpsc_sync_background
from .image_lookup import start_image_lookup_background
from .venue_check import start_venue_check_background
from .config import get_settings
from .auth import AuthUser, require_user
from .database import Base, SessionLocal, engine, ensure_schema, get_db
from .models import Product
from .pipeline.signals import compute_signal
from .serialize import product_card
from .services import (
    add_comment,
    create_post,
    create_user_report,
    get_product,
    list_feed,
    product_payload,
    run_discovery,
    search_catalog,
    search_locations,
    toggle_like,
)

settings = get_settings()
Path(settings.resolved_upload_dir).mkdir(parents=True, exist_ok=True)
Base.metadata.create_all(bind=engine)
ensure_schema()
with SessionLocal() as session:
    home_products = bootstrap_catalog(session)
    home_slugs = [product.slug for product in home_products]

if not settings.snapshot_mode:
    start_home_scrape_background(home_slugs)
    start_cpsc_sync_background()
    start_image_lookup_background()
    start_venue_check_background()
else:
    import logging

    logging.getLogger("app.main").info(
        "SNAPSHOT_MODE on — skipped home scrape / CPSC / image lookup / venue check"
    )


def _warm_feed_cache() -> None:
    """Precompute the national homepage so the first visitor isn't paying ~7s."""
    import logging
    import threading

    log = logging.getLogger("app.feed_cache")

    def worker() -> None:
        try:
            with SessionLocal() as db:
                list_feed(db, city=None)
            log.info("Homepage feed cache warmed")
        except Exception:
            log.exception("Homepage feed cache warm failed")

    threading.Thread(target=worker, name="feed-cache-warm", daemon=True).start()


_warm_feed_cache()

app = FastAPI(title="Recall Me Maybe", version="0.1.0", docs_url="/docs")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)

app.include_router(x_sweep_router)
app.include_router(categories_router)
app.include_router(case_summary_router)

class ReportIn(BaseModel):
    product_slug: str | None = None
    product_name: str | None = None
    brand: str | None = None
    model: str | None = None
    upc: str | None = None
    category: str | None = None
    text: str = Field(min_length=12, max_length=4000)
    title: str | None = None
    display_name: str | None = "Neighbor"
    location_label: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    incident_date: str | None = None


class PostIn(BaseModel):
    product_slug: str
    body: str = Field(min_length=4, max_length=4000)
    title: str | None = None
    display_name: str | None = "Neighbor"
    location_label: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    counts_as_report: bool = True


class CommentIn(BaseModel):
    body: str = Field(min_length=2, max_length=2000)
    display_name: str | None = "Neighbor"


class DiscoverIn(BaseModel):
    extra: str | None = None
    force: bool = False


@app.get("/health")
def health():
    from .data_sources.web_search import available_provider

    return {
        "ok": True,
        "app": settings.app_name,
        "snapshot_mode": settings.snapshot_mode,
        "live_search": False if settings.snapshot_mode else settings.has_live_search(),
        "search_provider": None if settings.snapshot_mode else available_provider(),
        "auth": settings.cognito_configured,
    }


@app.get("/api/feed")
def feed(city: str | None = None, db: Session = Depends(get_db)):
    return list_feed(db, city=city)


@app.get("/api/products")
def products(db: Session = Depends(get_db)):
    rows = db.query(Product).order_by(Product.name).all()
    return {"products": [product_card(row, compute_signal(db, row)) for row in rows]}


@app.get("/api/products/{slug}")
def product(slug: str, issue: str | None = None, db: Session = Depends(get_db)):
    row = get_product(db, slug)
    if not row:
        raise HTTPException(404, "Product not found")
    return product_payload(db, row, issue_slug=issue)


@app.get("/api/search")
def search(q: str = "", live: bool = True, db: Session = Depends(get_db)):
    # Empty catalog always triggers live discovery (see search_catalog).
    return search_catalog(db, q, live=live)


@app.get("/api/locations")
def locations(q: str = ""):
    return search_locations(q)


@app.post("/api/reports")
def reports(payload: ReportIn, user: AuthUser = Depends(require_user), db: Session = Depends(get_db)):
    try:
        return create_user_report(db, payload.model_dump(), user)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/posts")
def posts(payload: PostIn, user: AuthUser = Depends(require_user), db: Session = Depends(get_db)):
    try:
        return create_post(db, payload.model_dump(), user)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/posts/{post_id}/comments")
def comments(
    post_id: int,
    payload: CommentIn,
    user: AuthUser = Depends(require_user),
    db: Session = Depends(get_db),
):
    try:
        return add_comment(db, post_id, payload.model_dump(), user)
    except ValueError as exc:
        raise HTTPException(404 if "not found" in str(exc).lower() else 400, str(exc)) from exc


@app.post("/api/posts/{post_id}/likes")
def likes(post_id: int, user: AuthUser = Depends(require_user), db: Session = Depends(get_db)):
    try:
        return toggle_like(db, post_id, user)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.post("/api/products/{slug}/discover")
def discover(slug: str, payload: DiscoverIn | None = None, db: Session = Depends(get_db)):
    try:
        return run_discovery(
            db,
            slug,
            extra=(payload.extra if payload else None),
            force=(payload.force if payload else False),
        )
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc