"""Sandbox for every test.

User folders point to a temporary directory before fluneit is imported, and
everything that would touch the real system (Task Scheduler, the startup
shortcut, the default audio device) makes the test fail hard. A test that
needs one of these replaces it with its own stand-in via monkeypatch.
"""
import os
import pathlib
import sys
import tempfile

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SANDBOX = pathlib.Path(tempfile.mkdtemp(prefix="fluneit_tests_"))

for var in ("APPDATA", "LOCALAPPDATA", "XDG_STATE_HOME", "XDG_CONFIG_HOME"):
    os.environ[var] = str(SANDBOX / var)
    os.makedirs(os.environ[var], exist_ok=True)
# Pins settings and log to the sandbox and switches off portable mode, so a
# config.json in the developer's checkout is never read or written.
os.environ["FLUNEIT_HOME"] = str(SANDBOX / "home")
sys.path.insert(0, str(ROOT))


def _forbidden(what):
    def stop(*_args, **_kwargs):
        pytest.fail(f"test touched the real system: {what}")
    return stop


@pytest.fixture(autouse=True)
def no_real_system(monkeypatch):
    from fluneit import app

    if not str(app.CONFIG_FILE).startswith(str(SANDBOX)):
        pytest.fail(f"config outside the sandbox: {app.CONFIG_FILE}")
    monkeypatch.setattr(app, "set_default_output_device", _forbidden("default audio device"))
    if app.IS_WINDOWS:
        monkeypatch.setattr(app, "_schtasks", _forbidden("Task Scheduler"))
        monkeypatch.setattr(app, "_write_lnk", _forbidden("startup shortcut"))
        monkeypatch.setattr(app, "_remove_lnk", _forbidden("startup shortcut"))
        app._autostart_cache["v"] = None
    else:
        monkeypatch.setattr(app, "_autostart_desktop_path",
                            lambda: str(SANDBOX / "autostart" / "fluneit.desktop"))
    yield


@pytest.fixture
def app():
    from fluneit import app as module
    return module


@pytest.fixture
def fresh_config(app, monkeypatch, tmp_path):
    """CONFIG and CONFIG_FILE for one test, in its own folder."""
    monkeypatch.setattr(app, "CONFIG_FILE", str(tmp_path / "config.json"))
    monkeypatch.setattr(app, "CONFIG", dict(app.DEFAULT_CONFIG))
    return tmp_path
