# Contributing to FluneIt

Thanks for your interest! Reports and suggestions are welcome in English or
German ("Deutsch ist genauso willkommen").

FluneIt is maintained by one person. **Issues are welcome; for pull requests,
please open an issue first** so we can agree on the change before you put work
into it. Bug reports and ideas go through the
[issue forms](https://github.com/FynnXland/FluneIt/issues/new/choose); security
problems go to a [private report](SECURITY.md). How the program is put together
is described in [docs/architecture.md](docs/architecture.md).

## Development setup

Windows 10 or 11 with Python 3.11:

```powershell
git clone https://github.com/FynnXland/FluneIt.git
cd FluneIt
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
python -m fluneit
```

`requirements.txt` holds what FluneIt needs to run, `requirements-dev.txt` adds
pytest and PyInstaller. Without numpy, scipy and sounddevice FluneIt still runs;
the *Effekte* page then says what is missing.

A `config.json` in the repository root puts FluneIt into portable mode and is
then used instead of `%LOCALAPPDATA%\Fluneit`. It is ignored by Git. Setting
`FLUNEIT_HOME` to a folder keeps a development copy away from your real
settings.

Linux (experimental, X11): `packaging/setup_linux.sh`, then
`packaging/fluneit.sh`. The Linux code has only been checked by import tests so
far; reports from real Linux desktops are very welcome.

## Tests

```powershell
python -m pytest
python scripts\check_secrets.py
```

About 60 tests, a few seconds, no audio device needed. `tests/conftest.py`
points all user folders to a temporary directory and makes any test fail that
would touch Task Scheduler, the startup shortcut or the default audio device.
Keep it that way: a test that changes the real autostart is a bug.

New behaviour needs a test; a bug fix needs a test that fails without the fix.
GitHub Actions runs the guard and the tests on Windows for every push to `main`
and every pull request.

## Conventions

- Code lives in `fluneit/`. Windows-specific code sits behind `IS_WINDOWS`,
  Linux code in the `linux_*` modules.
- The interface is German; keep new labels consistent with the existing ones.
- Comments in the code are German, like the existing ones; commit messages,
  the CHANGELOG and the documentation for users are English (with a German
  README next to it).
- A new dependency goes into `requirements.txt` and
  [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md), and its license must be
  compatible with MIT.
- Screenshots and GIFs only with invented sample data. `docs/media/make_media.py`
  renders them in a sandbox; see [docs/media/README.md](docs/media/README.md).

## Privacy

Everything committed is public forever, including the history. Never commit
your `config.json`, log files, real app or device names in screenshots, user
names or paths from your own machine, or any keys and tokens.
`scripts/check_secrets.py` catches the obvious cases, not all of them.

## Version, CHANGELOG and building

The maintainer sets the version (`__version__` in `fluneit/app.py`) and writes
the CHANGELOG. In a pull request, describe in one or two sentences what changes
for users; that becomes the CHANGELOG entry.

`packaging\build_exe.ps1` builds `dist\FluneIt.exe` and `dist\SHA256SUMS.txt`.
Releases are built and published by the maintainer.

## AI agents

Parts of FluneIt were written with AI coding agents. There is no agent file in
the repository; agents follow this file like everyone else.

## License

Unless you explicitly state otherwise, any contribution you submit for inclusion
in this project is licensed under the [MIT License](LICENSE), without additional
terms or conditions.
