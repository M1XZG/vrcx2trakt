from __future__ import annotations

from vrcx2trakt import diagnostics


def test_write_error_log_creates_timestamped_report(monkeypatch, tmp_path):
    monkeypatch.setenv("VRCX2TRAKT_STATE_DIR", str(tmp_path))

    try:
        raise RuntimeError("test failure")
    except RuntimeError as exc:
        path = diagnostics.write_error_log(exc, context="unit test")

    assert path is not None
    assert path.parent == tmp_path / "logs"
    assert path.name.startswith("error-")
    report = path.read_text(encoding="utf-8")
    assert "Context: unit test" in report
    assert "RuntimeError: test failure" in report
    assert "Version:" in report
