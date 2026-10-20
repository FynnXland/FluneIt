# Changelog

What changed for users of FluneIt, newest first. Technical details are in the
commit messages. Versions follow [semantic versioning](https://semver.org/):
major = how you use FluneIt or your settings change, minor = new features,
patch = fixes. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [2.0.0] - 2026-10-21

**First public release: FluneIt now concentrates on tuning what you hear, and
the effects are built around gaming.**

### Added
- Three gaming presets: *Schritte & Details* for shooters, *Ausgewogen* for
  role-playing and open-world games, *Leise Nacht* for late sessions. Every
  preset says when to use it.
- Your own presets: save the current sound under a name, switch back to it,
  delete it.
- *Vergleichen*: bypass the effects for a moment to hear the difference. The
  device does not switch, so nothing clicks.
- One *Stärke* slider for the compressor instead of separate technical values.
- A setup dialog the first time you turn effects on. It explains the bridge
  and suggests the output device and an unused bridge device.
- *So funktioniert's* explains the signal path, the equalizer bands, what the
  presets cannot do, the compressor and the safety limiter.
- With a virtual audio cable installed, the microphone section explains how to
  send the processed microphone to Discord and similar apps.
- *Nach Updates suchen* really checks GitHub for a newer version, only when
  you click it.
- The key for voice-chat apps (Ctrl+Alt by default) can be changed in the
  settings.
- Portable mode: a `config.json` next to the program is used instead of the
  user folder. `FLUNEIT_HOME` sets the folder explicitly.

### Changed
- The name is spelled FluneIt everywhere.
- New installations keep their settings in `%LOCALAPPDATA%\Fluneit` instead of
  next to the program.
- The effects page opens at once. Before, the window froze for about 5 seconds
  the first time while libraries loaded.
- The tray mixer opens faster (about 95 ms instead of 190–280 ms on the
  development machine).
- Noise suppression and the noise gate are offered for the microphone only. On
  game audio they swallowed exactly the quiet sounds that matter.

### Removed
- The OBS streaming page. FluneIt is no longer meant as a streaming tool.
- The numpad hotkeys that launched programs and commands.
- The *Design – Bald verfügbar* placeholder.

### Fixed
- *Nach Updates suchen* always answered "aktuell" without checking anything.
- *Log-Datei öffnen* could open a different file than the one in use.
- Clicks on the tray icon reached the window from the wrong thread, which
  could delay the mixer.
- An unreadable `config.json` was overwritten with defaults on the next save.
  It is now kept as `config.json.defekt`.
- Settings are saved atomically, so a crash while saving cannot leave half a
  file behind.

## History before the public repository

FluneIt was developed on a single machine without version control, first
under the name SoundControl. The entries below are reconstructed from the
development log. Dates are exact; where several versions came out on the
same day and their contents cannot be told apart reliably, they are listed
together. The public Git history starts with that 1.17.0 state, unchanged.

### 1.17.0 - 2026-07-22
- Experimental Linux version: X11 key grabs, PipeWire/PulseAudio, MPRIS media
  controls and an own overlay window.
- Windows: an unreadable log file no longer stops FluneIt from starting, and
  hidden apps are stored without `.exe`, so one `config.json` works on both
  systems.

Added later without a new version number:
- 2026-08-08: audio effects (equalizer, compressor, noise suppression, noise
  gate, safety limiter) through a bridge device, and a separate microphone
  chain.
- 2026-09-05: autostart through a Task Scheduler logon task instead of a
  shortcut that Windows could skip. The switch shows the real state, and every
  start is written to the log.

### 1.16.0 - 2026-07-14
- Ctrl+Alt + wheel changes the voice-chat apps (Discord, TeamSpeak and others)
  together.
- Alt + wheel controls exactly one music app. Other players are shown dimmed;
  the arrow keys switch between them, and the choice is remembered.

### 1.15.0 - 2026-07-14
- Ctrl + numpad digit started programs, websites, folders or commands
  (removed in 2.0.0).

### 1.14.0 - 2026-07-14
- The tray mixer became a sound hub: system and microphone volume, every app
  and an output device switcher.

### 1.11.0 – 1.13.0 - 2026-07-14
- A streaming page created per-app audio sources in OBS through
  obs-websocket (removed in 2.0.0).

### 1.10.0 – 1.10.1 - 2026-07-12 to 2026-07-13
- Holding a modifier for a moment shows what the wheel will control; this can
  be turned off.
- Skip protection: going back within 60 seconds after skipping a track
  returns to the position where you were.

### 1.6.0 – 1.9.0 - 2026-07-12
- Media keys: Shift + wheel changes the track, Shift + mute plays and pauses,
  Shift+Alt + wheel seeks. The overlay shows title, artist and album art; a
  middle click on the tray icon plays and pauses.
- Ctrl now controls the app volume and Ctrl+Shift the microphone.
- Alt + wheel changes the music app even while another window is in front.

### 1.4.0 – 1.5.0 - 2026-07-11
- Rounding: shortly after you stop turning, the volume snaps to a multiple
  (for example 5 %) and the overlay says so. Also for the system volume.
- Apps and output devices can be hidden from the mixer.
- Renamed from SoundControl to Fluneit.

### 1.1.0 – 1.3.0 - 2026-07-11
- A standalone Windows program instead of a script.
- Settings window, tray mixer, app rules (start volume, start muted,
  exclude) and a first-run window, in a Windows 11 style design.

### 1.0.0 - 2026-07-10
- First version, as SoundControl: Shift + volume wheel changes the volume of
  the app in front. An overlay in the style of the Windows 11 volume display
  shows the app name above it and sits on top of the Windows display.
  Autostart included.

[Unreleased]: https://github.com/FynnXland/FluneIt/compare/v2.0.0...HEAD
[2.0.0]: https://github.com/FynnXland/FluneIt/releases/tag/v2.0.0
