# Fluneit

Eigenständiges Windows-Programm (`Fluneit.exe`), das die Lautstärke
**einzelner Programme** mit dem Lautstärkerad der Tastatur regelt.

## Bedienung

| Aktion | Wirkung |
|---|---|
| Rad drehen | System-Lautstärke (wie bisher, Windows-Anzeige) |
| **Strg** halten + Rad drehen | Lautstärke der App, die gerade den Fokus hat (±5 %) |
| **Strg** + Stumm-Taste | Fokussierte App stumm schalten / wieder laut |
| **Strg+Shift** halten + Rad drehen | Mikrofon-Lautstärke (Overlay mit Mikrofon-Symbol) |
| **Strg+Shift** + Stumm-Taste | Mikrofon stumm schalten / wieder an |
| **Shift** + Rad drehen | Titel wechseln (vor/zurück) – Overlay zeigt Songtitel + Album-Cover |
| **Shift** + Stumm-Taste | Wiedergabe / Pause (auch per **Mittelklick** aufs Tray-Symbol) |
| **Shift+Alt** + Rad drehen | Im Titel spulen (±10 s pro Tick, `spulen_sekunden`) |
| **Alt** halten + Rad drehen | Lautstärke **einer** Musik-App (Spotify/Browser/Deezer …). Die geregelte App steht unten, weitere laufende Player erscheinen gedimmt darüber |
| **Alt** + **← / →** (bei sichtbarem Overlay) | Zwischen mehreren Musik-Apps wechseln (Auswahl wird gemerkt) |
| **Alt** + Stumm-Taste | Ausgewählte Musik-App stumm schalten |
| **Strg+Alt** + Rad drehen | Lautstärke der **Kommunikations-Apps** (Discord, TeamSpeak, Teams …) gemeinsam |
| **Strg+Alt** + Stumm-Taste | Kommunikations-Apps stumm schalten |
| Klick aufs Tray-Symbol | **Mini-Mixer**: alle Apps mit Audio, Slider + Stumm-Knopf pro App (schließt mit Esc oder Klick daneben) |
| Modifier **halten** (~0,7 s) | Dezente Pille zeigt, was das Rad gerade regeln würde (abschaltbar: Einstellungen → Allgemein) |

**Skip-Reue-Schutz:** Wird ein Titel versehentlich übersprungen, merkt sich
Fluneit die Sekunde. Geht man innerhalb von 60 s zurück (Medien-Taste + Rad
runter), springt der Titel wieder genau dorthin – mit Titel-Abgleich, damit
nie im falschen Song gespult wird.

Beim Regeln mit Strg erscheint ein Overlay im Stil der Windows-11-Anzeige –
an exakt derselben Position (unten mittig, pixelgenau vermessen), mit
Lautsprecher-Icon, blauem Slider und Prozentzahl. Darüber schwebt eine Pille
mit dem Namen des Programms. Gezeichnet mit echter Per-Pixel-Transparenz,
sanftem Ausblenden; Mausklicks gehen durch das Overlay hindurch.

Auch bei der **System-Lautstärke** (Rad ohne Taste) zeigt Fluneit das eigene
Overlay mit Label „System“: Das native Windows-OSD wird per WinEvent-Hook
abgefangen und ausgeblendet, sobald es zu einer Lautstärketaste erscheint.
Sicherung gegen Doppelanzeige: Bestätigt der Hook die Unterdrückung nicht
(z. B. nach einem Windows-Update mit anderem Fensternamen), zeigt Fluneit
bewusst **nichts** und überlässt Windows sein OSD – nie beide gleichzeitig.
Abschaltbar unter Einstellungen → Allgemein → „Windows-Anzeige ersetzen“.

Hinweis: **Fn** geht nicht, weil die Fn-Taste rein in der Tastatur-Hardware
verarbeitet wird und für Windows unsichtbar ist. Deshalb Strg/Shift (per
`config.json` auch Strg oder Alt möglich).

## Starten & Beenden

Doppelklick auf **`Fluneit.exe`** – läuft im Hintergrund mit
Lautsprecher-Symbol im Infobereich (Tray). Es kann immer nur eine Instanz
laufen (Doppelstart wird ignoriert).

