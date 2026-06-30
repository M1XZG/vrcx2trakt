"""Extract VRChat cinema watches from the VRCX database into Trakt sync candidates.

Reads a copy of the live VRCX SQLite database, filters the three cinema
"players" (Popcorn Palace, Movie&Chill, LSMedia), parses each entry into a
title/year, classifies it as movie/episode/unknown, collapses replays into a
single watch, and writes ``candidates.json`` into the working directory.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
from collections import Counter
from pathlib import Path

from . import config

SOURCES = config.SOURCES

EPISODE_PATTERNS = (
    re.compile(r"S(?P<season>\d{1,2})\s*E(?P<episode>\d{1,3})", re.IGNORECASE),
    re.compile(r"Season:?\s*(?P<season>\d+)\s*Episode:?\s*(?P<episode>\d+)", re.IGNORECASE),
    re.compile(r"\bEpisode\s*(?P<episode>\d+)", re.IGNORECASE),
    re.compile(r"\bS(?P<season>\d+)E(?P<episode>\d+)\b", re.IGNORECASE),
)

POPCORN_DATE_RE = re.compile(r"^(?P<title>.*?)\s*-\s*(?P<year>\d{4})-\d{2}-\d{2}\s*$")
YEAR_PARENS_RE = re.compile(r"^(?P<title>.*?)\s*\((?P<year>\d{4})\)\s*$")
QUALITY_SUFFIX_RE = re.compile(
    r"(?:\s*[\[(](?:4K|2160p|1080p|720p|480p|UHD|FHD|HD)[\])]|\s+\b(?:4K|2160p|1080p|720p|480p|UHD|FHD|HD)\b)\s*$",
    re.IGNORECASE,
)
TRAILING_EMPTY_DATE_RE = re.compile(r"\s+-\s*$")


def ensure_parent(path: str | os.PathLike[str]) -> None:
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)


def copy_database(source: str | os.PathLike[str], destination: str | os.PathLike[str]) -> None:
    source = os.fspath(source)
    destination = os.fspath(destination)
    ensure_parent(destination)
    for suffix in ("", "-wal", "-shm"):
        dst = destination + suffix
        if os.path.exists(dst):
            os.remove(dst)

    copied_main = False
    for suffix in ("", "-wal", "-shm"):
        src = source + suffix
        dst = destination + suffix
        if os.path.exists(src):
            shutil.copy2(src, dst)
            if suffix == "":
                copied_main = True

    if not copied_main:
        raise FileNotFoundError("database not found: %s" % source)


def open_readonly(path: str | os.PathLike[str]) -> sqlite3.Connection:
    uri = "file:%s?mode=ro" % os.path.abspath(os.fspath(path))
    return sqlite3.connect(uri, uri=True)


def clean_spaces(value):
    return re.sub(r"\s+", " ", (value or "").strip())


def strip_quality_tags(title):
    title = clean_spaces(title)
    while True:
        updated = QUALITY_SUFFIX_RE.sub("", title).strip()
        if updated == title:
            return updated
        title = updated


def clean_unknown_title(raw_name):
    title = clean_spaces(raw_name)
    title = TRAILING_EMPTY_DATE_RE.sub("", title).strip()
    return title


def maybe_int(value):
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def parse_episode(raw_name):
    for pattern in EPISODE_PATTERNS:
        match = pattern.search(raw_name)
        if not match:
            continue

        show = raw_name[:match.start()].strip()
        show = re.sub(r"\s*[-–—:]\s*$", "", show).strip()
        show = clean_spaces(show) or clean_unknown_title(raw_name)
        episode = {
            "show": show,
            "season": maybe_int(match.groupdict().get("season")),
            "episode": maybe_int(match.groupdict().get("episode")),
        }
        return strip_quality_tags(show), episode
    return None, None


def parse_video_name(source, raw_name):
    raw_name = raw_name or ""
    episode_title, episode = parse_episode(raw_name)
    if episode:
        return episode_title, None, "episode", episode

    if source == "PopcornPalace":
        match = POPCORN_DATE_RE.match(raw_name)
        if match:
            title = strip_quality_tags(match.group("title"))
            return title, int(match.group("year")), "movie", None
    elif source in ("Movie&Chill", "LSMedia"):
        match = YEAR_PARENS_RE.match(raw_name)
        if match:
            title = clean_spaces(match.group("title"))
            return title, int(match.group("year")), "movie", None

    return clean_unknown_title(raw_name), None, "unknown", None


def world_prefix(location):
    location = location or ""
    candidate = location.split(":", 1)[0]
    if candidate.startswith("wrld_"):
        return candidate
    return ""


def prefer_world(existing, candidate):
    if not existing:
        return candidate
    if candidate[1] and not existing[1]:
        return candidate
    return existing


def load_world_maps(conn):
    by_world_id = {}
    by_location = {}
    cursor = conn.execute(
        "SELECT COALESCE(location, ''), COALESCE(world_id, ''), COALESCE(world_name, '') "
        "FROM gamelog_location"
    )
    for location, stored_world_id, world_name in cursor:
        prefix = world_prefix(location)
        world_id = stored_world_id or prefix
        if world_id:
            by_world_id[world_id] = prefer_world(by_world_id.get(world_id), (world_id, world_name))
        if location:
            by_location[location] = prefer_world(by_location.get(location), (world_id, world_name))
    return by_world_id, by_location


def resolve_world(location, by_world_id, by_location):
    prefix = world_prefix(location)
    if prefix and prefix in by_world_id:
        return by_world_id[prefix]
    if location in by_location:
        return by_location[location]
    return "", ""


def watched_date(created_at):
    created_at = created_at or ""
    if "T" in created_at:
        return created_at.split("T", 1)[0]
    return created_at[:10]


def fetch_rows(conn):
    placeholders = ",".join("?" for _ in SOURCES)
    query = (
        "SELECT id, COALESCE(created_at, ''), COALESCE(video_name, ''), "
        "video_id, COALESCE(location, '') "
        "FROM gamelog_video_play "
        "WHERE video_id IN (%s) "
        "ORDER BY created_at ASC, id ASC" % placeholders
    )
    return conn.execute(query, SOURCES).fetchall()


def collapse_rows(rows, by_world_id, by_location):
    raw_counts = Counter()
    collapsed = {}

    for row_id, created_at, raw_name, source, location in rows:
        raw_counts[source] += 1
        parsed_title, parsed_year, media_type, episode = parse_video_name(source, raw_name)
        date = watched_date(created_at)
        world_id, world_name = resolve_world(location, by_world_id, by_location)
        key = (source, parsed_title, parsed_year, date)

        candidate = {
            "source": source,
            "watched_at": created_at,
            "watched_date": date,
            "raw_name": raw_name,
            "parsed_title": parsed_title,
            "parsed_year": parsed_year,
            "media_type": media_type,
            "episode": episode,
            "world_id": world_id,
            "world_name": world_name,
            "play_count": 1,
            "row_ids": [row_id],
        }

        if key not in collapsed:
            collapsed[key] = candidate
            continue

        existing = collapsed[key]
        existing["play_count"] += 1
        existing["row_ids"].append(row_id)
        if created_at < existing["watched_at"]:
            candidate["play_count"] = existing["play_count"]
            candidate["row_ids"] = existing["row_ids"]
            collapsed[key] = candidate

    candidates = list(collapsed.values())
    candidates.sort(key=lambda item: (item["watched_at"], item["source"], item["parsed_title"]))
    return candidates, raw_counts


def write_json(path, candidates):
    ensure_parent(path)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(candidates, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def summary_text(raw_counts, candidates, out_path) -> str:
    media_counts = Counter(item["media_type"] for item in candidates)
    with_year = sum(1 for item in candidates if item["parsed_year"] is not None)
    without_year = len(candidates) - with_year

    lines = ["Raw rows per source:"]
    for source in SOURCES:
        lines.append("  %s: %d" % (source, raw_counts[source]))
    lines.append("Collapsed candidates: %d" % len(candidates))
    lines.append("Counts by media_type:")
    for media_type in ("movie", "episode", "unknown"):
        lines.append("  %s: %d" % (media_type, media_counts[media_type]))
    lines.append("Year counts:")
    lines.append("  with_year: %d" % with_year)
    lines.append("  without_year: %d" % without_year)
    lines.append("Example parsed titles:")
    seen = set()
    examples = []
    for item in candidates:
        title = item["parsed_title"]
        if title in seen:
            continue
        seen.add(title)
        suffix = " (%s)" % item["parsed_year"] if item["parsed_year"] is not None else ""
        examples.append("  - %s%s [%s/%s]" % (title, suffix, item["media_type"], item["source"]))
        if len(examples) == 15:
            break
    lines.extend(examples)
    lines.append("Wrote: %s" % out_path)
    return "\n".join(lines)


def run_extract(
    db: str | os.PathLike[str] | None = None,
    out: str | os.PathLike[str] | None = None,
    *,
    no_copy: bool = False,
) -> dict:
    """Run extraction end to end. Returns a result dict with paths and summary.

    ``db`` may be omitted to auto-detect the VRCX database. When ``no_copy`` is
    True the given ``db`` is read directly instead of being copied first.
    """
    out_path = Path(out) if out else config.candidates_path()
    copy_path = config.db_copy_path()

    if no_copy:
        db_path = Path(db) if db else copy_path
    else:
        source_db = config.resolve_vrcx_db(db)
        db_path = copy_path
        copy_database(source_db, db_path)

    conn = open_readonly(db_path)
    try:
        by_world_id, by_location = load_world_maps(conn)
        rows = fetch_rows(conn)
        candidates, raw_counts = collapse_rows(rows, by_world_id, by_location)
    finally:
        conn.close()

    write_json(out_path, candidates)
    return {
        "out_path": str(out_path),
        "candidates": candidates,
        "raw_counts": dict(raw_counts),
        "summary": summary_text(raw_counts, candidates, out_path),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Extract VRCX cinema watches into Trakt sync candidates."
    )
    parser.add_argument("--db", help="source VRCX DB path (auto-detected if omitted)")
    parser.add_argument("--out", help="output JSON path (default: state dir candidates.json)")
    parser.add_argument("--no-copy", action="store_true",
                        help="skip copying and read an existing DB copy")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = run_extract(db=args.db, out=args.out, no_copy=args.no_copy)
    print(result["summary"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
