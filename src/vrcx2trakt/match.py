"""Resolve VRCX watched-movie candidates against Trakt and build a review CSV.

Reads ``candidates.json`` (from extract), looks up each candidate on Trakt
(movies via search, TV/anime via show+episode resolution), and writes
``review.csv`` into the working directory. The CSV is review-first: edit the
``include`` column (1=push, 0=skip) and fix any wrong matches before pushing.

Offline mode (default) emits parsed fields only. ``live=True`` enriches each row
with the resolved Trakt id/title/year/score. Results are cached so re-runs don't
re-query Trakt.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from pathlib import Path

from . import config

CSV_HEADER = [
    "include", "source", "watched_date", "watched_at", "media_type",
    "raw_name", "parsed_title", "parsed_year",
    "trakt_type", "trakt_id", "trakt_title", "trakt_year", "match_score", "notes",
]

# Strip a trailing "(YYYY)" and anything after the first " - " to recover the
# bare show name from an episode label like "Toradora - Your Song".
_YEAR_PAREN = re.compile(r"\s*\(\d{3,4}\)\s*$")


def show_name_from_episode(show_field: str) -> str:
    name = show_field.split(" - ", 1)[0].strip()
    name = _YEAR_PAREN.sub("", name).strip()
    return name


def load_cache(path: str | os.PathLike[str]) -> dict:
    if os.path.exists(path):
        try:
            return json.load(open(path, encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_cache(path: str | os.PathLike[str], cache: dict) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    json.dump(cache, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=0)


def cache_key(cand: dict) -> str:
    if cand["media_type"] == "episode":
        ep = cand.get("episode") or {}
        return f"ep|{show_name_from_episode(ep.get('show', ''))}|{ep.get('season')}|{ep.get('episode')}"
    return f"mv|{cand['parsed_title']}|{cand.get('parsed_year')}"


def resolve(client, cand: dict) -> dict | None:
    """Return a normalized match dict, or None if nothing resolved."""
    mt = cand["media_type"]
    if mt == "episode":
        ep = cand.get("episode") or {}
        show = show_name_from_episode(ep.get("show", ""))
        if not show:
            return None
        m = client.resolve_episode(show, ep.get("season"), ep.get("episode"))
        if not m or not m.get("episode_trakt_id"):
            return None
        s, n = m.get("season"), m.get("number")
        label = f"{m.get('show_title')} S{s}E{n}"
        if m.get("episode_title"):
            label += f": {m['episode_title']}"
        return {
            "trakt_type": "episode",
            "trakt_id": m["episode_trakt_id"],
            "trakt_title": label,
            "trakt_year": "",
            "score": "",
        }

    # movie / unknown -> attempt a movie search
    m = client.search_movie(cand["parsed_title"], cand.get("parsed_year"))
    if not m or not m.get("trakt_id"):
        return None
    return {
        "trakt_type": "movie",
        "trakt_id": m["trakt_id"],
        "trakt_title": m.get("title") or "",
        "trakt_year": m.get("year") or "",
        "score": m.get("score") or "",
    }


def suggested_include(cand: dict, match: dict | None) -> int:
    """Default the include flag: confident movies/episodes in, junk/no-match out."""
    if not match:
        return 0
    if cand["media_type"] == "unknown":
        return 0  # likely music/clip; let the user opt in
    if cand["media_type"] == "movie" and cand.get("parsed_year") and match.get("trakt_year"):
        # Year mismatch -> probably wrong film; flag for manual check
        if int(cand["parsed_year"]) != int(match["trakt_year"]):
            return 0
    return 1


def run_match(
    candidates_file: str | os.PathLike[str] | None = None,
    out: str | os.PathLike[str] | None = None,
    cache_file: str | os.PathLike[str] | None = None,
    *,
    live: bool = False,
    use_cache: bool = True,
    client=None,
    progress=None,
) -> dict:
    """Resolve candidates and write the review CSV. Returns a result dict.

    ``progress`` may be a callable ``(done, total, label)`` for UI feedback.
    """
    candidates_path = Path(candidates_file) if candidates_file else config.candidates_path()
    out_path = Path(out) if out else config.review_path()
    cache_path = Path(cache_file) if cache_file else config.match_cache_path()

    if not candidates_path.exists():
        raise FileNotFoundError(f"{candidates_path} not found — run extract first.")
    candidates = json.load(open(candidates_path, encoding="utf-8"))

    cache: dict = load_cache(cache_path) if use_cache else {}
    if live and client is None:
        from .trakt_client import TraktClient
        client = TraktClient()

    rows = []
    stats = {"resolved": 0, "unresolved": 0, "from_cache": 0, "included": 0}
    total = len(candidates)
    for index, cand in enumerate(candidates, start=1):
        match = None
        notes_parts = []
        if cand["media_type"] == "episode":
            ep = cand.get("episode") or {}
            notes_parts.append(
                f"show={show_name_from_episode(ep.get('show',''))} "
                f"S{ep.get('season')}E{ep.get('episode')}"
            )
        if cand.get("play_count", 1) > 1:
            notes_parts.append(f"plays={cand['play_count']}")

        if live:
            key = cache_key(cand)
            if key in cache:
                match = cache[key]
                stats["from_cache"] += 1
            else:
                try:
                    match = resolve(client, cand)
                except Exception as exc:  # noqa: BLE001 - surface but keep going
                    notes_parts.append(f"error:{exc}")
                    match = None
                cache[key] = match
            if match:
                stats["resolved"] += 1
            else:
                stats["unresolved"] += 1
                notes_parts.append("no-trakt-match")

        include = suggested_include(cand, match) if live else 0
        stats["included"] += include
        rows.append({
            "include": include,
            "source": cand["source"],
            "watched_date": cand["watched_date"],
            "watched_at": cand["watched_at"],
            "media_type": cand["media_type"],
            "raw_name": cand["raw_name"],
            "parsed_title": cand["parsed_title"],
            "parsed_year": cand.get("parsed_year") or "",
            "trakt_type": (match or {}).get("trakt_type", ""),
            "trakt_id": (match or {}).get("trakt_id", ""),
            "trakt_title": (match or {}).get("trakt_title", ""),
            "trakt_year": (match or {}).get("trakt_year", ""),
            "match_score": (match or {}).get("score", ""),
            "notes": "; ".join(notes_parts),
        })
        if progress:
            progress(index, total, cand.get("parsed_title", ""))

    if live and use_cache:
        save_cache(cache_path, cache)

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_HEADER)
        w.writeheader()
        w.writerows(rows)

    return {"out_path": str(out_path), "rows": rows, "stats": stats, "live": live}


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Resolve candidates against Trakt -> review CSV.")
    ap.add_argument("--candidates", help="candidates.json path (default: state dir)")
    ap.add_argument("--out", help="review.csv output path (default: state dir)")
    ap.add_argument("--cache", help="match cache path (default: state dir)")
    ap.add_argument("--live", action="store_true",
                    help="Query Trakt to resolve matches (otherwise parsed fields only).")
    ap.add_argument("--no-cache", action="store_true", help="Ignore and overwrite the match cache.")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = run_match(
            candidates_file=args.candidates,
            out=args.out,
            cache_file=args.cache,
            live=args.live,
            use_cache=not args.no_cache,
        )
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    rows, stats = result["rows"], result["stats"]
    print(f"Wrote {len(rows)} rows -> {result['out_path']}")
    if result["live"]:
        print(f"  resolved={stats['resolved']} unresolved={stats['unresolved']} "
              f"(cache hits={stats['from_cache']})")
        print(f"  suggested include=1: {stats['included']}")
        print("\nNEXT: review the CSV (set include=1/0, fix wrong trakt_id), then push.")
    else:
        print("  (offline mode — run with --live to resolve Trakt matches)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