Tray-Menü (Rechtsklick auf das Symbol):
- **Mixer** – Mini-Mixer öffnen (auch per Linksklick)
- **Einstellungen öffnen** – das Einstellungsfenster
- **Mit Windows starten** – Autostart an/aus (Häkchen zeigt den Zustand)
- **Neu starten** / **Beenden**

## Einstellungsfenster & Design

Die Oberfläche folgt dem „SoundControl Design System“ (claude.ai/design,
[DESIGN_BRIEF.md](DESIGN_BRIEF.md)) im Windows-11-Fluent-Stil, umgesetzt in
[ui.py](ui.py). Fünf Seiten:
- **Allgemein** – Autostart, Overlay an/aus, Anzeigedauer
- **Steuerung** – Modifier-Tasten (App + Mikrofon), Schrittweite, Belegungsübersicht
- **Mixer** – System- und App-Lautstärken mit Suche, Slidern und Stummschalter
- **Regeln** – App-Regeln anlegen/bearbeiten/löschen (Dialog statt config-Editieren)
- **Über** – Version, Log/Projektordner

Das Tray-Flyout (Linksklick) enthält zusätzlich einen **Ausgabegerät-Wechsler**
(Standard-Wiedergabegerät per Klick umschalten). Beim ersten Start begrüßt ein
dreistufiges Onboarding-Fenster.

## Numpad-Hotkeys (Programme/Websites/Setups starten)

