# Media

All pictures are rendered from FluneIt's own drawing code by
[`make_media.py`](make_media.py). They show **invented sample data**: the apps
"Game", "Music", "Voice Chat" and "Browser", the devices "Headphones (USB
Audio)", "Speakers (Onboard Audio)" and "Digital Output (Onboard Audio)", and
the track "Night Drive – Example Artist" with a made-up cover.

| File | What it shows | How it is made |
|---|---|---|
| `hero.en.gif`, `hero.de.gif` | The overlay in four situations: app volume, microphone, music app with a second player, next track | Overlay drawing code (`OSD._render_box`, `OSD._render_pill`) at 2× on a neutral background, 15 fps, about 8.5 s |
| `effects.png` | Settings, page *Effekte*, with effects running and the preset *Gaming – Schritte & Details* | The real settings window, captured off screen with `PrintWindow`; the running state is simulated |
| `mixer.png` | The tray mixer | The real mixer, captured off screen; apps and devices are invented |

**Demo elements:** the keycaps and the line of text at the top of the GIFs, the
neutral background and the grey taskbar placeholders are not part of FluneIt.
They only show which keys are held.

**Simulated, not real output:** in `effects.png` the status line (delay, load,
dropouts) and the level bar are fixed values; in the GIFs the volume steps are
set by the script.

## Rendering again

```powershell
python docs\media\make_media.py
```

Windows only (the overlay uses Segoe UI and Segoe Fluent Icons), with ffmpeg on
`PATH` or in the `FFMPEG` environment variable. The script points all user
folders to a temporary directory, uses the user name "Alex", replaces audio
sessions, devices and the effects engine with stand-ins, and stops if FluneIt
would read or write settings outside that sandbox. Windows are placed off
screen, so nothing appears on your desktop. Look at every picture before
committing it.
