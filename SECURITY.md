# Security policy

## Supported versions

Only the [latest release](https://github.com/FynnXland/FluneIt/releases/latest)
gets security fixes.

## Reporting a vulnerability

**Please don't open a public issue.** Report privately via GitHub:
[**Report a vulnerability**](https://github.com/FynnXland/FluneIt/security/advisories/new)
(also on the *Security* tab).

Please include the version and OS, the impact, steps to reproduce (ideally a
minimal proof of concept), and whether you'd like to be credited. Leave out real
personal data, even in a private report.

FluneIt is maintained by one person in their spare time; expect an
acknowledgement within 7 days. Once a fix is released, the advisory is published
and you are credited if you wish.

## Scope

- **Update check:** only when the user clicks *Nach Updates suchen*. FluneIt
  sends one HTTPS GET request to `https://api.github.com/repos/FynnXland/FluneIt/releases/latest`,
  reads at most 200 KB of the answer, compares the version number and, if a
  newer one exists, offers a link to the release page in the browser. It does
  **not** download or run anything by itself.
- **Local files:** `config.json` and `fluneit.log` in `%LOCALAPPDATA%\Fluneit`
  (or next to the program in portable mode). A malformed `config.json` is moved
  aside and replaced with defaults.
- **Autostart:** a Task Scheduler logon task for the current user, created
  without administrator rights, that starts `FluneIt.exe` (or `python -m
  fluneit` when run from source).
- **System changes while effects are on:** FluneIt switches the Windows default
  output device to the chosen bridge device and back when effects are turned
  off, or at the next start after a crash.
- **Keyboard hook:** FluneIt installs a low-level keyboard hook. Windows passes
  every key press through it; FluneIt only acts on the volume, mute and arrow
  keys and does not log or store key presses.

## Out of scope

- The Windows SmartScreen warning on the unsigned `FluneIt.exe`, and antivirus
  false positives (please report those to the antivirus vendor).
- Vulnerabilities in dependencies themselves (report them upstream), unless
  FluneIt uses them in an unsafe way.
- Attacks that require an attacker who already controls the user account.