**Strg + Numpad-Ziffer** löst frei belegbare Aktionen aus — unabhängig von
Num-Lock (per Scancode erkannt). Verwaltung unter **Einstellungen → Hotkeys**:
- **Programm / Website / Ordner** öffnen, **Befehl** ausführen,
- **Setup** = mehrere Aktionen nacheinander (z. B. „Arbeits-Setup": IDE + Browser + Ordner).

Beim Auslösen zeigt ein dezentes Overlay den Namen. Config-Feld `hotkeys`
(`hotkeys_modifier` = `"strg"`/`"shift"`/`"alt"`).

## Konfiguration (`config.json`)

```json
{
  "modifier": "strg",
  "mikrofon_modifier": "strg+shift",
  "medien_modifier": "shift",
  "schrittweite_prozent": 5,
  "anzeige_dauer_ms": 1500,
  "regeln": []
}
```

- `modifier` / `mikrofon_modifier` / `medien_modifier` / `hintergrund_modifier`:
  einzelne Taste (`"shift"`, `"strg"`, `"alt"`) **oder Kombination** (`"strg+shift"`);
  `""` schaltet die jeweilige Funktion ab. Die spezifischste Kombi gewinnt
  (Strg+Shift schlägt Strg und Shift). Spulen = `medien_modifier` + Alt + Rad.
- `runden_auf`: rastet die Lautstärke kurz nach dem letzten Rad-Tick auf das
  nächste Vielfache ein (z. B. `5`: 12 % → 10 %; `0` = aus) — für App-,
  Mikrofon- **und System-Lautstärke**. Das Overlay taucht dabei mit
  „… – auf X % gerundet“ als Feedback wieder auf. Auch im Einstellungsfenster
  unter „Steuerung“ → „Auf runde Werte einrasten“.
- `ausgeblendete_apps` / `ausgeblendete_geraete`: per **Rechtsklick** im
  Tray-Mixer lassen sich Apps und Ausgabegeräte ausblenden; unter
  Einstellungen → Mixer → „Ausgeblendet“ wieder einblenden.
- `regeln`: werden angewendet, sobald eine App **neu** Audio startet:
  ```json
  { "app": "discord.exe", "typ": "startlautstaerke", "wert": 40 }
  { "app": "spotify.exe", "typ": "stumm" }
  { "app": "game.exe",    "typ": "ausschliessen" }
  ```
  `startlautstaerke` = App beginnt immer mit diesem Wert ·
  `stumm` = App startet stumm · `ausschliessen` = das Rad ignoriert diese App

Nach Änderungen: Tray → „Neu starten“.

## Technik-Notizen

- Tastatur-Hook (WH_KEYBOARD_LL) fängt die Medientasten ab; mit gehaltenem
  Modifier werden sie geschluckt und auf die App-Session (WASAPI/pycaw)
  umgeleitet. Browser & Co. mit mehreren Prozessen werden über Kindprozesse
  und Prozessnamen erfasst, UWP-Apps über ApplicationFrameHost aufgelöst.
- Overlay: natives Layered Window (`UpdateLayeredWindow`, Per-Pixel-Alpha),
  Position/Farben am echten Windows-OSD vermessen, skaliert mit der
  System-DPI. Die Windows-Anzeige (`XamlExplorerHostIslandWindow`) wird bei
  Bedarf per `ShowWindow` ausgeblendet.
- Performance: Audio-Sessions werden 1 s gecacht, gerenderte Overlay-Bilder
  pro Lautstärkestufe wiederverwendet. Leerlauf: 0 % CPU.
- Fehler landen in `fluneit.log`.

## Entwicklung

```
python -m pip install -r requirements.txt
python fluneit.py          # direkt ausfuehren
.\build_exe.ps1                  # Fluneit.exe neu bauen (braucht pyinstaller)
```

## Plattformen

Fluneit laeuft unter Windows und Linux aus derselben `fluneit.py`. Alles
Plattformspezifische steckt hinter `IS_WINDOWS` bzw. in den `linux_*`-Modulen:

| Bereich      | Windows                     | Linux                        |
|--------------|-----------------------------|------------------------------|
| Tasten       | `WH_KEYBOARD_LL`-Hook       | X11-Grabs (`linux_input`)    |
| Audio        | WASAPI / pycaw              | PulseAudio/PipeWire (`linux_audio`) |
| Medien       | SMTC (winrt)                | MPRIS ueber D-Bus (`linux_media`)   |
| Overlay      | `UpdateLayeredWindow`       | Tk-Fenster (`linux_osd`)     |
| Autostart    | Verknuepfung in `Startup`   | `~/.config/autostart/*.desktop` |

Bauen: `build_exe.ps1` (Windows) bzw. `build_linux.sh` (Linux).

`config.json` ist plattformneutral - Prozessnamen werden ohne `.exe`
verglichen, dieselbe Datei funktioniert auf beiden Systemen. Sie liegt neben
dem Programm; ist der Ordner nicht beschreibbar, weicht Fluneit nach
`%LOCALAPPDATA%\Fluneit` bzw. `~/.local/state/fluneit` aus (dasselbe gilt fuer
`fluneit.log`).

## Audio-Effekte (optional)

Auf der Seite **Effekte** liegen Equalizer, Kompressor, Rauschunterdrueckung
und Noise Gate. Alles ist standardmaessig **aus** - wer das nicht braucht,
merkt nichts davon, und die dafuer noetigen Bibliotheken werden erst beim
Einschalten geladen.

### Wie es funktioniert

Windows laesst Programme nicht ohne Treiber in den Audioweg eingreifen. Fluneit
loest das mit einer **Bruecke** und ohne jeden Treiber:

```
Programme  ->  Brueckengeraet      ->  Fluneit          ->  Kopfhoerer
               (hoert niemand)          Effektkette          (echtes Geraet)
                                        WASAPI-Loopback
```

Beim Einschalten macht Fluneit das Brueckengeraet zum Standard-Ausgabegeraet,
nimmt es per WASAPI-Loopback auf, rechnet die Effekte und gibt auf dem echten
Geraet aus. Beim Ausschalten wird alles zurueckgestellt - auch dann, wenn
Fluneit abstuerzt oder hart beendet wird (das zurueckzustellende Geraet steht
in `config.json` unter `effekte_wiederherstellen` und wird beim naechsten
Start aufgeraeumt).

Als Bruecke eignet sich jeder Ausgang, an dem nichts haengt, zum Beispiel
"Realtek Digital Output" oder ein HDMI-Ausgang. Fluneit schlaegt automatisch
einen vor.

### Verzoegerung

Der Umweg kostet Zeit. Gemessen auf dem Entwicklungsrechner (44,1 kHz):

| Stufe   | ca. Verzoegerung | Rechenlast |
|---------|------------------|------------|
| Niedrig | 22 ms            | ~10 %      |
| Mittel  | 42 ms            | ~7 %       |
| Sicher  | 102 ms           | ~6 %       |

Fuers Zocken "Niedrig" nehmen. Knackt es, eine Stufe hoeher gehen.

### Taktgeber zweier Geraete

Bruecke und Kopfhoerer haengen an verschiedenen Quarzen. Den Takt gibt die
Ausgabe vor: Fluneit schreibt blockierend, laeuft also genau so schnell, wie
das Ausgabegeraet abnimmt. Laeuft die Quelle dauerhaft schneller, greift eine
Obergrenze und verwirft den aeltesten Puffer - das zaehlt die Effekte-Seite
als "Aussetzer". Im Test blieb der Zaehler ueber drei Minuten Dauerbetrieb
bei 0.

(Ein Versuch, zusaetzlich um einzelne Samples nachzuregeln, wurde wieder
entfernt: gemessen griff er 100-mal pro Sekunde ein statt der wenigen Male
pro Minute, die echte Quarzdrift braucht - in Summe ein hoerbares Brummen.
Der Fuellstand taugt bei blockierender Ausgabe nicht als Driftanzeige, weil
er ohnehin fast immer leer ist.)

### Was die Gaming-Presets wirklich tun

Ein Spiel liefert nur einen fertigen Stereomix - einzelne Klaenge wie
"Schritte" oder "Faehigkeiten" lassen sich daraus **nicht** herausrechnen. Was
funktioniert, ist der Weg ueber Frequenzen: Schritte und Nachladen liegen
grob zwischen 2 und 6 kHz, Explosionen im Tiefbass. Das Preset
"Gaming - Schritte" hebt daher den Bereich an und senkt den Bass, der ihn
sonst verdeckt. Genau so arbeiten kommerzielle "Gaming-Equalizer" auch -
Werkzeuge wie SteelSeries Sonar trennen Spiel und Chat dagegen ueber eigene
virtuelle Audiogeraete, was einen signierten Treiber braucht.

### Mikrofon

Die Mikrofonkette (Rauschunterdrueckung, Gate, Kompressor, EQ) laeuft
unabhaengig. Sie kann das bearbeitete Signal auf einem Ausgabegeraet
**mithoerbar** machen. Damit Discord oder TeamSpeak das bearbeitete Mikrofon
als Eingang sehen, braeuchte es ein virtuelles Audiokabel - das ist ein
Kernel-Treiber und in Fluneit bewusst nicht enthalten.

## Autostart

Unter Windows richtet Fluneit eine **Anmelde-Aufgabe** in der Aufgabenplanung
ein (Name: `Fluneit`), nicht mehr eine Verknuepfung im Autostart-Ordner.

Warum der Wechsel: Eine Verknuepfung im Autostart-Ordner kann Windows still
uebergehen - der Schalter in Fluneit stand auf "an", weil die Datei da war,
und trotzdem startete beim Anmelden nichts. Eine Aufgabe laesst sich dagegen
abfragen; `autostart_enabled()` liest jetzt den echten Zustand, statt nur zu
pruefen, ob eine Datei existiert.

Eigenschaften der Aufgabe:

| Einstellung           | Wert  | Warum                                        |
|-----------------------|-------|----------------------------------------------|
| Verzoegerung          | 20 s  | Audiogeraete und Taskleiste sind beim Anmelden oft noch nicht bereit |
| `ExecutionTimeLimit`  | PT0S  | ohne das beendet Windows Fluneit nach drei Tagen Laufzeit |
| Akku-Einstellungen    | aus   | auf Notebooks sonst kein Start bzw. Abbruch beim Umstecken |
| Mehrfachstart         | IgnoreNew | kein zweiter Prozess, falls Fluneit schon laeuft |

Adminrechte braucht das nicht. Nachsehen laesst sich das in der
Aufgabenplanung (`taskschd.msc`) oder mit:

```bash
schtasks /query /TN Fluneit /FO LIST
```

Klappt die Aufgabe nicht, faellt Fluneit auf die Verknuepfung im
Autostart-Ordner zurueck und erkennt dann auch, wenn Windows sie im
Task-Manager deaktiviert hat (Registry-Zweig `StartupApproved`; erstes Byte 3
= deaktiviert, 2 = erlaubt).

Jeder Start schreibt seitdem eine Zeile ins Log - inklusive der Information,
ob er von der Anmelde-Aufgabe kam (`--autostart`) oder von Hand. Damit laesst
sich ein kuenftiges "startet nicht" nachvollziehen, statt zu raten. Das Log
liegt unter `%LOCALAPPDATA%\Fluneit\fluneit.log`; der Programmordner dient nur
noch als Rueckfall, weil eine dort beschaedigte Datei je nach startendem
Prozess mal beschreibbar war und mal nicht - Meldungen verschwanden dadurch
spurlos.
