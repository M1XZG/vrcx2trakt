from __future__ import annotations

from vrcx2trakt import cli
from vrcx2trakt.trakt_client import TraktAuthError


def test_cli_auth_error_writes_diagnostic_log(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("VRCX2TRAKT_STATE_DIR", str(tmp_path))

    class FailingClient:
        @staticmethod
        def credentials_exist() -> bool:
            return True

        def __init__(self) -> None:
            raise TraktAuthError("invalid client secret")

    monkeypatch.setattr(cli, "TraktClient", FailingClient)

    assert cli.main(["login"]) == 1

    logs = list((tmp_path / "logs").glob("error-*.log"))
    assert len(logs) == 1
    assert "TraktAuthError: invalid client secret" in logs[0].read_text(encoding="utf-8")
    assert f"Details logged to {logs[0]}" in capsys.readouterr().err
