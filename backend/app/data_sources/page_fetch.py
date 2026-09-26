from __future__ import annotations

import re

import httpx
from bs4 import BeautifulSoup

from ..security import sanitize_text

USER_AGENT = "SIGNAL-SafetyResearch/0.1 (hackathon demo; +https://github.com/emmaZX/HackGT-26)"


def fetch_readable(url: str, timeout: float = 12.0) -> dict:
    """Generic page reader. One path for every site — no per-domain scrapers."""
    if not url.startswith(("http://", "https://")):
        raise ValueError("Only http(s) URLs can be fetched")
    with httpx.Client(follow_redirects=True, timeout=timeout, headers={"User-Agent": USER_AGENT}) as client:
        response = client.get(url)
        response.raise_for_status()
        html = response.text
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "nav", "footer", "iframe"]):
        tag.decompose()
    title = soup.title.get_text(strip=True) if soup.title else url
    article = soup.find("article") or soup.find("main") or soup.body
    text = article.get_text(" ", strip=True) if article else ""
    text = sanitize_text(text, 8000)
    return {"url": str(response.url), "title": title[:300], "text": text}


def domain_of(url: str) -> str:
    match = re.search(r"https?://([^/]+)", url or "")
    return match.group(1).lower() if match else "unknown"
