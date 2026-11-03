from __future__ import annotations

from vrcx2trakt import wizard
from vrcx2trakt.trakt_client import TraktAuthError


def test_wizard_auth_error_writes_diagnostic_log(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("VRCX2TRAKT_STATE_DIR", str(tmp_path))

    def fail() -> int:
        raise TraktAuthError("invalid client secret")

    monkeypatch.setattr(wizard, "_run", fail)

    assert wizard.run() == 1

    logs = list((tmp_path / "logs").glob("error-*.log"))
    assert len(logs) == 1
    assert "Context: Setup wizard" in logs[0].read_text(encoding="utf-8")
    assert f"Details logged to {logs[0]}" in capsys.readouterr().err
