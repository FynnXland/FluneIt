<p align="center"><img src="assets/app-icon-128.png" width="96" alt=""></p>

<h1 align="center">FluneIt</h1>

<p align="center">
  <b>Das Lautstärkerad deiner Tastatur, für jede App einzeln.</b><br>
  Taste halten, Rad drehen: Spiel, Musik oder Sprachchat werden lauter oder leiser.
</p>

<p align="center">
  <a href="https://github.com/FynnXland/FluneIt/releases/latest"><img src="https://img.shields.io/github/v/release/FynnXland/FluneIt?label=release" alt="Neueste Version"></a>
  <a href="LICENSE"><img src="https://img.shields.io/github/license/FynnXland/FluneIt" alt="MIT-Lizenz"></a>
  <img src="https://img.shields.io/badge/platform-Windows%2011-0078D6" alt="Plattform: Windows 11">
</p>

<p align="center">
  <a href="https://github.com/FynnXland/FluneIt/releases/latest"><b>Download für Windows</b></a> &nbsp;·&nbsp;
  <a href="README.md">English</a> &nbsp;·&nbsp; <a href="docs/">Dokumentation</a> &nbsp;·&nbsp;
  <a href="CHANGELOG.md">Changelog</a>
</p>

<p align="center">
  <img src="docs/media/hero.de.gif" width="760" alt="Strg halten und am Rad drehen hebt das Spiel von 40 auf 60 Prozent; danach senkt Strg+Shift das Mikrofon, Alt hebt die Musik-App, während ein zweiter Player gedimmt erscheint, und Shift springt zum nächsten Titel mit Titel und Cover im Overlay">
  <br><i>Ein Rad, vier Ziele. Das Overlay sieht aus wie die Lautstärkeanzeige von Windows und erscheint an derselben Stelle.</i>
</p>

Windows hat ein Lautstärkerad und einen Mixer, der mehrere Klicks tief versteckt
ist. Mit FluneIt regelt das Rad die App, die du gerade vor dir hast, das
Mikrofon, deine Musik oder deinen Sprachchat, je nachdem, welche Taste du
hältst. Was passiert, zeigt ein Overlay im Stil von Windows. Dazu kommen ein
optionaler Equalizer und Kompressor für alles, was du hörst, mit Presets fürs
Zocken. Kein Konto, kein Treiber, und ins Netz geht FluneIt nur, wenn du nach
einem Update fragst.

> [!NOTE]
> Die Oberfläche ist auf Deutsch. Die englische README nennt die deutschen
> Bezeichnungen samt Bedeutung.

## So funktioniert's

```mermaid
flowchart LR
    A["Spiele, Chat, Musik"] --> B["Brücke<br/>(ein Ausgang, den niemand hört)"]
    B --> C["FluneIt<br/>Equalizer, Kompressor, Limiter"]
    C --> D["Deine Kopfhörer"]
```

Die Lautstärketasten brauchen nichts davon: FluneIt stellt die Lautstärke der
gewählten App im Windows-Mixer ein. Nur die optionalen Effekte nehmen einen
Umweg, weil Windows Programme ohne Treiber nicht in den Ton anderer Programme
eingreifen lässt. Solange die Effekte an sind, spielt Windows auf eine
*Brücke*, einen Ausgang ohne angeschlossenes Gerät. FluneIt nimmt den Ton dort
ab, legt die Effekte darauf und spielt ihn auf deinem echten Gerät. Ausschalten
stellt alles zurück. Details: [docs/architecture.md](docs/architecture.md).

## Funktionen

**Das Rad folgt der Taste, die du hältst.** <kbd>Strg</kbd> für die App im
Vordergrund, <kbd>Strg</kbd>+<kbd>Shift</kbd> fürs Mikrofon, <kbd>Alt</kbd> für
die Musik-App aus jedem Fenster, <kbd>Strg</kbd>+<kbd>Alt</kbd> für die
Sprach-Apps zusammen, <kbd>Shift</kbd> für Titel. Das Rad allein regelt
weiterhin die Systemlautstärke.

