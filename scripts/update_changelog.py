#!/usr/bin/env python3
"""
Compare two teemaopas-full.json snapshots and append a human-readable changelog entry.

Usage:
  python update_changelog.py \\
    --old teemaopas-full.json \\
    --new teemaopas-full.tmp.json \\
    --out ../docs/changelog.json \\
    --date 2026-05-21T04:17:00Z
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def tags_map(dataset: dict) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for item in dataset.get("tags_index", []):
        tag = (item.get("tag") or "").strip()
        if tag:
            out[tag] = item
    return out


def attr_map(item: dict) -> dict[str, str]:
    blocks = item.get("attribute_blocks") or []
    result: dict[str, str] = {}
    for block in blocks:
        name = norm(block.get("name") or "")
        if name:
            result[name] = norm(block.get("description") or "")
    return result


def snapshot(item: dict) -> dict:
    return {
        "shortdesc": norm(item.get("shortdesc") or ""),
        "longdesc": norm(item.get("longdesc") or ""),
        "syntax": norm(item.get("syntax_block") or item.get("syntax") or ""),
        "visibility": norm(item.get("tag_scope") or item.get("visibility") or ""),
        "attrs": attr_map(item),
    }


def diff_item(old: dict, new: dict) -> list[str]:
    o = snapshot(old)
    n = snapshot(new)
    changes: list[str] = []

    if o["shortdesc"] != n["shortdesc"]:
        changes.append("Short description changed")
    if o["longdesc"] != n["longdesc"]:
        changes.append("Long description changed")
    if o["syntax"] != n["syntax"]:
        changes.append("Syntax updated")
    if o["visibility"] != n["visibility"]:
        changes.append("Visibility updated")

    old_attrs, new_attrs = o["attrs"], n["attrs"]
    for name in sorted(new_attrs):
        if name not in old_attrs:
            changes.append(f"Attribute added: {name}")
        elif old_attrs[name] != new_attrs[name]:
            changes.append(f"Attribute description updated: {name}")
    for name in sorted(old_attrs):
        if name not in new_attrs:
            changes.append(f"Attribute removed: {name}")

    return changes


def format_date_label(iso: str) -> str:
    months = [
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December",
    ]
    text = iso.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        dt = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return f"{dt.day} {months[dt.month - 1]} {dt.year}"


def build_entry(old_data: dict | None, new_data: dict, when_iso: str) -> dict | None:
    new_map = tags_map(new_data)
    old_map = tags_map(old_data) if old_data else {}

    added = sorted(set(new_map) - set(old_map))
    removed = sorted(set(old_map) - set(new_map))
    updated: list[dict] = []

    for tag in sorted(set(old_map) & set(new_map)):
        changes = diff_item(old_map[tag], new_map[tag])
        if changes:
            updated.append({"tag": tag, "changes": changes})

    if not added and not removed and not updated:
        return None

    parts: list[str] = []
    if added:
        parts.append(f"{len(added)} new tag{'s' if len(added) != 1 else ''}")
    if removed:
        parts.append(f"{len(removed)} tag{'s' if len(removed) != 1 else ''} removed")
    if updated:
        parts.append(f"{len(updated)} tag{'s' if len(updated) != 1 else ''} updated")

    return {
        "date": when_iso,
        "date_label": format_date_label(when_iso),
        "summary": ", ".join(parts),
        "added": [{"tag": t, "message": f"New tag {t} appeared in the theme guide."} for t in added],
        "removed": [
            {"tag": t, "message": f"Tag {t} is no longer listed in the theme guide."} for t in removed
        ],
        "updated": updated,
    }


def load_changelog(path: Path) -> dict:
    if not path.is_file():
        return {"entries": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"entries": []}
    if not isinstance(data.get("entries"), list):
        return {"entries": []}
    return data


def main() -> None:
    ap = argparse.ArgumentParser(description="Update cheat sheet changelog from JSON diff")
    ap.add_argument("--new", required=True, help="New teemaopas-full.json path")
    ap.add_argument("--out", required=True, help="Output changelog.json path")
    ap.add_argument("--old", default=None, help="Previous JSON (omit on first run)")
    ap.add_argument("--date", default=None, help="ISO-8601 timestamp for this entry")
    ap.add_argument("--max-entries", type=int, default=24, help="Keep this many entries")
    args = ap.parse_args()

    new_data = json.loads(Path(args.new).read_text(encoding="utf-8"))
    old_data = None
    if args.old and Path(args.old).is_file():
        old_data = json.loads(Path(args.old).read_text(encoding="utf-8"))

    when_iso = args.date or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    entry = build_entry(old_data, new_data, when_iso)

    out_path = Path(args.out)
    changelog = load_changelog(out_path)

    if entry:
        changelog["entries"].insert(0, entry)
        changelog["entries"] = changelog["entries"][: args.max_entries]
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(changelog, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Changelog updated: {entry['summary']}")
    else:
        print("No tag changes detected; changelog file left unchanged.")


if __name__ == "__main__":
    main()
