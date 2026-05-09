#!/usr/bin/env python3
"""
Luo suomenkielinen, haettava cheat sheet -HTML teemaopas-scrapen JSON-datasta.

Käyttö:
  python build_teemaopas_cheatsheet.py \
    --input teemaopas-full.json \
    --output teemaopas-cheatsheet.html
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def short(s: str, n: int = 260) -> str:
    s = norm(s)
    if len(s) <= n:
        return s
    return s[: n - 1].rstrip() + "…"


def normalize_attr_name(raw: str) -> str:
    name = norm(raw).strip("` ")
    name = name.rstrip(":").strip()
    if "/" in name:
        parts = [p.strip().rstrip(":").strip() for p in name.split("/")]
        parts = [p for p in parts if p]
        if parts:
            name = " / ".join(parts)
    return name


def attr_blocks_from_text(attr_text: str, syntax_text: str) -> list[dict]:
    """Parse attribute blocks from a flat 'Attribuutit' text dump (legacy data)."""
    text = attr_text or ""
    blocks: list[dict] = []

    matches = list(re.finditer(r"`([a-zA-Z_][a-zA-Z0-9_/ -]*):`", text))
    if matches:
        for i, m in enumerate(matches):
            name = normalize_attr_name(m.group(1))
            start = m.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            desc = norm(text[start:end])
            blocks.append({"name": name, "description": desc})
        return blocks

    fallback: list[str] = []
    for m in re.finditer(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\s*:", text):
        name = normalize_attr_name(m.group(1))
        if name.lower() in {"http", "https"}:
            continue
        if name not in fallback:
            fallback.append(name)
    if fallback:
        return [
            {"name": n, "description": "Kuvaus ei jäsentynyt automaattisesti. Avaa dokumentaatiosivu."}
            for n in fallback
        ]

    for m in re.finditer(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\s*:", syntax_text or ""):
        name = normalize_attr_name(m.group(1))
        if not any(b["name"] == name for b in blocks):
            blocks.append(
                {
                    "name": name,
                    "description": "Poimittu syntaksista. Avaa dokumentaatiosivu tarkkaa kuvausta varten.",
                }
            )
    return blocks


def merge_global_attrs(blocks: list[dict]) -> list[dict]:
    """Combine 'before' + 'after' duplicates and ensure global attrs come last."""
    merged: list[dict] = []
    seen_names: dict[str, dict] = {}
    global_order = ["before / after", "escape", "or"]

    for b in blocks:
        name = (b.get("name") or "").strip()
        desc = (b.get("description") or "").strip()
        if name.lower() in {"before", "after"}:
            name = "before / after"
        key = name.lower()
        if key in seen_names:
            if desc and desc not in seen_names[key]["description"]:
                seen_names[key]["description"] = (
                    seen_names[key]["description"] + "\n\n" + desc
                ).strip()
            continue
        item = {"name": name, "description": desc}
        seen_names[key] = item
        merged.append(item)

    primary = [b for b in merged if b["name"].lower() not in global_order]
    globals_present = [b for b in merged if b["name"].lower() in global_order]
    globals_present.sort(key=lambda b: global_order.index(b["name"].lower()))
    return primary + globals_present


def render_visibility(item: dict) -> str:
    for key in ("tag_scope", "visibility"):
        candidate = (item.get(key) or "").strip()
        if candidate:
            return candidate
    return "Ei määritetty"


def render_shortdesc(tag: str, item: dict) -> str:
    for key in ("shortdesc", "lead"):
        candidate = norm(item.get(key) or "")
        if candidate:
            return candidate
    return f"{tag}-tagin yleiskuvaus puuttuu datasta. Avaa dokumentaatiosivu."


def render_longdesc(item: dict) -> str:
    for key in ("longdesc", "description"):
        candidate = (item.get(key) or "").strip()
        if candidate:
            return candidate
    return ""


PURPOSES = [
    "Alennuskupongit ja lahjakortit",
    "Bannerit",
    "Globaalit tagit",
    "Haku ja navigointi",
    "Kampanjat",
    "Kanta-asiakasohjelma",
    "Kassa",
    "Laajennukset",
    "Maksu- ja toimitustapatiedot",
    "Ostoskori",
    "Sisältösivut",
    "Tilaukset",
    "Toivelistat",
    "Tuotepaketit",
    "Tuotearvostelut",
    "Tuotelistat",
    "Tuotemerkit",
    "Tuotesuodattimet",
    "Tuotteet",
    "Tuoteryhmät",
    "Tuotevariaatiot",
    "Uutissivut",
]


def build_purpose_styles(purposes: list[str]) -> str:
    """Generate per-purpose pill colors (light + dark theme)."""
    rules: list[str] = []
    n = max(1, len(purposes))
    for i, name in enumerate(sorted(purposes, key=lambda x: x.lower())):
        hue = round((360 / n) * i)
        bg = f"hsl({hue}, 60%, 92%)"
        border = f"hsl({hue}, 45%, 72%)"
        color = f"hsl({hue}, 55%, 22%)"
        dbg = f"hsl({hue}, 38%, 20%)"
        dborder = f"hsl({hue}, 42%, 36%)"
        dcolor = f"hsl({hue}, 70%, 82%)"
        safe = name.replace('"', '\\"')
        rules.append(
            f'.tag-card__purpose-badge[data-purpose="{safe}"] {{'
            f' background: {bg}; border-color: {border}; color: {color};'
            f' }}'
        )
        rules.append(
            f'html[data-theme="dark"] .tag-card__purpose-badge[data-purpose="{safe}"] {{'
            f' background: {dbg}; border-color: {dborder}; color: {dcolor};'
            f' }}'
        )
    return "\n    ".join(rules)


def purpose_from_url(url: str) -> str:
    u = url.lower()
    mapping = [
        ("toivelista", "Toivelistat"),
        ("wishlist", "Toivelistat"),
        ("kampanj", "Kampanjat"),
        ("review", "Tuotearvostelut"),
        ("arvostelu", "Tuotearvostelut"),
        ("checkout", "Kassa"),
        ("kassa", "Kassa"),
        ("order", "Tilaukset"),
        ("tilaus", "Tilaukset"),
        ("category", "Tuoteryhmät"),
        ("tuoteryh", "Tuoteryhmät"),
        ("brand", "Tuotemerkit"),
        ("tuotemerk", "Tuotemerkit"),
        ("productset", "Tuotelistat"),
        ("list", "Tuotelistat"),
        ("tuotelista", "Tuotelistat"),
        ("product", "Tuotteet"),
        ("tuote", "Tuotteet"),
        ("news", "Uutissivut"),
        ("uutis", "Uutissivut"),
        ("banner", "Bannerit"),
        ("extension", "Laajennukset"),
        ("laajennu", "Laajennukset"),
        ("coupon", "Alennuskupongit ja lahjakortit"),
        ("giftcard", "Alennuskupongit ja lahjakortit"),
        ("delivery", "Maksu- ja toimitustapatiedot"),
        ("payment", "Maksu- ja toimitustapatiedot"),
        ("shipping", "Maksu- ja toimitustapatiedot"),
        ("cart", "Ostoskori"),
        ("basket", "Ostoskori"),
        ("content", "Sisältösivut"),
        ("infopage", "Sisältösivut"),
        ("filter", "Tuotesuodattimet"),
        ("suodatin", "Tuotesuodattimet"),
        ("variation", "Tuotevariaatiot"),
        ("variaatio", "Tuotevariaatiot"),
        ("bundle", "Tuotepaketit"),
        ("paketti", "Tuotepaketit"),
        ("globaal", "Globaalit tagit"),
        ("helper", "Globaalit tagit"),
        ("minify", "Globaalit tagit"),
        ("doctype", "Globaalit tagit"),
        ("themeurl", "Globaalit tagit"),
        ("notifications", "Globaalit tagit"),
        ("search", "Haku ja navigointi"),
        ("navig", "Haku ja navigointi"),
    ]
    for needle, purpose in mapping:
        if needle in u:
            return purpose
    return "Globaalit tagit"


def tag_inner_name(tag: str) -> str:
    """{FooBar} -> foobar for substring matching."""
    t = (tag or "").strip()
    if t.startswith("{") and t.endswith("}"):
        t = t[1:-1]
    return t.lower()


# Tag name substring -> extra purpose (shown in filter when primary differs, e.g. Campaign* + Globaalit).
# Order: longer / more specific needles first where relevant.
TAG_NAME_EXTRA_PURPOSES: list[tuple[str, str]] = [
    ("toivelista", "Toivelistat"),
    ("wishlist", "Toivelistat"),
    ("campaign", "Kampanjat"),
    ("kampanj", "Kampanjat"),
    ("giftcard", "Alennuskupongit ja lahjakortit"),
    ("coupon", "Alennuskupongit ja lahjakortit"),
    ("discount", "Alennuskupongit ja lahjakortit"),
    ("checkout", "Kassa"),
    ("productset", "Tuotelistat"),
    ("tuotelista", "Tuotelistat"),
    ("variaatio", "Tuotevariaatiot"),
    ("variation", "Tuotevariaatiot"),
    ("tuoteryh", "Tuoteryhmät"),
    ("category", "Tuoteryhmät"),
    ("tuotemerk", "Tuotemerkit"),
    ("brand", "Tuotemerkit"),
    ("arvostelu", "Tuotearvostelut"),
    ("review", "Tuotearvostelut"),
    ("suodatin", "Tuotesuodattimet"),
    ("filter", "Tuotesuodattimet"),
    ("bundle", "Tuotepaketit"),
    ("paketti", "Tuotepaketit"),
    ("search", "Haku ja navigointi"),
    ("navig", "Haku ja navigointi"),
    ("shipping", "Maksu- ja toimitustapatiedot"),
    ("delivery", "Maksu- ja toimitustapatiedot"),
    ("payment", "Maksu- ja toimitustapatiedot"),
    ("infopage", "Sisältösivut"),
    ("content", "Sisältösivut"),
    ("basket", "Ostoskori"),
    ("cart", "Ostoskori"),
    ("tilaus", "Tilaukset"),
    ("order", "Tilaukset"),
    ("kassa", "Kassa"),
    ("extension", "Laajennukset"),
    ("laajennu", "Laajennukset"),
    ("banner", "Bannerit"),
    ("uutis", "Uutissivut"),
    ("news", "Uutissivut"),
    ("tuote", "Tuotteet"),
    ("product", "Tuotteet"),
]


def purpose_categories_for_tag(tag: str, primary: str) -> list[str]:
    """Primary purpose first, then tag-name-derived extras (deduped, order stable)."""
    inner = tag_inner_name(tag)
    out: list[str] = [primary]
    for needle, cat in TAG_NAME_EXTRA_PURPOSES:
        if needle in inner and cat not in out:
            out.append(cat)
    return out


def format_updated_at(value: str | None) -> str:
    """Return a human-readable Finnish date for the 'last updated' badge.

    Accepts ISO-8601 strings; falls back to current UTC time when missing.
    """
    months_fi = [
        "tammikuuta", "helmikuuta", "maaliskuuta", "huhtikuuta",
        "toukokuuta", "kesäkuuta", "heinäkuuta", "elokuuta",
        "syyskuuta", "lokakuuta", "marraskuuta", "joulukuuta",
    ]
    dt: datetime
    if value:
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            dt = datetime.now(timezone.utc)
    else:
        dt = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return f"{dt.day}. {months_fi[dt.month - 1]} {dt.year}"


def build_html(dataset: dict, updated_at_label: str) -> str:
    tags = dataset.get("tags_index", [])
    rows = []
    for t in tags:
        tag = t.get("tag") or ""
        if not tag:
            continue
        structured = t.get("attribute_blocks") or []
        if structured:
            blocks = [
                {"name": normalize_attr_name(b.get("name", "")), "description": (b.get("description") or "").strip()}
                for b in structured
                if (b.get("name") or "").strip()
            ]
        else:
            blocks = attr_blocks_from_text(t.get("attributes", ""), t.get("syntax", ""))
        blocks = merge_global_attrs(blocks)

        primary = purpose_from_url(t.get("url", ""))
        rows.append(
            {
                "tag": tag,
                "url": t.get("url", ""),
                "shortdesc": render_shortdesc(tag, t),
                "longdesc": render_longdesc(t),
                "syntax": short(t.get("syntax", ""), 280),
                "visibility": render_visibility(t),
                "attribute_blocks": blocks,
                "purpose": primary,
                "purpose_categories": purpose_categories_for_tag(tag, primary),
            }
        )

    rows.sort(key=lambda x: x["tag"].lower())
    payload = json.dumps(rows, ensure_ascii=False)
    purpose_payload = json.dumps(sorted(PURPOSES, key=lambda x: x.lower()), ensure_ascii=False)
    stats = {"total": len(rows)}
    purpose_styles = build_purpose_styles(PURPOSES)

    return f"""<!doctype html>