**Effekte für alles, was du hörst** (optional, aus, bis du sie einschaltest).
<p align="center"><img src="docs/media/effects.png" width="776" alt="Die Seite Effekte: Effekte laufen von der Brücke zu den Kopfhörern mit etwa 22 ms Verzögerung, das Preset Gaming – Schritte & Details ist gewählt, der Sieben-Band-Equalizer ist um 2,5 und 6 kHz angehoben und unter 150 Hz abgesenkt"></p>

- **Gaming-Presets:** *Schritte & Details* für Shooter, *Ausgewogen* für
  Rollenspiele, *Leise Nacht* für späte Runden, dazu Musik, Film, Sprache und
  Bass. Eigene Einstellungen speicherst du unter einem Namen.
- **Equalizer mit sieben Bändern**, den du mit der Maus ziehst, ein Kompressor
  mit einem einzigen Regler *Stärke* und ein Schutzlimiter, der immer an bleibt.
- **Vergleichen** schaltet die Effekte kurz ab, damit du den Unterschied hörst.
- **Tray-Mixer:** ein Klick auf das Symbol im Infobereich zeigt System,
  Mikrofon, jede App mit Ton und das Ausgabegerät.
- **Overlay statt der Windows-Anzeige**, auch bei der Systemlautstärke, also nie
  zwei Anzeigen auf einmal.
- **Runden:** kurz nachdem du aufhörst zu drehen, rastet die Lautstärke auf das
  nächstliegende Vielfache von 5 % ein (oder 10 %, oder aus).
- **Regeln pro App:** eine App immer mit fester Lautstärke starten, immer stumm
  oder vom Rad ausschließen.

<details><summary><b>Weitere Funktionen</b></summary>

- **Medientasten:** <kbd>Shift</kbd> + Rad wechselt den Titel, <kbd>Shift</kbd> +
  Stumm-Taste spielt und pausiert, <kbd>Shift</kbd>+<kbd>Alt</kbd> + Rad spult um
  10 Sekunden. Das Overlay zeigt Titel, Interpret und Cover.
- **Skip-Schutz:** versehentlich weitergeschaltet? Gehst du innerhalb von 60
  Sekunden zurück, landest du wieder an der Sekunde, an der du warst.
- **Mehrere Musik-Player:** <kbd>Alt</kbd> + Rad regelt einen davon; die anderen
  erscheinen gedimmt, und <kbd>←</kbd> <kbd>→</kbd> wechseln, solange das
  Overlay zu sehen ist.
- **Modus-Hinweis:** hältst du eine Taste kurz, sagt ein kleines Schild, was das
  Rad gerade regeln würde.
- **Mikrofon-Kette:** Rauschunterdrückung, Noise Gate und Klangkorrektur für dein
  Mikrofon. Andere Apps bekommen sie nur über ein virtuelles Audiokabel wie
  VB-CABLE, das FluneIt nicht mitinstalliert.
- **Apps und Geräte ausblenden** per Rechtsklick im Mixer.

</details>

## Ein Blick hinein

<p align="center"><img src="docs/media/mixer.png" width="360" alt="Der Tray-Mixer: Regler für System und Mikrofon, darunter Browser, Game, Music und Voice Chat, und eine Liste der Ausgabegeräte mit ausgewählten Kopfhörern"></p>

Der Tray-Mixer öffnet sich mit einem Klick auf das Lautsprecher-Symbol im
Infobereich. Alle App- und Gerätenamen in diesen Bildern sind erfundene
Beispieldaten.

## Installation

