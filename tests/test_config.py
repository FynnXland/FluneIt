"""Where settings live, and that they survive crashes and broken files."""
import json
import os

import pytest


def test_default_location_is_the_user_folder(app, monkeypatch, tmp_path):
    monkeypatch.delenv("FLUNEIT_HOME", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setattr(app, "APP_DIR", str(tmp_path / "program"))
    os.makedirs(tmp_path / "program")
    path = app._initial_config_file()
    assert path.startswith(str(tmp_path / ("local" if app.IS_WINDOWS else "state")))


def test_config_next_to_the_program_means_portable_mode(app, monkeypatch, tmp_path):
    monkeypatch.delenv("FLUNEIT_HOME", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    program = tmp_path / "program"
    program.mkdir()
    (program / "config.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(app, "APP_DIR", str(program))
    assert app._initial_config_file() == str(program / "config.json")


def test_fluneit_home_wins_over_portable_mode(app, monkeypatch, tmp_path):
    program = tmp_path / "program"
    program.mkdir()
    (program / "config.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(app, "APP_DIR", str(program))
    monkeypatch.setenv("FLUNEIT_HOME", str(tmp_path / "home"))
    assert app._initial_config_file() == str(tmp_path / "home" / "config.json")


def test_missing_options_are_filled_in(app, fresh_config):
    path = fresh_config / "config.json"
    path.write_text(json.dumps({"schrittweite_prozent": 7}), encoding="utf-8")
    cfg = app.load_config()
    assert cfg["schrittweite_prozent"] == 7
    assert cfg["effekte_aktiv"] is False                # effects are opt-in
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert set(app.DEFAULT_CONFIG) <= set(saved)


def test_unknown_options_are_dropped(app, fresh_config):
    path = fresh_config / "config.json"
    path.write_text(json.dumps({"hotkeys": [{"taste": "1"}]}), encoding="utf-8")
    assert "hotkeys" not in app.load_config()


@pytest.mark.parametrize("content", ["{not json", "[1, 2, 3]"])
def test_a_broken_file_is_kept_aside_not_overwritten(app, fresh_config, content):
    path = fresh_config / "config.json"
    path.write_text(content, encoding="utf-8")
    cfg = app.load_config()
    assert cfg == app.DEFAULT_CONFIG
    backup = fresh_config / "config.json.defekt"
    assert backup.read_text(encoding="utf-8") == content


def test_writing_is_atomic_and_leaves_no_temp_file(app, fresh_config):
    assert app._write_config({"a": 1})
    assert json.loads((fresh_config / "config.json").read_text(encoding="utf-8")) == {"a": 1}
    assert not (fresh_config / "config.json.tmp").exists()


def test_hidden_apps_are_stored_without_exe(app, fresh_config):
    path = fresh_config / "config.json"
    path.write_text(json.dumps({"ausgeblendete_apps": ["Steam.exe", "steam", "game.exe"]}),
                    encoding="utf-8")
    assert app.load_config()["ausgeblendete_apps"] == ["steam", "game"]