<html lang="fi" data-theme="light">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>MyCashflow cheat sheet</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Lato:wght@400;700;900&display=swap" rel="stylesheet">
  <style>
    :root {{
      --bg: #f6f1e8;
      --panel: #ffffff;
      --muted: #5c7b68;
      --text: #122a1d;
      --line: #e3dccf;
      --accent: #144327;
      --accent-soft: #1f5c39;
      --peach: #fad9b8;
      --peach-strong: #f1bc83;
      --highlight: #b4e4be;
      --highlight-strong: #8fc798;
      --chip: #faf3e8;
      --shadow: 0 1px 2px rgba(20, 67, 39, 0.06), 0 8px 24px rgba(20, 67, 39, 0.08);
      color-scheme: light;
    }}
    html[data-theme="dark"] {{
      --bg: #0c1410;
      --panel: #14221a;
      --muted: #8fb39a;
      --text: #e8f1ec;
      --line: #2a4538;
      --accent: #b4e4be;
      --accent-soft: #8fc798;
      --peach: #3d2e24;
      --peach-strong: #6b4d38;
      --highlight: #1e3d2e;
      --highlight-strong: #2d5a42;
      --chip: #1a2c22;
      --shadow: 0 1px 2px rgba(0, 0, 0, 0.25), 0 10px 28px rgba(0, 0, 0, 0.35);
      color-scheme: dark;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Lato", system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
      background: var(--bg); color: var(--text);
    }}
    .wrap {{ max-width: 1280px; margin: 0 auto; padding: 24px; }}
    h1 {{
      margin: 0 0 8px; font-size: 30px; font-weight: 900;
      color: var(--accent); letter-spacing: -0.01em;
    }}
    .sub {{ color: var(--muted); margin-bottom: 4px; font-size: 14px; }}
    .updated-at {{
      color: var(--muted); font-size: 12px; margin-bottom: 14px;
      text-transform: uppercase; letter-spacing: 0.06em; font-weight: 700;
    }}
    .updated-at__date {{ color: var(--accent); }}
    .page-head {{
      display: flex; justify-content: space-between; align-items: flex-start;
      gap: 16px; flex-wrap: wrap; margin-bottom: 4px;
    }}
    .page-head__titles {{ flex: 1; min-width: 200px; }}
    .theme-toggle {{
      flex-shrink: 0; margin-top: 4px;
      display: inline-flex; align-items: center; gap: 8px;
      padding: 8px 14px; border-radius: 999px; cursor: pointer;
      font-family: inherit; font-size: 13px; font-weight: 700;
      background: var(--chip); color: var(--accent); border: 1px solid var(--line);
      box-shadow: var(--shadow);
      transition: background 120ms ease, border-color 120ms ease, color 120ms ease;
    }}
    .theme-toggle:hover {{
      border-color: var(--accent-soft); background: var(--panel);
    }}
    .theme-toggle:focus-visible {{
      outline: 2px solid var(--peach-strong); outline-offset: 2px;
    }}
    html[data-theme="dark"] .theme-toggle:focus-visible {{
      outline-color: var(--accent);
    }}
    .toolbar {{
      display: grid; grid-template-columns: 1fr auto auto; gap: 10px;
      background: var(--panel); border: 1px solid var(--line); border-radius: 14px; padding: 12px;
      position: sticky; top: 12px; z-index: 2;
      box-shadow: var(--shadow);
    }}
    input, select {{
      background: var(--panel); color: var(--text); border: 1px solid var(--line);
      border-radius: 8px; padding: 8px 10px; font-size: 14px; font-family: inherit;
    }}
    input:focus, select:focus {{
      outline: 2px solid var(--peach-strong); outline-offset: 1px;
      border-color: var(--peach-strong);
    }}
    .pill {{
      display: inline-flex; align-items: center; padding: 6px 10px; border: 1px solid var(--line);
      border-radius: 999px; background: var(--chip); color: var(--accent); font-size: 12px;
    }}
    .stats {{ display: flex; gap: 8px; flex-wrap: wrap; margin: 12px 0 18px; }}
    .grid {{
      display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px;
    }}
    .card {{
      background: var(--panel); border: 1px solid var(--line); border-radius: 14px; padding: 16px;
      box-shadow: var(--shadow);
    }}
    .card div {{
      white-space: normal;
    }}

    .tag-card__header {{
      display: flex; justify-content: space-between; gap: 10px; align-items: center;
    }}
    .tag-card__title {{
      margin: 0; font-weight: 900; font-size: 18px; line-height: 1.25;
      color: var(--accent); letter-spacing: -0.01em;
    }}
    .tag-card__purpose-badge {{ flex-shrink: 0; font-weight: 700; }}
    {purpose_styles}

    .tag-card__section {{
      margin-top: 12px;
    }}
    .tag-card__section:first-of-type {{
      margin-top: 14px;
    }}
    .tag-card__heading {{
      margin: 0; color: var(--muted); font-size: 11px; font-weight: 700;
      letter-spacing: 0.06em; text-transform: uppercase;
    }}
    .tag-card__body {{
      margin: 6px 0 0; color: var(--text); font-size: 13.5px; line-height: 1.5;
      min-height: 45px;
    }}
    .tag-card__attr-list {{
      display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px;
    }}
    .tag-card__attr-trigger {{
      background: var(--peach); border: 1px solid var(--peach-strong); border-radius: 999px;
      padding: 4px 10px; font-size: 12px; color: var(--accent);
      font-family: inherit; font-weight: 700; cursor: pointer;
      transition: background 120ms ease, border-color 120ms ease, color 120ms ease;
    }}
    .tag-card__attr-trigger:hover {{
      background: var(--peach-strong); border-color: var(--accent); color: var(--accent);
    }}
    .tag-card__attr-trigger:disabled {{ cursor: default; opacity: 0.7; }}
    .tag-card__description-trigger,
    .tag-card__visibility-trigger {{
      margin-top: 8px; background: var(--highlight); border: 1px solid var(--highlight-strong);
      border-radius: 999px; padding: 4px 12px; font-size: 12px; color: var(--accent);
      font-family: inherit; font-weight: 700; cursor: pointer;
      transition: background 120ms ease, border-color 120ms ease;
    }}
    .tag-card__description-trigger:hover,
    .tag-card__visibility-trigger:hover {{
      background: var(--highlight-strong); border-color: var(--accent);
    }}
    .tag-card__description-trigger::before {{ content: "Avaa kuvaus"; }}
    .tag-card__visibility-trigger::before {{ content: "Avaa näkyvyys"; }}
    .tag-card__docs-link {{
      display: inline-block; margin-top: 14px; color: var(--accent);
      text-decoration: none; font-weight: 700; font-size: 13px;
      border-bottom: 2px solid var(--peach-strong); padding-bottom: 1px;
    }}
    .tag-card__docs-link:hover {{ border-bottom-color: var(--accent); }}
    .tag-card__empty {{
      margin-top: 6px; font-size: 13px; color: var(--muted); font-style: italic;
    }}

    .modal-backdrop {{
      position: fixed; inset: 0; background: rgba(15, 47, 31, 0.55);
      display: none; align-items: center; justify-content: center; z-index: 10;
      padding: 24px;
    }}
    html[data-theme="dark"] .modal-backdrop {{
      background: rgba(0, 0, 0, 0.72);
    }}
    .modal-backdrop.open {{ display: flex; }}
    .modal {{
      background: var(--panel); border: 1px solid var(--line); border-radius: 16px;
      padding: 22px 24px; max-width: 640px; width: 100%; max-height: 80vh;
      overflow-y: auto; position: relative; box-shadow: var(--shadow);
    }}
    .modal-head {{ display: flex; justify-content: space-between; align-items: center; gap: 12px; }}
    .modal-name {{ font-weight: 900; font-size: 20px; color: var(--accent); letter-spacing: -0.01em; }}
    .modal-close {{
      background: transparent; border: 1px solid var(--line); color: var(--muted);
      border-radius: 8px; padding: 4px 10px; cursor: pointer; font-size: 13px;
      font-family: inherit;
    }}
    .modal-close:hover {{ color: var(--accent); border-color: var(--accent); }}
    .modal-body {{ margin-top: 14px; color: var(--text); font-size: 14px; line-height: 1.55; }}
    .modal-tag {{ color: var(--muted); font-size: 12px; margin-top: 4px; }}

    @media (max-width: 1100px) {{
      .grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
    }}
    @media (max-width: 720px) {{
      .toolbar {{ grid-template-columns: 1fr; }}
      .grid {{ grid-template-columns: 1fr; }}
    }}
  </style>
  <link rel="stylesheet" href="extra.css">
