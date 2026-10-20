"""Key combinations, the update check and autostart, without touching the system."""
import io
import json
import sys
import urllib.error

import pytest


# ------------------------------------------------------------------ keys

@pytest.mark.parametrize("spec, expected", [
    ("strg", {0x11}), ("strg+shift", {0x11, 0x10}), ("Alt", {0x12}),
    ("", None), ("aus", None), ("strg+fn", None),
])
def test_parse_modifier_specs(app, spec, expected):
    result = app._parse_mods(spec)
    assert (set(result) if result else None) == expected


def test_the_most_specific_combination_wins(app, monkeypatch):
    monkeypatch.setattr(app, "CONFIG", dict(app.DEFAULT_CONFIG))
    app.apply_config()
    sizes = [len(keys) for keys, _kind in app.HOOK_FUNCS]
    assert sizes == sorted(sizes, reverse=True)
    kinds = {frozenset(k): kind for k, kind in app.HOOK_FUNCS}
    assert kinds[frozenset({0x11})] == "app"
    assert kinds[frozenset({0x11, 0x10})] == "mic"
    assert kinds[frozenset({0x11, 0x12})] == "comm"


# --------------------------------------------------------------- updates

@pytest.mark.parametrize("version, expected", [
    ("v2.0.0", (2, 0, 0)), ("1.17.0", (1, 17, 0)), ("v2.1.0-beta.1", (2, 1, 0)), ("x", ()),
])
def test_version_tuple(app, version, expected):
    assert app._version_tuple(version) == expected


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _github_answers(monkeypatch, answer):
    import urllib.request

    def fake_urlopen(req, timeout):
        assert req.full_url == "https://api.github.com/repos/FynnXland/FluneIt/releases/latest"
        if isinstance(answer, Exception):
            raise answer
        return _Response(json.dumps(answer).encode())
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)


def test_a_newer_release_is_reported(app, monkeypatch):
    monkeypatch.setattr(app, "__version__", "2.0.0")
    _github_answers(monkeypatch, {"tag_name": "v2.1.0"})
    assert app.check_for_update() == ("neu", "2.1.0")


def test_the_same_release_counts_as_up_to_date(app, monkeypatch):
    monkeypatch.setattr(app, "__version__", "2.0.0")
    _github_answers(monkeypatch, {"tag_name": "v2.0.0"})
    assert app.check_for_update() == ("aktuell", "2.0.0")


def test_no_release_yet_is_not_called_offline(app, monkeypatch):
    _github_answers(monkeypatch, urllib.error.HTTPError("u", 404, "Not Found", None, None))
    state, text = app.check_for_update()
    assert state == "fehler" and "noch keine Version" in text


def test_offline_is_reported(app, monkeypatch):
    _github_answers(monkeypatch, OSError("no network"))
    assert app.check_for_update() == ("fehler", "GitHub nicht erreichbar")


# ------------------------------------------------------------- autostart

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="Windows autostart")


@windows_only
def test_task_definition_never_times_out_and_waits_after_logon(app):
    xml = app._task_xml()
    assert "<ExecutionTimeLimit>PT0S</ExecutionTimeLimit>" in xml   # else Windows ends it after 3 days
    assert "<Delay>PT20S</Delay>" in xml
    assert "<DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>" in xml
    assert "--autostart" in xml


@windows_only
def test_task_definition_from_source_uses_the_module(app, monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert "<Arguments>-m fluneit --autostart</Arguments>" in app._task_xml()


@windows_only
def test_task_definition_escapes_xml(app, monkeypatch):
    monkeypatch.setattr(app, "APP_DIR", r"C:\Tools & More\<FluneIt>")
    xml = app._task_xml()
    assert r"C:\Tools &amp; More\&lt;FluneIt&gt;" in xml


@windows_only
def test_enabling_creates_the_task_and_removes_the_old_shortcut(app, monkeypatch):
    calls = []
    monkeypatch.setattr(app, "_create_task", lambda: calls.append("task") or True)
    monkeypatch.setattr(app, "_remove_lnk", lambda: calls.append("lnk weg") or True)
    assert app.set_autostart(True) is True
    assert calls == ["task", "lnk weg"]


@windows_only
@pytest.mark.parametrize("state, expected", [("aktiv", True), ("deaktiviert", False)])
def test_the_switch_shows_the_real_task_state(app, monkeypatch, state, expected):
    monkeypatch.setattr(app, "_task_state", lambda: state)
    assert app.autostart_enabled() is expected
