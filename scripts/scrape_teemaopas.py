#!/usr/bin/env python3
"""
Crawl https://support.mycashflow.com/fi/teemaopas and extract Interface tag docs.

Run locally (not in a locked-down CI sandbox — the site may 403 plain urllib):

  cd scripts
  python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\\Scripts\\activate
  pip install -r requirements-teemaopas.txt
  playwright install chromium
  python scrape_teemaopas.py --out teemaopas-full.json

Optional:
  python scrape_teemaopas.py --out out.json --max-pages 500 --delay 0.25 --headed
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

PREFIX_PATH = "/fi/teemaopas"
TAG_HEADING = re.compile(r"^(\{[A-Za-z0-9_]+\})")


@dataclass
class PageRecord:
    url: str
    title: str = ""
    h1: str = ""
    tag: str | None = None
    shortdesc: str = ""
    longdesc: str = ""
    sections: dict[str, str] = field(default_factory=dict)
    attribute_blocks: list[dict] = field(default_factory=list)
    tag_scope: str = ""
    tables_text: list[str] = field(default_factory=list)
    error: str | None = None


def normalize_url(url: str, base: str) -> str:
    joined = urljoin(base, url)
    p = urlparse(joined)
    if p.scheme not in ("http", "https"):
        return ""
    path = p.path.rstrip("/") or "/"
    if not path.startswith(PREFIX_PATH):
        return ""
    return f"{p.scheme}://{p.netloc}{path}"


def dismiss_cookie_banner(page) -> None:
    for name in (
        "Hyväksy kaikki cookies",
        "Accept all",
        "Kiellä kaikki cookies",
    ):
        try:
            btn = page.get_by_role("button", name=name)
            if btn.count() and btn.first.is_visible(timeout=800):
                btn.first.click(timeout=2000)
                time.sleep(0.3)
                return
        except Exception:
            continue


def extract_sections(soup: BeautifulSoup) -> dict[str, str]:
    """Collect text under each h2 until the next h2 (Finnish docs use h2 for major blocks)."""
    sections: dict[str, str] = {}
    body = soup.body
    if not body:
        return sections

    for h2 in body.find_all("h2"):
        key = h2.get_text(" ", strip=True)
        if not key:
            continue
        parts: list[str] = []
        for sib in h2.find_next_siblings():
            if sib.name == "h2":
                break
            text = sib.get_text("\n", strip=True)
            if text:
                parts.append(text)
        if parts:
            sections[key] = "\n".join(parts).strip()
    return sections


def extract_tables(soup: BeautifulSoup, max_tables: int = 8) -> list[str]:
    out: list[str] = []
    body = soup.body
    if not body:
        return out
    for i, table in enumerate(body.find_all("table")):
        if i >= max_tables:
            break
        t = table.get_text("\n", strip=True)
        if t:
            out.append(t[:8000])
    return out


def extract_shortdesc(soup: BeautifulSoup) -> str:
    """Read .shortdesc element verbatim — short summary that appears under the title."""
    el = soup.select_one(".shortdesc")
    if not el:
        return ""
    return el.get_text(" ", strip=True)


def extract_longdesc(soup: BeautifulSoup) -> str:
    """Read .longdesc element with .anchor-link descendants removed."""
    el = soup.select_one(".longdesc")
    if not el:
        return ""
    el = copy.copy(el)
    for anchor in el.select(".anchor-link"):
        anchor.decompose()
    text = el.get_text("\n", strip=True)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def extract_attribute_blocks(soup: BeautifulSoup) -> list[dict]:
    """Pull attribute blocks from .tag-attributes using .attribute-name / .attribute-desc."""
    blocks: list[dict] = []
    container = soup.select_one(".tag-attributes")
    if not container:
        return blocks

    name_nodes = container.select(".attribute-name")
    if name_nodes:
        for name_node in name_nodes:
            name = name_node.get_text(" ", strip=True)
            desc_node = None
            for sib in name_node.find_next_siblings():
                classes = sib.get("class") or []
                if "attribute-desc" in classes:
                    desc_node = sib
                    break
                if "attribute-name" in classes:
                    break
            if desc_node is None:
                parent = name_node.parent
                if parent is not None:
                    desc_node = parent.select_one(".attribute-desc")
            description = ""
            if desc_node is not None:
                cleaned = copy.copy(desc_node)
                for anchor in cleaned.select(".anchor-link"):
                    anchor.decompose()
                description = re.sub(
                    r"\n{3,}", "\n\n", cleaned.get_text("\n", strip=True)
                ).strip()
            if name:
                blocks.append({"name": name, "description": description})
        return blocks

    return blocks


def _find_tag_scope_element(soup: BeautifulSoup):
    """Locate the scope/visibility block; markup varies between builds."""
    for sel in (
        ".tag-scope",
        "[class*='tag-scope']",
        ".TagScope",
        "[class*='TagScope']",
    ):
        el = soup.select_one(sel)
        if el:
            classes = " ".join(el.get("class") or [])
            if sel.startswith("[") and "tag-scope" not in classes.lower():
                continue
            return el
    for el in soup.find_all(True):
        classes = el.get("class") or []
        for c in classes:
            if isinstance(c, str) and "tag-scope" in c.lower():
                return el
    return None


def extract_tag_scope(soup: BeautifulSoup) -> str:
    """Read .tag-scope (visibility / scope) with .anchor-link descendants removed."""
    el = _find_tag_scope_element(soup)
    if not el:
        return ""
    el = copy.copy(el)
    for anchor in el.select(".anchor-link"):
        anchor.decompose()
    text = el.get_text("\n", strip=True)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def visibility_h2_section(sections: dict[str, str]) -> str:
    """Return the 'Näkyvyys' h2 section text exactly as captured by extract_sections."""
    return (sections.get("Näkyvyys") or "").strip()


def visibility_body_fallback(soup: BeautifulSoup) -> str:
    """Last-resort sweep: look for a paragraph containing 'Toimii näkyvyydessä' anywhere."""
    needles = ("Toimii näkyvyydessä", "Toimii näkymässä")
    body = soup.body
    if not body:
        return ""
    parts: list[str] = []
    for el in body.find_all(["p", "li", "div"]):
        text = el.get_text(" ", strip=True)
        if not text:
            continue
        if any(n in text for n in needles):
            parts.append(text)
            if len(parts) >= 6:
                break
    return "\n".join(parts).strip()


def parse_tag_page(soup: BeautifulSoup, url: str) -> PageRecord:
    title_el = soup.find("title")
    title = title_el.get_text(strip=True) if title_el else ""

    h1_el = soup.find("h1")
    h1 = h1_el.get_text(" ", strip=True) if h1_el else ""

    tag: str | None = None
    m = TAG_HEADING.match(h1)
    if m:
        tag = m.group(1)
    elif "|" in title:
        cand = title.split("|", 1)[0].strip()
        m2 = TAG_HEADING.match(cand)
        if m2:
            tag = m2.group(1)

    sections = extract_sections(soup)
    tables = extract_tables(soup)
    shortdesc = extract_shortdesc(soup)
    longdesc = extract_longdesc(soup)
    attribute_blocks = extract_attribute_blocks(soup)
    tag_scope = extract_tag_scope(soup)
    if not tag_scope:
        tag_scope = visibility_h2_section(sections)
    if not tag_scope:
        tag_scope = visibility_body_fallback(soup)

    return PageRecord(
        url=url,
        title=title,
        h1=h1,
        tag=tag,
        shortdesc=shortdesc,
        longdesc=longdesc,
        sections=sections,
        attribute_blocks=attribute_blocks,
        tag_scope=tag_scope,
        tables_text=tables,
    )


def discover_links(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    found: list[str] = []
    for a in soup.find_all("a", href=True):
        u = normalize_url(a["href"], base_url)
        if u:
            found.append(u)
    return found


def run(
    start_url: str,
    out_path: str,
    max_pages: int,
    delay_s: float,
    headed: bool,
    timeout_ms: int,
    min_tags: int = 1,
) -> int:
    seen: set[str] = set()
    queued: set[str] = set()
    start_norm = normalize_url(start_url, start_url)
    queue: deque[str] = deque([start_norm])
    queued.add(start_norm)
    pages: list[PageRecord] = []
    errors: list[dict[str, Any]] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            locale="fi-FI",
        )
        page = context.new_page()

        while queue and len(pages) < max_pages:
            url = queue.popleft()
            if url in seen:
                continue
            seen.add(url)

            try:
                resp = page.goto(url, wait_until="load", timeout=timeout_ms)
                if resp is not None and resp.status >= 400:
                    errors.append({"url": url, "error": f"HTTP {resp.status}"})
                    time.sleep(delay_s)
                    continue
                dismiss_cookie_banner(page)
                try:
                    page.wait_for_selector(".tag-scope, .shortdesc, .longdesc", timeout=2500)
                except Exception:
                    pass
                page.wait_for_timeout(350)
                html = page.content()
            except Exception as e:
                errors.append({"url": url, "error": repr(e)})
                time.sleep(delay_s)
                continue

            for link in discover_links(html, url):
                if link not in seen and link not in queued:
                    queued.add(link)
                    queue.append(link)

            try:
                soup = BeautifulSoup(html, "html.parser")
                rec = parse_tag_page(soup, url)
            except Exception as e:
                rec = PageRecord(url=url, error=repr(e))

            pages.append(rec)
            time.sleep(delay_s)

        context.close()
        browser.close()

    tag_pages = [p for p in pages if p.tag and not p.error]

    if len(tag_pages) < min_tags:
        print(
            f"ABORT: scraped only {len(tag_pages)} tag pages (min-tags={min_tags}); "
            "likely blocked or markup changed. Refusing to overwrite output.",
            file=sys.stderr,
        )
        return 2

    payload = {
        "start_url": start_url,
        "page_count": len(pages),
        "unique_urls_crawled": len(seen),
        "tag_page_count": len(tag_pages),
        "errors": errors[:200],
        "pages": [asdict(p) for p in pages],
        "tags_index": [
            {
                "tag": p.tag,
                "url": p.url,
                "shortdesc": (p.shortdesc or "")[:2000],
                "longdesc": (p.longdesc or "")[:8000],
                "tag_scope": (p.tag_scope or "")[:4000],
                "visibility": (
                    (p.sections.get("Näkyvyys") or "") or (p.tag_scope or "")
                )[:4000],
                "syntax": (p.sections.get("Syntaksi") or "")[:2000],
                "attributes": (p.sections.get("Attribuutit") or "")[:6000],
                "attribute_blocks": p.attribute_blocks,
                "tables_preview": p.tables_text[:2],
            }
            for p in tag_pages
        ],
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"Wrote {out_path}")
    print(f"Pages: {len(pages)}, tag pages: {len(tag_pages)}, errors: {len(errors)}")
    return 0 if len(pages) else 1


def main() -> None:
    ap = argparse.ArgumentParser(description="Scrape MyCashflow Teemaopas (Playwright)")
    ap.add_argument(
        "--start",
        default="https://support.mycashflow.com/fi/teemaopas",
        help="Start URL (must be under /fi/teemaopas)",
    )
    ap.add_argument("--out", default="teemaopas-full.json", help="Output JSON path")
    ap.add_argument("--max-pages", type=int, default=1500, help="Safety cap")
    ap.add_argument("--delay", type=float, default=0.2, help="Seconds between requests")
    ap.add_argument("--headed", action="store_true", help="Show browser (debug)")
    ap.add_argument("--timeout", type=int, default=45000, help="Navigation timeout ms")
    ap.add_argument(
        "--min-tags",
        type=int,
        default=120,
        help="Minimum tag pages required for the scrape to be considered successful (default 120).",
    )
    args = ap.parse_args()

    if PREFIX_PATH not in urlparse(args.start).path:
        print("Start URL must be under /fi/teemaopas", file=sys.stderr)
        sys.exit(2)

    sys.exit(
        run(
            start_url=args.start,
            out_path=args.out,
            max_pages=args.max_pages,
            delay_s=args.delay,
            headed=args.headed,
            timeout_ms=args.timeout,
            min_tags=args.min_tags,
        )
    )


if __name__ == "__main__":
    main()
