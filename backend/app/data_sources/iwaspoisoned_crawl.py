"""
Crawl iWasPoisoned grocery/supermarket industry listing over HTTPS.

Plain httpx is blocked by their bot check; Playwright is required.
Caps keep volume hackathon-safe — raise deliberately if needed.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import urljoin

from ..config import get_settings

logger = logging.getLogger(__name__)

GROCERY_LIST = "https://iwaspoisoned.com/industry/grocery_or_supermarket"

# Hard caps — sized for ~2 months of grocery reports (~10/page).
DEFAULT_MAX_PAGES = 40
DEFAULT_MAX_INCIDENTS = 400


@dataclass
class IwpIncident:
    url: str
    title: str
    text: str
    published: datetime | None
    store_hint: str = ""


def crawl_grocery_incidents(
    *,
    max_pages: int | None = None,
    max_incidents: int | None = None,
    days: int | None = None,
) -> dict:
    """
    Return {incidents: list[IwpIncident], pages: int, capped: bool, error: str|None}.
    """
    settings = get_settings()
    max_pages = max(1, max_pages or DEFAULT_MAX_PAGES)
    max_incidents = max(1, max_incidents or DEFAULT_MAX_INCIDENTS)
    window = days if days is not None else settings.discovery_recency_days
    cutoff = datetime.utcnow() - timedelta(days=max(14, window))

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {
            "incidents": [],
            "pages": 0,
            "capped": False,
            "error": "playwright_not_installed",
        }

    listed: list[dict] = []
    capped = False
    pages_done = 0

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            for page_num in range(1, max_pages + 1):
                url = GROCERY_LIST if page_num == 1 else f"{GROCERY_LIST}?page={page_num}"
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=45000)
                    page.wait_for_timeout(1200)
                    # Bot wall / meta-refresh can destroy the first execution context.
                    try:
                        page.wait_for_selector('a[href*="/incident/"]', timeout=8000)
                    except Exception:
                        page.wait_for_timeout(1500)
                except Exception as exc:
                    logger.warning("iWP list page %s failed: %s", page_num, exc)
                    break
                pages_done = page_num
                try:
                    rows = page.eval_on_selector_all(
                        'a[href*="/incident/"]',
                        """els => {
                          const seen = new Set();
                          const out = [];
                          for (const e of els) {
                            const href = (e.href || '').split('#')[0];
                            if (!href || seen.has(href)) continue;
                            seen.add(href);
                            const card = e.closest('article, li, .row, div') || e.parentElement;
                            out.push({
                              url: href,
                              around: ((card && card.innerText) || e.innerText || '').trim().slice(0, 400)
                            });
                          }
                          return out;
                        }""",
                    )
                except Exception as exc:
                    logger.warning("iWP list eval page %s failed: %s — retrying once", page_num, exc)
                    try:
                        page.wait_for_timeout(2000)
                        page.goto(url, wait_until="load", timeout=45000)
                        page.wait_for_timeout(1500)
                        rows = page.eval_on_selector_all(
                            'a[href*="/incident/"]',
                            """els => {
                              const seen = new Set();
                              const out = [];
                              for (const e of els) {
                                const href = (e.href || '').split('#')[0];
                                if (!href || seen.has(href)) continue;
                                seen.add(href);
                                const card = e.closest('article, li, .row, div') || e.parentElement;
                                out.push({
                                  url: href,
                                  around: ((card && card.innerText) || e.innerText || '').trim().slice(0, 400)
                                });
                              }
                              return out;
                            }""",
                        )
                    except Exception as exc2:
                        logger.warning("iWP list page %s gave up: %s", page_num, exc2)
                        break
                if not rows:
                    break
                page_all_old = True
                for row in rows:
                    age = _parse_relative_age(row.get("around") or "")
                    if age is None or age >= cutoff:
                        page_all_old = False
                    listed.append(row)
                    if len(listed) >= max_incidents:
                        capped = True
                        break
                logger.info(
                    "iWP list page %s: +%s links (listed=%s)",
                    page_num,
                    len(rows),
                    len(listed),
                )
                if capped:
                    break
                # Entire page older than window → stop paging further back.
                if page_all_old and page_num > 1:
                    break
                # Stop early if "See More" disappears
                more = page.query_selector(f'a[href*="page={page_num + 1}"]')
                if not more and page_num > 1:
                    break

            incidents: list[IwpIncident] = []
            for idx, row in enumerate(listed[:max_incidents], start=1):
                url = (row.get("url") or "").split("#")[0].rstrip("/")
                if not url:
                    continue
                around = row.get("around") or ""
                store_hint = around.split("\n")[0].strip()[:160]
                rel = _parse_relative_age(around)
                published = rel
                title = store_hint or url
                text = around
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=25000)
                    page.wait_for_timeout(400)
                    detail = page.eval_on_selector(
                        "body",
                        """el => {
                          const h = document.querySelector('h1, h2, .title, [class*="title"]');
                          const body = document.querySelector('article, main, .report, .content') || el;
                          return {
                            title: (h && h.innerText || document.title || '').trim().slice(0, 240),
                            text: (body && body.innerText || '').trim().slice(0, 5000)
                          };
                        }""",
                    )
                    title = (detail or {}).get("title") or store_hint or url
                    text = (detail or {}).get("text") or around
                    # Prefer an absolute date from the page when present
                    from ..pipeline.evidence_schema import parse_observed_at

                    observed = parse_observed_at(text=f"{title}\n{text}", url=url, published=published)
                    if observed:
                        published = observed
                except Exception as exc:
                    logger.debug("iWP incident fetch failed %s: %s", url[:80], exc)
                    title = store_hint or url
                    if not published:
                        published = None

                if published and published < cutoff:
                    continue
                if not published:
                    # Fail closed on undated pages
                    continue

                incidents.append(
                    IwpIncident(
                        url=url,
                        title=title[:240],
                        text=text[:5000],
                        published=published,
                        store_hint=store_hint,
                    )
                )
                if idx % 25 == 0:
                    logger.info("iWP detail progress %s/%s kept=%s", idx, len(listed), len(incidents))
            browser.close()
    except Exception as exc:
        logger.exception("iWP grocery crawl failed")
        return {"incidents": [], "pages": pages_done, "capped": capped, "error": str(exc)[:200]}

    return {
        "incidents": incidents,
        "pages": pages_done,
        "capped": capped or len(listed) >= max_incidents,
        "listed": len(listed),
        "error": None,
    }


_REL_AGE = re.compile(
    r"\b(\d+)\s*(minute|hour|day|week|month)s?\s+ago\b",
    re.I,
)


def _parse_relative_age(blob: str) -> datetime | None:
    m = _REL_AGE.search(blob or "")
    if not m:
        return None
    n = int(m.group(1))
    unit = m.group(2).lower()
    now = datetime.utcnow()
    if unit.startswith("minute"):
        return now - timedelta(minutes=n)
    if unit.startswith("hour"):
        return now - timedelta(hours=n)
    if unit.startswith("day"):
        return now - timedelta(days=n)
    if unit.startswith("week"):
        return now - timedelta(weeks=n)
    if unit.startswith("month"):
        return now - timedelta(days=30 * n)
    return None