| Plattform | Bezug | Hinweise |
|---|---|---|
| Windows 11 | [`FluneIt.exe`](https://github.com/FynnXland/FluneIt/releases/latest) | Eine einzelne Datei mit etwa 60 MB, kein Installer. Braucht im Leerlauf etwa 80 MB Arbeitsspeicher. |
| Windows 10 | dieselbe Datei | Sollte laufen, ist aber nicht getestet. |
| Linux | aus dem Quellcode, siehe [Entwicklung](#entwicklung) | Experimentell: Der Code ist da, wurde aber nur mit Importtests geprüft, nicht auf einem echten Desktop. |

> [!TIP]
> FluneIt ist nicht signiert, deshalb kann Windows SmartScreen beim ersten Start
> warnen. Wähle *Weitere Informationen → Trotzdem ausführen*. Ob die Datei die von
> dieser Seite ist, zeigt der Vergleich mit `SHA256SUMS.txt` aus dem Release:
> `Get-FileHash FluneIt.exe -Algorithm SHA256`.

### Erster Start

1. Lege `FluneIt.exe` in einen Ordner, in dem sie bleiben kann, zum Beispiel
   `%LOCALAPPDATA%\Programs\FluneIt`, und starte sie.
2. Ein Willkommensfenster zeigt die wichtigste Taste und bietet *Mit Windows
   starten* an.
3. FluneIt sitzt jetzt im Infobereich. Per Rechtsklick auf das Symbol erreichst
   du *Einstellungen öffnen*.

Für Effekte öffnest du *Effekte* und legst den Schalter um. Ein kurzer Dialog
fragt nach deinen Kopfhörern und nach der Brücke, einem Ausgang ohne
angeschlossenes Gerät, etwa dem HDMI-Ausgang der Grafikkarte oder dem
Digitalausgang des Mainboards.

## Im Alltag

| Tasten | Was passiert |
|---|---|
| Rad | Systemlautstärke, wie immer |
| <kbd>Strg</kbd> + Rad | Lautstärke der App im Vordergrund |
| <kbd>Strg</kbd> + Stumm-Taste | App im Vordergrund stumm schalten oder wieder laut |
| <kbd>Strg</kbd>+<kbd>Shift</kbd> + Rad / Stumm-Taste | Mikrofon |
| <kbd>Alt</kbd> + Rad / Stumm-Taste | Die Musik-App, aus jedem Fenster |
| <kbd>Strg</kbd>+<kbd>Alt</kbd> + Rad / Stumm-Taste | Sprach-Apps (Discord, TeamSpeak, Teams …) |
| <kbd>Shift</kbd> + Rad | Nächster oder vorheriger Titel |
| <kbd>Shift</kbd> + Stumm-Taste | Wiedergabe oder Pause |
| <kbd>Shift</kbd>+<kbd>Alt</kbd> + Rad | Im Titel spulen |

Die Tasten lassen sich unter *Steuerung* ändern; alle außer der für die App im
Vordergrund lassen sich auch abschalten. Die <kbd>Fn</kbd>-Taste geht nicht:
Tastaturen verarbeiten sie selbst und melden sie Windows nie.

**Verzögerung der Effekte.** Der Umweg über die Brücke kostet Zeit. Die
Effekte-Seite zeigt die Schätzung von FluneIt; auf dem Entwicklungsrechner
waren es etwa 20 ms bei *Niedrig*, 40 ms bei *Mittel* und 100 ms bei *Sicher*.
Zum Zocken *Niedrig* nehmen; knackt es, eine Stufe höher.

**Was die Gaming-Presets können und was nicht.** Ein Spiel liefert einen
fertigen Mix. Einzelne Geräusche wie „nur Schritte“ lassen sich daraus nicht
herausrechnen, nur ihr Frequenzbereich. *Schritte & Details* hebt den Bereich
an, in dem Schritte und Nachladen liegen (etwa 2,5 bis 6 kHz), und senkt den
Bass, der sie verdeckt.

## Datenschutz und deine Daten

| Was | Wo | Verlässt deinen PC? |
|---|---|---|
| Einstellungen | `%LOCALAPPDATA%\Fluneit\config.json`, oder neben `FluneIt.exe`, wenn dort schon eine `config.json` liegt | Nein |
| Log-Datei | `%LOCALAPPDATA%\Fluneit\fluneit.log`: Programmstarts und Fehler; kann Apps, Audiogeräte und Ordner nennen, nie Ton | Nein |
| Autostart | eine Aufgabe namens *Fluneit* in der Windows-Aufgabenplanung | Nein |
| Update-Prüfung | eine Anfrage an `api.github.com`, nur wenn du auf *Nach Updates suchen* klickst | Nur diese Anfrage |

FluneIt nimmt keinen Ton auf und speichert keinen. Mit Effekten läuft der Ton
im Arbeitsspeicher durch FluneIt zu deinen Kopfhörern. Die experimentelle
Linux-Version lädt außerdem Cover, wenn ein Musik-Player sie als Webadresse
anbietet. Um FluneIt komplett zu entfernen: *Mit Windows starten* ausschalten,
über das Tray-Menü beenden (*Beenden*) und `FluneIt.exe` sowie den Ordner
`%LOCALAPPDATA%\Fluneit` löschen.

## Fehlerbehebung

| Problem | Lösung |
|---|---|
| Kein Ton, nachdem FluneIt mit Effekten abgestürzt ist | FluneIt neu starten: Es stellt das Standardgerät zurück. Oder in den Windows-Soundeinstellungen die Kopfhörer wählen. |
| Die Effekte knacken | *Effekte → Verzögerung*: eine Stufe höher. |
| Die Effekte-Seite meldet fehlende Bibliotheken | Nur beim Start aus dem Quellcode: `pip install -r requirements.txt`. |
| Mit gehaltener <kbd>Strg</kbd>-Taste tut das Rad nichts | Die App im Vordergrund hat gerade vielleicht keinen Ton; dann steht *kein Audio* im Overlay. Unter *Regeln* nachsehen, ob die App ausgeschlossen ist. |
| FluneIt startet nicht mit Windows | *Allgemein* zeigt, wie der Autostart eingerichtet ist. Das Log vermerkt jeden Start als *Anmeldung* oder *manuell*. |
| Etwas anderes | Ein [Issue](https://github.com/FynnXland/FluneIt/issues/new/choose) eröffnen und einen Log-Auszug anhängen (*Über → Log-Datei öffnen*). |

## Entwicklung

```powershell
git clone https://github.com/FynnXland/FluneIt.git
cd FluneIt
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
python -m fluneit                 # aus dem Quellcode starten
python -m pytest                  # Tests, kein Audiogerät nötig
.\packaging\build_exe.ps1         # baut dist\FluneIt.exe
```

Python 3.11 unter Windows. Mehr in [CONTRIBUTING.md](CONTRIBUTING.md) und
[docs/architecture.md](docs/architecture.md).

## Danksagung

FluneIt baut auf [pycaw](https://github.com/AndreMiras/pycaw) und
[comtypes](https://github.com/enthought/comtypes) für die Windows-Audio-
Schnittstellen auf, auf [pystray](https://github.com/moses-palmer/pystray) für
das Tray-Symbol, auf [NumPy](https://numpy.org/) und [SciPy](https://scipy.org/)
für die Effekte und auf
[python-sounddevice](https://github.com/spatialaudio/python-sounddevice) für die
Wiedergabe. Alle mitgelieferten Komponenten und ihre Lizenzen stehen in
[THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).

## Lizenz

FluneIt steht unter der [MIT-Lizenz](LICENSE).

Sofern du nicht ausdrücklich etwas anderes angibst, steht jeder Beitrag, den du
zur Aufnahme in dieses Projekt einreichst, unter der MIT-Lizenz, ohne weitere
Bedingungen.

Copyright © 2026 FynnXland
