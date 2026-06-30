"""Small Trakt.tv API client: device-code auth, token refresh, search, history sync."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import requests

from . import __version__, config


class TraktError(RuntimeError):
    pass


class TraktAPIError(TraktError):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class TraktAuthError(TraktError):
    pass


class TraktClient:
    BASE_URL = "https://api.trakt.tv"

    def __init__(
        self,
        credentials_path: Path | str | None = None,
        token_path: Path | str | None = None,
        *,
        timeout: float = 30.0,
        refresh_margin_seconds: int = 24 * 60 * 60,
    ) -> None:
        self.credentials_path = (
            Path(credentials_path).expanduser() if credentials_path else config.credentials_path()
        )
        self.token_path = (
            Path(token_path).expanduser() if token_path else config.token_path()
        )
        self.timeout = timeout
        self.refresh_margin_seconds = refresh_margin_seconds
        self.session = requests.Session()
        self._last_post_at = 0.0

        creds = self._load_credentials()
        self.client_id = creds["client_id"]
        self.client_secret = creds["client_secret"]
        self.token = self._load_token()

    @staticmethod
    def credentials_exist() -> bool:
        return config.credentials_path().exists()

    @staticmethod
    def token_exists() -> bool:
        return config.token_path().exists()

    @staticmethod
    def save_credentials(client_id: str, client_secret: str) -> Path:
        """Persist Trakt app credentials into the config directory (mode 600)."""
        config.ensure_config_dir()
        path = config.config_dir() / "credentials.json"
        data = {"client_id": str(client_id).strip(), "client_secret": str(client_secret).strip()}
        tmp = path.with_name(path.name + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
            fh.write("\n")
        os.replace(tmp, path)
        if not config.is_windows():
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
        return path

    def login(self) -> dict[str, Any]:
        code_resp = self._oauth_post_raw("/oauth/device/code", {"client_id": self.client_id})
        if code_resp.status_code != 200:
            self._raise_for_response(code_resp, "Could not start Trakt device authorization")

        code_data = self._json_response(code_resp)
        device_code = code_data["device_code"]
        user_code = code_data["user_code"]
        verification_url = code_data.get("verification_url") or "https://trakt.tv/activate"
        expires_in = int(code_data.get("expires_in") or 600)
        interval = max(1, int(code_data.get("interval") or 5))
        deadline = time.time() + expires_in

        print("Authorize this application with Trakt:")
        print(f"  Visit: {verification_url}")
        print(f"  Enter code: {user_code}")
        print(f"  Convenience URL: https://trakt.tv/activate/{user_code}")
        print("Waiting for authorization...")

        already_used_reported = False
        while time.time() < deadline:
            sleep_for = min(interval, max(0.0, deadline - time.time()))
            if sleep_for:
                time.sleep(sleep_for)

            resp = self._oauth_post_raw(
                "/oauth/device/token",
                {
                    "code": device_code,
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                },
            )

            if resp.status_code == 200:
                token = self._json_response(resp)
                self._save_token(token)
                print("Trakt authorization complete.")
                return self.token or token
            if resp.status_code == 400:
                continue
            if resp.status_code == 404:
                raise TraktAuthError("Trakt device code is invalid. Start login again.")
            if resp.status_code == 409:
                if not already_used_reported:
                    print("Trakt reports this device code was already used; waiting for confirmation...")
                    already_used_reported = True
                continue
            if resp.status_code == 410:
                raise TraktAuthError("Trakt device code expired. Run login again.")
            if resp.status_code == 418:
                raise TraktAuthError("Trakt authorization was denied.")
            if resp.status_code == 429:
                retry_after = self._retry_after_seconds(resp)
                interval = max(interval * 2, int(retry_after or 0), 1)
                continue

            self._raise_for_response(resp, "Trakt device authorization failed")

        raise TraktAuthError("Trakt device authorization timed out. Run login again.")

    def start_device_code(self) -> dict[str, Any]:
        """Begin the device flow and return the user/device codes (for GUI use)."""
        resp = self._oauth_post_raw("/oauth/device/code", {"client_id": self.client_id})
        if resp.status_code != 200:
            self._raise_for_response(resp, "Could not start Trakt device authorization")
        return self._json_response(resp)

    def poll_device_token(self, device_code: str) -> dict[str, Any] | None:
        """Poll once for a device token. Returns the saved token, or None if pending.

        Raises TraktAuthError on terminal failures (expired/denied/invalid).
        """
        resp = self._oauth_post_raw(
            "/oauth/device/token",
            {
                "code": device_code,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
        )
        if resp.status_code == 200:
            self._save_token(self._json_response(resp))
            return self.token
        if resp.status_code in (400, 409, 429):
            return None
        if resp.status_code == 404:
            raise TraktAuthError("Trakt device code is invalid. Start login again.")
        if resp.status_code == 410:
            raise TraktAuthError("Trakt device code expired. Run login again.")
        if resp.status_code == 418:
            raise TraktAuthError("Trakt authorization was denied.")
        self._raise_for_response(resp, "Trakt device authorization failed")
        return None

    def ensure_auth(self) -> dict[str, Any]:
        if not self.token:
            return self.login()
        if self._token_needs_refresh(self.token):
            self._refresh()
        if not self.token or not self.token.get("access_token"):
            raise TraktAuthError("Trakt token cache is missing an access token. Run login again.")
        return self.token

    def search_movie(self, title: str, year: int | str | None = None) -> dict[str, Any] | None:
        params: dict[str, Any] = {"query": title, "limit": 5}
        if year:
            params["years"] = str(year)

        results = self._request("GET", "/search/movie", params=params, auth=False)
        if not results:
            return None

        chosen = results[0]
        if year is not None:
            target_year = int(year)
            chosen = next(
                (item for item in results if (item.get("movie") or {}).get("year") == target_year),
                chosen,
            )

        movie = chosen.get("movie") or {}
        ids = movie.get("ids") or {}
        return {
            "trakt_id": ids.get("trakt"),
            "title": movie.get("title"),
            "year": movie.get("year"),
            "slug": ids.get("slug"),
            "score": chosen.get("score"),
            "imdb": ids.get("imdb"),
            "tmdb": ids.get("tmdb"),
        }

    def search_show(self, title: str) -> dict[str, Any] | None:
        results = self._request("GET", "/search/show", params={"query": title, "limit": 5}, auth=False)
        if not results:
            return None

        chosen = results[0]
        show = chosen.get("show") or {}
        ids = show.get("ids") or {}
        return {
            "trakt_id": ids.get("trakt"),
            "title": show.get("title"),
            "year": show.get("year"),
            "slug": ids.get("slug"),
            "ids": ids,
        }

    def resolve_episode(
        self,
        show_title: str,
        season: int | str | None,
        episode: int | str | None,
    ) -> dict[str, Any] | None:
        if season is None or episode is None:
            return None

        show = self.search_show(show_title)
        if not show:
            return None

        show_ref = show.get("slug") or show.get("trakt_id")
        if not show_ref:
            return None

        try:
            ep = self._request(
                "GET",
                f"/shows/{show_ref}/seasons/{int(season)}/episodes/{int(episode)}",
                auth=False,
            )
        except TraktAPIError as exc:
            if exc.status_code == 404:
                return None
            raise

        ids = ep.get("ids") or {}
        return {
            "show_trakt_id": show.get("trakt_id"),
            "episode_trakt_id": ids.get("trakt"),
            "show_title": show.get("title"),
            "season": ep.get("season"),
            "number": ep.get("number"),
            "episode_title": ep.get("title"),
        }

    def add_history(
        self,
        movies: list[dict[str, Any]] | None = None,
        episodes: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {}
        movie_items = self._history_items(movies or [])
        episode_items = self._history_items(episodes or [])
        if movie_items:
            body["movies"] = movie_items
        if episode_items:
            body["episodes"] = episode_items
        if not body:
            return {"added": {}, "not_found": {}}

        response = self._request("POST", "/sync/history", json_body=body, auth=True)
        return {
            "added": response.get("added", {}),
            "not_found": response.get("not_found", {}),
        }

    def get_history(
        self,
        media_type: str = "movies",
        start_at: str | None = None,
        end_at: str | None = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        page = 1
        while True:
            params: dict[str, Any] = {"page": page, "limit": limit}
            if start_at:
                params["start_at"] = start_at
            if end_at:
                params["end_at"] = end_at

            data, resp = self._request(
                "GET",
                f"/sync/history/{media_type}",
                params=params,
                auth=True,
                return_response=True,
            )
            if data:
                items.extend(data)

            page_count = int(resp.headers.get("X-Pagination-Page-Count") or "1")
            if page >= page_count or not data:
                break
            page += 1

        return items

    def whoami(self) -> dict[str, Any]:
        return self._request("GET", "/users/me", auth=True)

    def _request(
        self,
        method: str,
        path: str,
        *,
        auth: bool = False,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        retry_auth: bool = True,
        max_retries: int = 3,
        return_response: bool = False,
    ) -> Any:
        url = path if path.startswith("http") else f"{self.BASE_URL}{path}"
        method_upper = method.upper()
        refreshed_after_401 = False

        for attempt in range(max_retries + 1):
            headers = self._headers(auth=auth)
            if method_upper == "POST":
                self._respect_post_rate_limit()

            resp = self.session.request(
                method_upper,
                url,
                params=params,
                json=json_body,
                headers=headers,
                timeout=self.timeout,
            )
            if method_upper == "POST":
                self._last_post_at = time.monotonic()

            if resp.status_code == 401 and auth and retry_auth and not refreshed_after_401:
                self._refresh()
                refreshed_after_401 = True
                continue

            if resp.status_code == 429 and attempt < max_retries:
                time.sleep(self._retry_after_seconds(resp) or 1.0)
                continue

            if 200 <= resp.status_code < 300:
                data = self._json_response(resp)
                return (data, resp) if return_response else data

            self._raise_for_response(resp)

        raise TraktAPIError("Trakt request failed after retries")

    def _refresh(self) -> dict[str, Any]:
        if not self.token or not self.token.get("refresh_token"):
            raise TraktAuthError("Trakt token cache is missing a refresh token. Run login again.")

        resp = self._oauth_post_raw(
            "/oauth/token",
            {
                "refresh_token": self.token["refresh_token"],
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "redirect_uri": "urn:ietf:wg:oauth:2.0:oob",
                "grant_type": "refresh_token",
            },
        )
        if resp.status_code != 200:
            self._raise_for_response(resp, "Could not refresh Trakt token. Run login again.")

        new_token = self._json_response(resp)
        self._save_token(new_token)
        return self.token or new_token

    def _headers(self, *, auth: bool) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "trakt-api-version": "2",
            "trakt-api-key": self.client_id,
            "User-Agent": f"vrcx2trakt/{__version__}",
        }
        if auth:
            token = self.ensure_auth()
            headers["Authorization"] = f"Bearer {token['access_token']}"
        return headers

    def _load_credentials(self) -> dict[str, str]:
        try:
            with self.credentials_path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
        except FileNotFoundError as exc:
            raise TraktAuthError(f"Missing Trakt credentials file: {self.credentials_path}") from exc

        client_id = data.get("client_id")
        client_secret = data.get("client_secret")
        if not client_id or not client_secret:
            raise TraktAuthError(
                f"Trakt credentials file must contain client_id and client_secret: {self.credentials_path}"
            )
        return {"client_id": str(client_id), "client_secret": str(client_secret)}

    def _load_token(self) -> dict[str, Any] | None:
        try:
            with self.token_path.open("r", encoding="utf-8") as fh:
                return json.load(fh)
        except FileNotFoundError:
            return None

    def _save_token(self, token: dict[str, Any]) -> None:
        current = self.token or {}
        saved = {
            "access_token": token.get("access_token"),
            "refresh_token": token.get("refresh_token"),
            "created_at": int(token.get("created_at") or time.time()),
            "expires_in": int(token.get("expires_in") or current.get("expires_in") or 0),
            "scope": token.get("scope", current.get("scope", "")),
        }
        if not saved["access_token"] or not saved["refresh_token"]:
            raise TraktAuthError("Trakt token response did not include access and refresh tokens.")

        # Always save tokens into the (writable) primary config dir, even when the
        # client was constructed from the legacy credentials location.
        config.ensure_config_dir()
        target = config.config_dir() / "token.json"
        tmp_path = target.with_name(f"{target.name}.tmp")
        fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(saved, fh, indent=2, sort_keys=True)
            fh.write("\n")
        os.replace(tmp_path, target)
        if not config.is_windows():
            try:
                os.chmod(target, 0o600)
            except OSError:
                pass
        self.token_path = target
        self.token = saved

    def _token_needs_refresh(self, token: dict[str, Any]) -> bool:
        created_at = float(token.get("created_at") or 0)
        expires_in = float(token.get("expires_in") or 0)
        if not created_at or not expires_in:
            return True
        margin = min(float(self.refresh_margin_seconds), max(300.0, expires_in * 0.1))
        return time.time() >= created_at + expires_in - margin

    def _oauth_post_raw(self, path: str, body: dict[str, Any]) -> requests.Response:
        self._respect_post_rate_limit()
        resp = self.session.post(
            f"{self.BASE_URL}{path}",
            json=body,
            headers=self._headers(auth=False),
            timeout=self.timeout,
        )
        self._last_post_at = time.monotonic()
        return resp

    def _respect_post_rate_limit(self) -> None:
        elapsed = time.monotonic() - self._last_post_at
        if self._last_post_at and elapsed < 1.0:
            time.sleep(1.0 - elapsed)

    def _retry_after_seconds(self, resp: requests.Response) -> float | None:
        retry_after = resp.headers.get("Retry-After")
        if not retry_after:
            return None
        try:
            return max(0.0, float(retry_after))
        except ValueError:
            return None

    def _history_items(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        formatted: list[dict[str, Any]] = []
        for item in items:
            if "ids" in item and "watched_at" in item:
                formatted.append(item)
                continue

            trakt_id = item.get("trakt_id") or item.get("trakt")
            watched_at = item.get("watched_at")
            if not trakt_id or not watched_at:
                raise ValueError(
                    "History items must include watched_at and trakt_id/trakt, or already contain ids."
                )
            formatted.append({"watched_at": watched_at, "ids": {"trakt": int(trakt_id)}})
        return formatted

    def _json_response(self, resp: requests.Response) -> Any:
        if resp.status_code == 204 or not resp.content:
            return None
        try:
            return resp.json()
        except ValueError as exc:
            raise TraktAPIError(
                f"Trakt returned non-JSON response with HTTP {resp.status_code}", resp.status_code
            ) from exc

    def _raise_for_response(self, resp: requests.Response, prefix: str = "Trakt request failed") -> None:
        detail = ""
        try:
            data = resp.json()
        except ValueError:
            text = resp.text.strip()
            data = text[:300] if text else None

        if isinstance(data, dict):
            detail = data.get("error_description") or data.get("error") or data.get("message") or ""
        elif data:
            detail = str(data)

        message = f"{prefix}: HTTP {resp.status_code}"
        if detail:
            message = f"{message} ({detail})"
        raise TraktAPIError(message, resp.status_code)


def _print_json(data: Any) -> None:
    print(json.dumps(data, indent=2, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Small Trakt.tv client for VRCX watched-history sync.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("login", help="Authorize with Trakt using device-code flow.")
    subparsers.add_parser("whoami", help="Show the authenticated Trakt user.")

    search_parser = subparsers.add_parser("search", help="Search Trakt for a movie.")
    search_parser.add_argument("title", help="Movie title to search for.")
    search_parser.add_argument("--year", type=int, help="Release year to prefer.")

    args = parser.parse_args(argv)
    client = TraktClient()

    try:
        if args.command == "login":
            client.login()
            return 0
        if args.command == "whoami":
            _print_json(client.whoami())
            return 0
        if args.command == "search":
            result = client.search_movie(args.title, args.year)
            if not result:
                print("No movie match found.")
                return 1
            _print_json(result)
            return 0
    except TraktError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
