"""Guided console wizard for vrcx2trakt."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from . import config, extract, match, push
from .trakt_client import TraktClient, TraktError


def _path_text(path: Path) -> str:
    return str(path.expanduser().resolve(strict=False))


def _username(profile: dict[str, Any]) -> str:
    return (
        str(profile.get("username") or "")
        or str((profile.get("ids") or {}).get("slug") or "")
        or str(profile.get("name") or "")
        or "there"
    )


def _yes_no(prompt: str, *, default: bool = False) -> bool:
    suffix = " [Y/n]: " if default else " [y/N]: "
    answer = input(prompt + suffix).strip().lower()
    if not answer:
        return default
    return answer in {"y", "yes"}


def _prompt_non_empty(prompt: str) -> str:
    while True:
        value = input(prompt).strip()
        if value:
            return value
        print("Please enter a value.")


def _show_paths() -> None:
    detected = config.detect_vrcx_db()
    print("Paths:")
    print(f"  config:      {_path_text(config.config_dir())}")
    print(f"  state:       {_path_text(config.state_dir())}")
    print(f"  credentials: {_path_text(config.credentials_path())}")
    print(f"  token:       {_path_text(config.token_path())}")
    print(f"  VRCX DB:     {_path_text(detected) if detected else 'not found yet'}")
    print()


def _ensure_credentials() -> None:
    if TraktClient.credentials_exist():
        print("Trakt API credentials found.")
        return

    print("First, create a Trakt API app so vrcx2trakt can authorise with Trakt.")
    print("Open this page:")
    print("  https://trakt.tv/oauth/applications/new")
    print("Use this redirect uri:")
    print("  urn:ietf:wg:oauth:2.0:oob")
    print("Then paste the client_id and client_secret below.")
    client_id = _prompt_non_empty("Trakt client_id: ")
    client_secret = _prompt_non_empty("Trakt client_secret: ")
    saved = TraktClient.save_credentials(client_id, client_secret)
    print(f"Saved credentials to {_path_text(saved)}")


def _ensure_login() -> TraktClient:
    client = TraktClient()
    if not TraktClient.token_exists():
        print()
        print("Now we need to authorise this device with Trakt.")
        client.login()

    profile = client.whoami()
    print(f"Hello, {_username(profile)}. Trakt is ready.")
    return client


def _choose_vrcx_db() -> Path:
    detected = config.detect_vrcx_db()
    if detected:
        print()
        print(f"Found VRCX database: {_path_text(detected)}")
        if _yes_no("Use this database?", default=True):
            return detected

    while True:
        value = _prompt_non_empty("Enter the path to VRCX.sqlite3: ")
        candidate = Path(value).expanduser()
        if not candidate.exists():
            print(f"That file was not found: {_path_text(candidate)}")
            continue
        print(f"Selected VRCX database: {_path_text(candidate)}")
        if _yes_no("Use this database?", default=True):
            return candidate


def _progress() -> Any:
    state = {"last": 0}

    def progress(done: int, total: int, label: str) -> None:
        if done == total or done - state["last"] >= 25:
            print(f"  resolved {done}/{total}: {label}")
            state["last"] = done

    return progress


def _show_preview(result: dict[str, Any], *, limit: int = 10) -> None:
    print(f"Would push {result['to_push_movies']} movies and {result['to_push_episodes']} episodes.")
    if result["skipped_remote_dupes"] or result["skipped_local_dupes"]:
        print(
            f"Skipped {result['skipped_local_dupes']} already pushed locally and "
            f"{result['skipped_remote_dupes']} already on Trakt."
        )
    for item in result["preview"][:limit]:
        print(
            f"  {item['trakt_type']:<7} {item['watched_date']}  "
            f"trakt:{item['trakt_id']:<8} {item['trakt_title']}"
        )


def _run() -> int:
    print("vrcx2trakt setup wizard")
    print("=======================")
    print("This wizard will organise your VRCX cinema watches and sync them to Trakt.")
    print()
    _show_paths()

    _ensure_credentials()
    client = _ensure_login()

    db_path = _choose_vrcx_db()

    print()
    print("Extracting watches from VRCX...")
    extract_result = extract.run_extract(db=db_path)
    print(extract_result["summary"])
    print(f"Found {len(extract_result['candidates'])} candidate watches.")

    print()
    if not _yes_no("Resolve candidates against Trakt now?", default=True):
        match_result = match.run_match(live=False)
        print(f"Wrote review CSV to {match_result['out_path']}")
        print("Run `vrcx2trakt match --live` when you are ready to resolve matches.")
        print("All done for now.")
        return 0

    print("Resolving candidates against Trakt...")
    match_result = match.run_match(live=True, client=client, progress=_progress())
    print(f"Wrote review CSV to {match_result['out_path']}")
    print(
        f"Resolved {match_result['stats']['resolved']} items, "
        f"unresolved {match_result['stats']['unresolved']}, "
        f"suggested include {match_result['stats']['included']}."
    )
    print("You can edit the include column: 1 means push, 0 means skip.")
    print("You can also fix any wrong trakt_id values before pushing.")
    input("Press Enter when you've reviewed the CSV (or just continue)... ")

    print()
    print("Checking what would be pushed...")
    dry_run = push.run_push(dry_run=True, check_remote=True, client=client)
    _show_preview(dry_run)

    if _yes_no("Push these watched items to Trakt now?", default=False):
        result = push.run_push(check_remote=True, client=client)
        print()
        print(f"Pushed {result['to_push_movies']} movies and {result['to_push_episodes']} episodes.")
        print("Trakt response:")
        print(json.dumps(result["response"], indent=2))
        if result.get("log_path"):
            print(f"Logged to {result['log_path']}. State now has {result.get('state_keys')} pushed keys.")
    else:
        print("No changes pushed. You can re-run `vrcx2trakt push --check-remote` later.")

    print()
    print("All done. Thanks for using vrcx2trakt.")
    return 0


def run() -> int:
    try:
        return _run()
    except KeyboardInterrupt:
        print("\nCancelled.")
        return 130
    except (TraktError, FileNotFoundError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(run())