</head>
<body>
  <div class="wrap">
    <div class="page-head">
      <div class="page-head__titles">
        <h1>MyCashflow cheat sheet</h1>
        <div class="sub">Hae tageja, attribuutteja ja kuvausta yhdestä näkymästä.</div>
        <div class="updated-at">Päivitetty viimeksi: <span class="updated-at__date">{updated_at_label}</span></div>
      </div>
      <button type="button" class="theme-toggle" id="themeToggle" aria-pressed="false" title="Vaihda tumma / vaalea teema">
        <span class="theme-toggle__icon" aria-hidden="true">🌙</span>
        <span class="theme-toggle__label">Tumma tila</span>
      </button>
    </div>

    <div class="toolbar">
      <input id="q" type="search" placeholder="Hae tagia, attribuuttia tai kuvausta…" />
      <select id="purpose">
        <option value="">Käyttötarkoitus (kaikki)</option>
      </select>
      <span class="pill" id="count">0 tulosta</span>
    </div>

    <div class="stats">
      <span class="pill">Tagit yhteensä: {stats["total"]}</span>
    </div>

    <div id="grid" class="grid"></div>
  </div>

  <div id="attrModal" class="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="attrModalName">
    <div class="modal">
      <div class="modal-head">
        <div>
          <div class="modal-name" id="attrModalName"></div>
          <div class="modal-tag" id="attrModalTag"></div>
        </div>
        <button type="button" class="modal-close" data-modal-close>Sulje</button>
      </div>
      <div class="modal-body" id="attrModalBody"></div>
    </div>
  </div>

  <script>
    const data = {payload};
    const grid = document.getElementById("grid");
    const purposes = {purpose_payload};
    const q = document.getElementById("q");
    const purpose = document.getElementById("purpose");
    const count = document.getElementById("count");
    const attrModal = document.getElementById("attrModal");
    const attrModalName = document.getElementById("attrModalName");
    const attrModalTag = document.getElementById("attrModalTag");
    const attrModalBody = document.getElementById("attrModalBody");
    const themeToggle = document.getElementById("themeToggle");
    const themeToggleLabel = themeToggle.querySelector(".theme-toggle__label");
    const themeToggleIcon = themeToggle.querySelector(".theme-toggle__icon");

    const THEME_KEY = "mcf-cheat-sheet-theme";

    function applyTheme(mode) {{
      const root = document.documentElement;
      root.dataset.theme = mode;
      const dark = mode === "dark";
      themeToggle.setAttribute("aria-pressed", dark ? "true" : "false");
      themeToggleLabel.textContent = dark ? "Vaalea tila" : "Tumma tila";
      themeToggleIcon.textContent = dark ? "☀️" : "🌙";
      try {{ localStorage.setItem(THEME_KEY, mode); }} catch (e) {{}}
    }}

    function initTheme() {{
      let mode = "light";
      try {{
        const saved = localStorage.getItem(THEME_KEY);
        if (saved === "dark" || saved === "light") mode = saved;
        else if (window.matchMedia("(prefers-color-scheme: dark)").matches) mode = "dark";
      }} catch (e) {{}}
      applyTheme(mode);
    }}

    themeToggle.addEventListener("click", () => {{
      const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
      applyTheme(next);
    }});

    initTheme();

    function esc(s) {{
      return String(s ?? "").replace(/[&<>\"']/g, ch => ({{"&":"&amp;","<":"&lt;",">":"&gt;","\\"":"&quot;","'":"&#39;"}}[ch]));
    }}

    function fillSelect(el, values) {{
      values.forEach(v => {{
        const opt = document.createElement("option");
        opt.value = v;
        opt.textContent = v;
        el.appendChild(opt);
      }});
    }}

    fillSelect(purpose, purposes);

    function attrPillsHtml(blocks, tagName) {{
      const items = (blocks || []).filter(b => (b.name || "").trim());
      if (!items.length) {{
        return `<div class="tag-card__empty">Ei attribuutteja jäsennettävissä.</div>`;
      }}
      return `<div class="tag-card__attr-list">${{items.map((b, i) => `
        <button type="button" class="tag-card__attr-trigger" data-tag="${{esc(tagName)}}" data-idx="${{i}}">${{esc(b.name)}}</button>
      `).join("")}}</div>`;
    }}

    function escHtml(s) {{
      return String(s).replace(/[&<>"']/g, ch => ({{
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
      }})[ch]);
    }}

    function visibilityToHtml(text) {{
      if (!text) return "";
      return escHtml(text).replace(
        /([a-zäöå0-9.,;:!?])\\s+(?=[A-ZÄÖÅ])/g,
        (m, ch) => (ch === "." ? m : ch + "<br><br>")
      );
    }}

    function openModal({{ name, subtitle, body, bodyHtml }}) {{
      attrModalName.textContent = name || "";
      attrModalTag.textContent = subtitle || "";
      if (bodyHtml && bodyHtml.trim()) {{
        attrModalBody.innerHTML = bodyHtml;
      }} else if (body && body.trim()) {{
        attrModalBody.textContent = body;
      }} else {{
        attrModalBody.textContent = "Kuvaus puuttuu. Avaa dokumentaatiosivu.";
      }}
      attrModal.classList.add("open");
    }}

    function closeAttrModal() {{
      attrModal.classList.remove("open");
    }}

    grid.addEventListener("click", (e) => {{
      const attrBtn = e.target.closest("button.tag-card__attr-trigger");
      if (attrBtn) {{
        const tagName = attrBtn.dataset.tag;
        const idx = Number(attrBtn.dataset.idx);
        const row = data.find(r => r.tag === tagName);
        if (!row) return;
        const block = (row.attribute_blocks || [])[idx];
        if (!block) return;
        openModal({{
          name: block.name || "",
          subtitle: tagName ? `${{tagName}}-tagin attribuutti` : "",
          body: block.description || "",
        }});
        return;
      }}

      const descBtn = e.target.closest("button.tag-card__description-trigger");
      if (descBtn) {{
        const tagName = descBtn.dataset.tag;
        const row = data.find(r => r.tag === tagName);
        if (!row) return;
        openModal({{
          name: "Kuvaus",
          subtitle: tagName || "",
          body: row.longdesc || "",
        }});
        return;
      }}

      const visBtn = e.target.closest("button.tag-card__visibility-trigger");
      if (visBtn) {{
        const tagName = visBtn.dataset.tag;
        const row = data.find(r => r.tag === tagName);
        if (!row) return;
        openModal({{
          name: "Näkyvyys",
          subtitle: tagName || "",
          bodyHtml: visibilityToHtml(row.visibility || ""),
        }});
      }}
    }});

    attrModal.addEventListener("click", (e) => {{
      if (e.target === attrModal || e.target.matches("[data-modal-close]")) {{
        closeAttrModal();
      }}
    }});

    document.addEventListener("keydown", (e) => {{
      if (e.key === "Escape" && attrModal.classList.contains("open")) {{
        closeAttrModal();
      }}
    }});

    function render() {{
      const query = q.value.trim().toLowerCase();
      const purposeVal = purpose.value;
      let rows = data.filter(r => {{
        if (purposeVal) {{
          const cats = r.purpose_categories || [r.purpose];
          if (!cats.includes(purposeVal)) return false;
        }}
        if (!query) return true;
        const tag = (r.tag || "").toLowerCase();
        const tagHit = tag.includes(query);
        const restBlob = [
          r.shortdesc, r.longdesc, r.syntax, r.visibility, r.purpose,
          ...((r.purpose_categories || []).join(" ") || ""),
          ...((r.attribute_blocks || []).flatMap(b => [b.name, b.description]))
        ].join(" ").toLowerCase();
        const restHit = restBlob.includes(query);
        return tagHit || restHit;
      }});

      if (query) {{
        function searchScore(r) {{
          const tag = (r.tag || "").toLowerCase();
          const tagHit = tag.includes(query) ? 1 : 0;
          const restBlob = [
            r.shortdesc, r.longdesc, r.syntax, r.visibility, r.purpose,
            ...((r.purpose_categories || []).join(" ") || ""),
            ...((r.attribute_blocks || []).flatMap(b => [b.name, b.description]))
          ].join(" ").toLowerCase();
          const restHit = restBlob.includes(query) ? 1 : 0;
          return tagHit * 3 + restHit;
        }}
        rows.sort((a, b) => {{
          const diff = searchScore(b) - searchScore(a);
          if (diff !== 0) return diff;
          return a.tag.localeCompare(b.tag, "fi");
        }});
      }} else {{
        rows.sort((a, b) => a.tag.localeCompare(b.tag, "fi"));
      }}

      count.textContent = `${{rows.length}} tulosta`;
      grid.innerHTML = rows.map(r => `
        <article class="card tag-card">
          <header class="tag-card__header">
            <h2 class="tag-card__title">${{esc(r.tag)}}</h2>
            <span class="pill tag-card__purpose-badge" data-purpose="${{esc(r.purpose)}}">${{esc(r.purpose)}}</span>
          </header>
          <section class="tag-card__section tag-card__section--purpose" aria-labelledby="purpose-${{esc(r.tag)}}">
            <h3 class="tag-card__heading" id="purpose-${{esc(r.tag)}}">Käyttötarkoitus</h3>
            <p class="tag-card__body">${{esc(r.shortdesc)}}</p>
          </section>
          ${{r.longdesc ? `
          <section class="tag-card__section tag-card__section--description" aria-labelledby="desc-${{esc(r.tag)}}">
            <h3 class="tag-card__heading" id="desc-${{esc(r.tag)}}">Kuvaus</h3>
            <button type="button" class="tag-card__description-trigger" data-tag="${{esc(r.tag)}}"></button>
          </section>` : ""}}
          <section class="tag-card__section tag-card__section--visibility" aria-labelledby="vis-${{esc(r.tag)}}">
            <h3 class="tag-card__heading" id="vis-${{esc(r.tag)}}">Näkyvyys</h3>
            ${{r.visibility && r.visibility !== "Ei määritetty"
              ? `<button type="button" class="tag-card__visibility-trigger" data-tag="${{esc(r.tag)}}"></button>`
              : `<p class="tag-card__body">${{esc(r.visibility || "Ei määritetty")}}</p>`}}
          </section>
          <section class="tag-card__section tag-card__section--attributes" aria-labelledby="attrs-${{esc(r.tag)}}">
            <h3 class="tag-card__heading" id="attrs-${{esc(r.tag)}}">Keskeiset attribuutit</h3>
            ${{attrPillsHtml(r.attribute_blocks, r.tag)}}
          </section>
          <footer class="tag-card__footer">
            <a class="tag-card__docs-link" target="_blank" rel="noopener noreferrer" href="${{esc(r.url)}}">Avaa lähdedokumentaatio</a>
          </footer>
        </article>
      `).join("");
    }}

    [q, purpose].forEach(el => el.addEventListener("input", render));
    render();
  </script>
</body>
</html>
"""


def main() -> None:
    ap = argparse.ArgumentParser(description="Rakenna teemaopas-datasta suomenkielinen cheat sheet HTML")
    ap.add_argument("--input", required=True, help="Path to teemaopas-full.json")
    ap.add_argument("--output", required=True, help="Output HTML path")
    ap.add_argument(
        "--updated-at",
        default=None,
        help="ISO-8601 timestamp shown in the 'Päivitetty viimeksi' badge. Defaults to the input file mtime.",
    )
    args = ap.parse_args()

    in_path = Path(args.input)
    out_path = Path(args.output)
    dataset = json.loads(in_path.read_text(encoding="utf-8"))

    updated_iso = args.updated_at
    if not updated_iso:
        try:
            updated_iso = (
                datetime.fromtimestamp(in_path.stat().st_mtime, tz=timezone.utc).isoformat()
            )
        except OSError:
            updated_iso = None

    html = build_html(dataset, format_updated_at(updated_iso))
    out_path.write_text(html, encoding="utf-8")
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()

