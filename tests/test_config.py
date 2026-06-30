from vrcx2trakt import config


def test_config_dir_honours_override(monkeypatch, tmp_path):
    override = tmp_path / "config"
    monkeypatch.setenv("VRCX2TRAKT_CONFIG_DIR", str(override))

    assert config.config_dir() == override


def test_state_dir_honours_override(monkeypatch, tmp_path):
    override = tmp_path / "state"
    monkeypatch.setenv("VRCX2TRAKT_STATE_DIR", str(override))

    assert config.state_dir() == override


def test_detect_vrcx_db_honours_existing_override(monkeypatch, tmp_path):
    db_path = tmp_path / "VRCX.sqlite3"
    db_path.write_text("", encoding="utf-8")
    monkeypatch.setenv("VRCX_DB", str(db_path))

    assert config.detect_vrcx_db() == db_path
