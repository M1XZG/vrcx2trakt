"""Command-line interface for vrcx2trakt."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import config, extract, match, push
from .trakt_client import TraktAuthError, TraktClient, TraktError


def _path_text(path: Path) -> str:
    return str(path.expanduser().resolve(strict=False))


def _username(profile: dict[str, Any]) -> str:
    return (
        str(profile.get("username") or "")
        or str((profile.get("ids") or {}).get("slug") or "")
        or str(profile.get("name") or "")
        or "unknown"
    )


def _setup(_: argparse.Namespace) -> int:
    print("Create a Trakt API app at:")
    print("  https://trakt.tv/oauth/applications/new")
    print("Use this redirect uri:")
    print("  urn:ietf:wg:oauth:2.0:oob")
    print()

    client_id = input("Trakt client_id: ").strip()
    client_secret = input("Trakt client_secret: ").strip()
    if not client_id or not client_secret:
        print("Error: client_id and client_secret must both be provided.", file=sys.stderr)
        return 1

    saved = TraktClient.save_credentials(client_id, client_secret)
    print(f"Saved Trakt credentials to {_path_text(saved)}")
    print("Next, run `vrcx2trakt login` to authorise this device.")
    return 0


def _login(_: argparse.Namespace) -> int:
    if not TraktClient.credentials_exist():
        print("Error: Trakt credentials are missing. Run `vrcx2trakt setup` first.", file=sys.stderr)
        return 1
    TraktClient().login()
    return 0


def _whoami(_: argparse.Namespace) -> int:
    if not TraktClient.credentials_exist():
        print("Error: Trakt credentials are missing. Run `vrcx2trakt setup` first.", file=sys.stderr)
        return 1
    profile = TraktClient().whoami()
    print(f"Authenticated Trakt user: {_username(profile)}")
    return 0


def _extract(args: argparse.Namespace) -> int:
    result = extract.run_extract(db=args.db, out=args.out, no_copy=args.no_copy)
    print(result["summary"])
    return 0


def _match(args: argparse.Namespace) -> int:
    result = match.run_match(
        candidates_file=args.candidates,
        out=args.out,
        cache_file=args.cache,
        live=args.live,
        use_cache=not args.no_cache,
    )
    rows = result["rows"]
    stats = result["stats"]
    print(f"Wrote {len(rows)} rows to {result['out_path']}")
    if result["live"]:
        print(
            "Stats: "
            f"resolved={stats['resolved']} "
            f"unresolved={stats['unresolved']} "
            f"included={stats['included']} "
            f"from_cache={stats['from_cache']}"
        )
    else:
        print("Offline mode, run with --live to resolve Trakt matches.")
    return 0


def _print_push_summary(result: dict[str, Any]) -> None:
    print(
        f"Review rows: {result['review_rows']} | "
        f"included with trakt_id: {result['included']} | "
        f"included but no trakt_id: {result['skipped_no_id']}"
    )
    if result["remote_history_events"]:
        print(f"  fetched {result['remote_history_events']} existing remote history events for dedup")
    print(
        f"  to push: {result['to_push_movies']} movies, {result['to_push_episodes']} episodes "
        f"(skipped {result['skipped_local_dupes']} already pushed, "
        f"{result['skipped_remote_dupes']} already on Trakt)"
    )

    if result["dry_run"]:
        print()
        print("DRY RUN preview (first 25)")
        for item in result["preview"][:25]:
            print(
                f"  {item['trakt_type']:<7} {item['watched_date']}  "
                f"trakt:{item['trakt_id']:<8} {item['trakt_title']}"
            )
        print()
        print("Dry run only, nothing pushed. Re-run without --dry-run to push.")
        return

    if not result["pushed"]:
        print("Nothing new to push.")
        return

    print()
    print("Trakt response:")
    print(json.dumps(result["response"], indent=2))
    print(f"Logged to {result.get('log_path')}. State updated ({result.get('state_keys')} pushed keys).")


def _push(args: argparse.Namespace) -> int:
    result = push.run_push(
        review_file=args.review,
        state_file=args.state,
        log_file=args.log,
        dry_run=args.dry_run,
        check_remote=args.check_remote,
    )
    _print_push_summary(result)
    return 0


def _sync(_: argparse.Namespace) -> int:
    if not TraktClient.credentials_exist():
        print("Error: Trakt credentials are missing. Run `vrcx2trakt setup` first.", file=sys.stderr)
        return 1
    if not TraktClient.token_exists():
        print("Error: Trakt token is missing. Run `vrcx2trakt login` first.", file=sys.stderr)
        return 1

    client = TraktClient()
    extract_result = extract.run_extract()
    print(f"extract: {len(extract_result['candidates'])} candidates to {extract_result['out_path']}")

    match_result = match.run_match(live=True, client=client)
    stats = match_result["stats"]
    print(
        f"match: {len(match_result['rows'])} rows, "
        f"resolved={stats['resolved']}, unresolved={stats['unresolved']}, "
        f"included={stats['included']} to {match_result['out_path']}"
    )

    push_result = push.run_push(check_remote=True, client=client)
    print(
        f"push: {push_result['to_push_movies']} movies, {push_result['to_push_episodes']} episodes, "
        f"skipped local={push_result['skipped_local_dupes']}, "
        f"skipped remote={push_result['skipped_remote_dupes']}, pushed={push_result['pushed']}"
    )
    return 0


def _wizard(_: argparse.Namespace) -> int:
    from . import wizard

    return wizard.run()


def _gui(_: argparse.Namespace) -> int:
    try:
        from .gui import main as gui_main
    except ImportError as exc:
        print(f"Error: could not start the GUI ({exc}). Is tkinter installed?", file=sys.stderr)
        return 1
    return gui_main()


def _paths(_: argparse.Namespace) -> int:
    detected = config.detect_vrcx_db()
    print(f"config_dir:       {_path_text(config.config_dir())}")
    print(f"state_dir:        {_path_text(config.state_dir())}")
    print(f"credentials_path: {_path_text(config.credentials_path())}")
    print(f"token_path:       {_path_text(config.token_path())}")
    print(f"vrcx_db:          {_path_text(detected) if detected else 'not found'}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vrcx2trakt",
        description="Sync VRCX cinema watches to your Trakt.tv watched history.",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="command")

    setup_parser = subparsers.add_parser("setup", help="save Trakt API app credentials")
    setup_parser.set_defaults(func=_setup)

    login_parser = subparsers.add_parser("login", help="authorise with Trakt using device-code flow")
    login_parser.set_defaults(func=_login)

    whoami_parser = subparsers.add_parser("whoami", help="show the authenticated Trakt username")
    whoami_parser.set_defaults(func=_whoami)

    extract_parser = subparsers.add_parser("extract", help="extract VRCX watches to candidates.json")
    extract_parser.add_argument("--db", help="source VRCX DB path, auto-detected if omitted")
    extract_parser.add_argument("--out", help="output JSON path, defaults to the state dir")
    extract_parser.add_argument("--no-copy", action="store_true", help="read the given DB directly")
    extract_parser.set_defaults(func=_extract)

    match_parser = subparsers.add_parser("match", help="build a review CSV from candidates")
    match_parser.add_argument("--live", action="store_true", help="resolve matches against Trakt")
    match_parser.add_argument("--no-cache", action="store_true", help="ignore the match cache")
    match_parser.add_argument("--candidates", help="candidates.json path, defaults to the state dir")
    match_parser.add_argument("--out", help="review.csv output path, defaults to the state dir")
    match_parser.add_argument("--cache", help="match cache path, defaults to the state dir")
    match_parser.set_defaults(func=_match)

    push_parser = subparsers.add_parser("push", help="push approved review rows to Trakt")
    push_parser.add_argument("--dry-run", action="store_true", help="preview without posting to Trakt")
    push_parser.add_argument("--check-remote", action="store_true", help="skip items already on Trakt")
    push_parser.add_argument("--review", help="review.csv path, defaults to the state dir")
    push_parser.add_argument("--state", help="pushed-state.json path, defaults to the state dir")
    push_parser.add_argument("--log", help="push-log.json path, defaults to the state dir")
    push_parser.set_defaults(func=_push)

    sync_parser = subparsers.add_parser("sync", help="run extract, live match, and remote-checked push")
    sync_parser.set_defaults(func=_sync)

    wizard_parser = subparsers.add_parser("wizard", help="run the guided console wizard")
    wizard_parser.set_defaults(func=_wizard)

    gui_parser = subparsers.add_parser("gui", help="run the graphical interface")
    gui_parser.set_defaults(func=_gui)

    paths_parser = subparsers.add_parser("paths", help="show vrcx2trakt paths and VRCX detection")
    paths_parser.set_defaults(func=_paths)

    return parser


def main(argv: list[str] | None = None) -> int:
    args_list = sys.argv[1:] if argv is None else list(argv)
    if not args_list:
        return _wizard(argparse.Namespace())

    parser = build_parser()
    args = parser.parse_args(args_list)
    if not hasattr(args, "func"):
        parser.print_help()
        return 2

    try:
        return int(args.func(args))
    except (TraktAuthError, TraktError, FileNotFoundError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
