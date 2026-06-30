"""Push approved VRCX watch records to Trakt watched history.

Reads ``review.csv`` (from match), takes rows where ``include`` is truthy and a
trakt_id is present, and POSTs them to ``/sync/history`` as movies/episodes with
the VRChat watch date as ``watched_at``.

Dedup is our responsibility (Trakt does not dedupe by item+watched_at):
  - a local state file records every (type,id,date) pushed
  - with ``check_remote=True``, existing Trakt history is fetched and used to skip dups

Always preview with ``dry_run=True`` first.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path

from . import config

TRUTHY = {"1", "true", "yes", "y", "x"}


def is_included(value: str) -> bool:
    return str(value).strip().lower() in TRUTHY


def load_state(path: str | os.PathLike[str]) -> set[str]:
    if os.path.exists(path):
        try:
            return set(json.load(open(path, encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            return set()
    return set()


def save_state(path: str | os.PathLike[str], state: set[str]) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    json.dump(sorted(state), open(path, "w", encoding="utf-8"), indent=0)


def dedup_key(trakt_type: str, trakt_id: str | int, watched_date: str) -> str:
    return f"{trakt_type}|{trakt_id}|{watched_date}"


def run_push(
    review_file: str | os.PathLike[str] | None = None,
    state_file: str | os.PathLike[str] | None = None,
    log_file: str | os.PathLike[str] | None = None,
    *,
    dry_run: bool = False,
    check_remote: bool = False,
    client=None,
) -> dict:
    """Push approved rows to Trakt. Returns a result dict describing the outcome."""
    review_path = Path(review_file) if review_file else config.review_path()
    state_path = Path(state_file) if state_file else config.pushed_state_path()
    log_path = Path(log_file) if log_file else config.push_log_path()

    if not review_path.exists():
        raise FileNotFoundError(f"{review_path} not found — run match (live) first.")

    rows = list(csv.DictReader(open(review_path, encoding="utf-8")))
    included = [r for r in rows if is_included(r.get("include", "")) and str(r.get("trakt_id", "")).strip()]
    skipped_no_id = [r for r in rows if is_included(r.get("include", "")) and not str(r.get("trakt_id", "")).strip()]

    state = load_state(state_path)

    # Lazily create a client when we need to talk to Trakt (real push or remote check).
    if client is None and (not dry_run or check_remote):
        from .trakt_client import TraktClient
        client = TraktClient()

    remote_keys: set[str] = set()
    if check_remote and client:
        for mtype, ttype in (("movies", "movie"), ("episodes", "episode")):
            for ev in client.get_history(media_type=mtype):
                obj = ev.get(ttype) or {}
                tid = (obj.get("ids") or {}).get("trakt")
                date = (ev.get("watched_at") or "")[:10]
                if tid and date:
                    remote_keys.add(dedup_key(ttype, tid, date))

    movies, episodes = [], []
    dup_local = dup_remote = 0
    planned_keys: list[str] = []
    for r in included:
        ttype = r["trakt_type"] or ("episode" if r["media_type"] == "episode" else "movie")
        tid = int(str(r["trakt_id"]).strip())
        date = r["watched_date"]
        key = dedup_key(ttype, tid, date)
        if key in state:
            dup_local += 1
            continue
        if key in remote_keys:
            dup_remote += 1
            continue
        if key in planned_keys:
            continue  # de-dup within this batch
        planned_keys.append(key)
        item = {"watched_at": r["watched_at"], "ids": {"trakt": tid}}
        (episodes if ttype == "episode" else movies).append((key, item, r))

    result = {
        "review_rows": len(rows),
        "included": len(included),
        "skipped_no_id": len(skipped_no_id),
        "to_push_movies": len(movies),
        "to_push_episodes": len(episodes),
        "skipped_local_dupes": dup_local,
        "skipped_remote_dupes": dup_remote,
        "remote_history_events": len(remote_keys),
        "preview": [
            {
                "trakt_type": r["trakt_type"],
                "watched_date": r["watched_date"],
                "trakt_id": item["ids"]["trakt"],
                "trakt_title": r["trakt_title"],
            }
            for _, item, r in (movies + episodes)
        ],
        "dry_run": dry_run,
        "pushed": False,
        "response": None,
    }

    if dry_run:
        return result

    if not movies and not episodes:
        result["response"] = {"added": {}, "not_found": {}}
        return result

    resp = client.add_history(
        movies=[i for _, i, _ in movies],
        episodes=[i for _, i, _ in episodes],
    )
    result["response"] = resp
    result["pushed"] = True

    added = resp.get("added", {})
    # Only record dedup keys as pushed if Trakt accepted the corresponding type.
    for key, _, _ in movies:
        if added.get("movies", 0):
            state.add(key)
    for key, _, _ in episodes:
        if added.get("episodes", 0):
            state.add(key)
    save_state(state_path, state)
    result["state_keys"] = len(state)

    os.makedirs(os.path.dirname(os.path.abspath(log_path)), exist_ok=True)
    json.dump({
        "response": resp,
        "pushed_movies": len(movies),
        "pushed_episodes": len(episodes),
        "skipped_local_dupes": dup_local,
        "skipped_remote_dupes": dup_remote,
    }, open(log_path, "w", encoding="utf-8"), indent=2)
    result["log_path"] = str(log_path)
    return result


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Push approved review rows to Trakt history.")
    ap.add_argument("--review", help="review.csv path (default: state dir)")
    ap.add_argument("--state", help="pushed-state.json path (default: state dir)")
    ap.add_argument("--log", help="push-log.json path (default: state dir)")
    ap.add_argument("--dry-run", action="store_true", help="Show what would be pushed; do not POST.")
    ap.add_argument("--check-remote", action="store_true",
                    help="Fetch existing Trakt history and skip items already watched on the same date.")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = run_push(
            review_file=args.review,
            state_file=args.state,
            log_file=args.log,
            dry_run=args.dry_run,
            check_remote=args.check_remote,
        )
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"Review rows: {result['review_rows']} | included with trakt_id: {result['included']} | "
          f"included but no trakt_id: {result['skipped_no_id']}")
    if result["remote_history_events"]:
        print(f"  fetched {result['remote_history_events']} existing remote history events for dedup")
    print(f"  to push: {result['to_push_movies']} movies, {result['to_push_episodes']} episodes "
          f"(skipped {result['skipped_local_dupes']} already-pushed, "
          f"{result['skipped_remote_dupes']} already-on-trakt)")

    if result["dry_run"]:
        print("\n-- DRY RUN preview (first 25) --")
        for item in result["preview"][:25]:
            print(f"  {item['trakt_type']:<7} {item['watched_date']}  "
                  f"trakt:{item['trakt_id']:<8} {item['trakt_title']}")
        print("\nDry run only — nothing pushed. Re-run without --dry-run to push.")
        return 0

    if not result["pushed"]:
        print("Nothing new to push.")
        return 0

    print("\nTrakt response:")
    print(json.dumps(result["response"], indent=2))
    print(f"\nLogged to {result.get('log_path')}. State updated ({result.get('state_keys')} pushed keys).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
