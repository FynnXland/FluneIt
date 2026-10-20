"""OBS-Bruecke fuer Fluneit - treiberfreies Per-App-Audio fuers Streaming.

Statt eigener virtueller Audiogeraete nutzen wir, dass modernes OBS den Ton
EINES Prozesses direkt als eigene Quelle aufnehmen kann ("Anwendungs-
Audioaufnahme" / wasapi_process_output_capture, ab Windows 10 2004 / OBS 28).
Dieses Modul erkennt den OBS-Zustand und legt per obs-websocket (v5) mit einem
Klick eine solche Quelle fuer eine laufende App an - ohne dass Windows mit
virtuellen Geraeten ueberladen wird.
"""

import base64
import ctypes
import glob
import hashlib
import json
import os
import shutil
import socket
import struct
import sys

IS_WINDOWS = sys.platform == "win32"

if IS_WINDOWS:
    from ctypes import wintypes

# Quelltyp der App-Audioaufnahme: Windows fest (WASAPI Process-Loopback),
# Linux dynamisch (PipeWire-App-Capture-Plugin, Name variiert je Version)
WASAPI_KIND = "wasapi_process_output_capture"
LINUX_KIND_HINTS = ("pipewire", "audio")

# ----------------------------- OBS-Zustand ----------------------------------

def _config_path():
    if IS_WINDOWS:
        matches = glob.glob(os.path.expandvars(
            r"%APPDATA%\obs-studio\plugin_config\obs-websocket\config.json"))
        return matches[0] if matches else None
    for cand in ("~/.config/obs-studio/plugin_config/obs-websocket/config.json",
                 "~/.var/app/com.obsproject.Studio/config/obs-studio/"
                 "plugin_config/obs-websocket/config.json"):
        path = os.path.expanduser(cand)
        if os.path.exists(path):
            return path
    return None


def _obs_exe():
    if IS_WINDOWS:
        for cand in (r"%ProgramFiles%\obs-studio\bin\64bit\obs64.exe",
                     r"%ProgramFiles(x86)%\obs-studio\bin\64bit\obs64.exe"):
            path = os.path.expandvars(cand)
            if os.path.exists(path):
                return path
        return None
    path = shutil.which("obs")
    if path:
        return path
    if os.path.exists("/var/lib/flatpak/app/com.obsproject.Studio"):
        return "flatpak run com.obsproject.Studio"
    return None


def _obs_proc_running(psutil):
    needle = "obs64" if IS_WINDOWS else "obs"
    for p in psutil.process_iter(['name']):
        n = (p.info.get("name") or "").lower()
        if (needle in n) if IS_WINDOWS else (n == "obs" or n.startswith("obs-")):
            return True
    return False


def obs_status():
    """Sammelt alles, was die UI ueber OBS wissen muss."""
    import psutil
    status = {"installed": bool(_obs_exe()), "exe": _obs_exe(), "running": False,
              "ws_enabled": False, "ws_port": 4455, "auth_required": True,
              "password": "", "reachable": False, "config_found": False}
    try:
        status["running"] = _obs_proc_running(psutil)
    except Exception:
        pass
    cfg = _config_path()
    if cfg:
        status["config_found"] = True
        try:
            data = json.load(open(cfg, encoding="utf-8"))
            status["ws_enabled"] = bool(data.get("server_enabled"))
            status["ws_port"] = int(data.get("server_port", 4455))
            status["auth_required"] = bool(data.get("auth_required", True))
            status["password"] = data.get("server_password", "") or ""
        except Exception:
            pass
    # Port offen?
    try:
        s = socket.socket(); s.settimeout(0.3)
        status["reachable"] = s.connect_ex(("127.0.0.1", status["ws_port"])) == 0
        s.close()
    except Exception:
        pass
    return status


def enable_websocket():
    """Aktiviert den obs-websocket-Server in der OBS-Konfiguration.
    Nur moeglich, wenn OBS gerade NICHT laeuft (sonst ueberschreibt OBS beim
    Beenden die Datei). Erzeugt bei Bedarf ein Passwort. Gibt (ok, meldung)."""
    import psutil
    if _obs_proc_running(psutil):
        return False, "Bitte OBS zuerst beenden, dann erneut versuchen."
    cfg = _config_path()
    if not cfg:
        return False, "obs-websocket-Konfiguration nicht gefunden (OBS mind. einmal starten)."
    try:
        data = json.load(open(cfg, encoding="utf-8"))
    except Exception:
        data = {}
    data["server_enabled"] = True
    data.setdefault("server_port", 4455)
    data.setdefault("auth_required", True)
    if not data.get("server_password"):
        data["server_password"] = base64.b64encode(os.urandom(12)).decode()
    try:
        with open(cfg, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
    except OSError as e:
        return False, f"Konnte Konfiguration nicht schreiben: {e}"
    return True, "obs-websocket aktiviert. Starte OBS, dann kann Fluneit Quellen anlegen."


# ----------------------------- Minimaler WebSocket-Client -------------------
# Reicht fuer obs-websocket v5 (Request/Response ueber localhost) - keine
# Fremdbibliothek noetig, damit die Exe schlank bleibt.

class _WS:
    def __init__(self, host, port, timeout=4.0):
        self.sock = socket.create_connection((host, port), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        req = (f"GET / HTTP/1.1\r\nHost: {host}:{port}\r\nUpgrade: websocket\r\n"
               f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
               f"Sec-WebSocket-Version: 13\r\n\r\n")
        self.sock.sendall(req.encode())
        resp = b""
        while b"\r\n\r\n" not in resp:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("OBS hat die WebSocket-Verbindung abgelehnt")
            resp += chunk
        if b" 101 " not in resp.split(b"\r\n", 1)[0]:
            raise ConnectionError("Kein WebSocket-Upgrade (Status != 101)")
        self._buf = resp.split(b"\r\n\r\n", 1)[1]

    def send_text(self, text):
        payload = text.encode()
        header = bytearray([0x81])  # FIN + Textframe
        mask = os.urandom(4)
        n = len(payload)
        if n < 126:
            header.append(0x80 | n)
        elif n < 65536:
            header.append(0x80 | 126); header += struct.pack(">H", n)
        else:
            header.append(0x80 | 127); header += struct.pack(">Q", n)
        header += mask
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(bytes(header) + masked)

    def _read(self, n):
        while len(self._buf) < n:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("Verbindung von OBS geschlossen")
            self._buf += chunk
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    def recv_text(self):
        while True:
            b0, b1 = self._read(2)
            opcode = b0 & 0x0F
            length = b1 & 0x7F
            if length == 126:
                length = struct.unpack(">H", self._read(2))[0]
            elif length == 127:
                length = struct.unpack(">Q", self._read(8))[0]
            data = self._read(length) if length else b""
            if opcode == 0x8:  # close
                raise ConnectionError("OBS hat die Verbindung geschlossen")
            if opcode in (0x1, 0x2):
                return data.decode("utf-8", "replace")
            # Ping/Pong u. a. ueberspringen

    def close(self):
        try:
            self.sock.close()
        except Exception:
            pass


def _auth_string(password, salt, challenge):
    """obs-websocket-Authentifizierung (SHA256, Base64) - offizieller Algorithmus."""
    secret = base64.b64encode(hashlib.sha256((password + salt).encode()).digest()).decode()
    return base64.b64encode(hashlib.sha256((secret + challenge).encode()).digest()).decode()


# ----------------------------- OBS-Requests ---------------------------------

class OBSError(Exception):
    pass


def _connect(status):
    ws = _WS("127.0.0.1", status["ws_port"])
    hello = json.loads(ws.recv_text())            # op 0
    ident = {"op": 1, "d": {"rpcVersion": 1}}
    auth = hello.get("d", {}).get("authentication")
    if auth:
        if not status.get("password"):
            ws.close()
            raise OBSError("OBS verlangt ein Passwort, aber in der Konfiguration steht keins.")
        ident["d"]["authentication"] = _auth_string(
            status["password"], auth["salt"], auth["challenge"])
    ws.send_text(json.dumps(ident))
    identified = json.loads(ws.recv_text())        # op 2
    if identified.get("op") != 2:
        ws.close()
        raise OBSError("Anmeldung bei OBS fehlgeschlagen (Passwort falsch?).")
    return ws


def _request(ws, request_type, data=None):
    rid = base64.b64encode(os.urandom(6)).decode()
    ws.send_text(json.dumps({"op": 6, "d": {"requestType": request_type,
                                            "requestId": rid, "requestData": data or {}}}))
    while True:
        msg = json.loads(ws.recv_text())
        if msg.get("op") == 7 and msg["d"].get("requestId") == rid:
            st = msg["d"]["requestStatus"]
            if not st.get("result"):
                raise OBSError(st.get("comment") or f"OBS-Fehler {st.get('code')}")
            return msg["d"].get("responseData", {})


def _resolve_app_capture_kind(ws):
    """Linux: Quelltyp fuer Per-App-Audio finden (PipeWire-App-Capture-Plugin).
    Liefert den Kind-String oder None, wenn kein passendes Plugin da ist."""
    try:
        kinds = _request(ws, "GetInputKindList").get("inputKinds", [])
    except Exception:
        return None
    for k in kinds:
        kl = k.lower()
        if all(h in kl for h in LINUX_KIND_HINTS) and ("app" in kl or "application" in kl):
            return k
    return None


def _capture_kinds(ws):
    """Alle Kind-Strings, die als App-Audioaufnahme zaehlen (fuer list_captures)."""
    kinds = [WASAPI_KIND]
    k = None if IS_WINDOWS else _resolve_app_capture_kind(ws)
    if k:
        kinds.append(k)
    return kinds


def _find_window_triplet(pid, exe_name):
    """OBS identifiziert die Quelle ueber 'Titel:Klasse:Exe'. Passendes
    sichtbares Fenster des Prozesses suchen (Titel/Klasse optional). Nur Windows."""
    user32 = ctypes.WinDLL("user32")
    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    found = {}

    @WNDENUMPROC
    def cb(hwnd, _):
        wpid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
        if wpid.value == pid and user32.IsWindowVisible(hwnd) and user32.GetWindowTextLengthW(hwnd) > 0:
            title = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, title, 256)
            cls = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, cls, 256)
            found["title"] = title.value
            found["class"] = cls.value
            return False
        return True

    user32.EnumWindows(cb, 0)
    title = found.get("title", "")
    cls = found.get("class", "")
    # OBS-Format: "Titel:Klasse:Exe" (Doppelpunkte im Titel werden von OBS escaped;
    # fuer die reine Exe-Zuordnung reicht der Exe-Teil, den OBS bevorzugt matcht)
    return f"{title}:{cls}:{exe_name}"


def _scene_name(ws):
    scene = _request(ws, "GetCurrentProgramScene")
    return scene.get("currentProgramSceneName") or scene.get("sceneName")


def _create_one(ws, scene_name, pid, exe_name, display_name):
    name = f"{display_name} (Fluneit)"
    if IS_WINDOWS:
        window = _find_window_triplet(pid, exe_name)
        _request(ws, "CreateInput", {
            "sceneName": scene_name,
            "inputName": name,
            "inputKind": WASAPI_KIND,
            "inputSettings": {"window": window, "priority": 2},  # priority 2 = per Exe
        })
        return name
    kind = _resolve_app_capture_kind(ws)
    if not kind:
        raise OBSError("Kein App-Audio-Plugin in OBS gefunden. Unter Linux braucht "
                       "OBS das Plugin \u201eobs-pipewire-audio-capture\u201c "
                       "(Anwendungs-Audioaufnahme).")
    # Einstellungen bewusst leer: die Ziel-App waehlst du im OBS-Quellen-Dialog
    _request(ws, "CreateInput", {
        "sceneName": scene_name,
        "inputName": name,
        "inputKind": kind,
        "inputSettings": {},
    })
    return name


def create_app_capture(status, pid, exe_name, display_name):
    """Legt in der aktuellen OBS-Szene eine Anwendungs-Audioaufnahme fuer die
    App an. Gibt (ok, meldung). Meldung enthaelt die echte OBS-Antwort."""
    try:
        ws = _connect(status)
    except (OSError, OBSError, ConnectionError) as e:
        return False, str(e)
    try:
        name = _create_one(ws, _scene_name(ws), pid, exe_name, display_name)
        return True, f"Quelle „{name}“ angelegt."
    except OBSError as e:
        msg = str(e)
        if "already exists" in msg.lower() or "NOT_UNIQUE" in msg:
            return False, f"„{display_name} (Fluneit)“ existiert in OBS bereits."
        return False, f"OBS meldet: {msg}"
    except Exception as e:
        return False, f"Fehler: {e}"
    finally:
        ws.close()


def create_many(status, apps):
    """Legt fuer mehrere Apps je eine Quelle an (eine Verbindung).
    apps = [(pid, exe, display)]. Gibt (ok, meldung)."""
    try:
        ws = _connect(status)
    except (OSError, OBSError, ConnectionError) as e:
        return False, str(e)
    created, skipped = [], 0
    try:
        sn = _scene_name(ws)
        for pid, exe, display in apps:
            try:
                created.append(_create_one(ws, sn, pid, exe, display))
            except OBSError as e:
                if "exist" in str(e).lower() or "NOT_UNIQUE" in str(e):
                    skipped += 1
                else:
                    raise
    except Exception as e:
        return False, f"Fehler: {e}"
    finally:
        ws.close()
    if not created:
        return False, "Nichts angelegt (bereits vorhanden)."
    tail = f", {skipped} schon vorhanden" if skipped else ""
    return True, f"{len(created)} Quelle(n) angelegt{tail}."


def _exe_from_window(window):
    """'Titel:Klasse:exe' -> 'exe' (kleingeschrieben)."""
    parts = str(window or "").rsplit(":", 1)
    return parts[-1].strip().lower() if parts else ""


def list_captures(status):
    """Vorhandene App-Audioaufnahmen in OBS: [{'name','exe'}]. Read-only."""
    try:
        ws = _connect(status)
    except (OSError, OBSError, ConnectionError):
        return None  # nicht erreichbar
    try:
        out = []
        kinds = set(_capture_kinds(ws))
        for i in _request(ws, "GetInputList").get("inputs", []):
            if i.get("inputKind") not in kinds:
                continue
            name = i.get("inputName", "")
            try:
                s = _request(ws, "GetInputSettings", {"inputName": name})
                exe = _exe_from_window(s.get("inputSettings", {}).get("window", ""))
            except OBSError:
                exe = ""
            out.append({"name": name, "exe": exe})
        return out
    except Exception:
        return None
    finally:
        ws.close()


def delete_capture(status, name):
    """Entfernt eine (Fluneit-)App-Aufnahme wieder. (ok, meldung)."""
    try:
        ws = _connect(status)
    except (OSError, OBSError, ConnectionError) as e:
        return False, str(e)
    try:
        _request(ws, "RemoveInput", {"inputName": name})
        return True, f"„{name}“ aus OBS entfernt."
    except OBSError as e:
        return False, f"OBS meldet: {e}"
    finally:
        ws.close()


def list_input_kinds(status):
    """Alle in OBS verfuegbaren Quelltypen (read-only). Damit erkennt Fluneit,
    ob ein Exclude-faehiges Audio-Plugin (win-capture-audio) geladen ist."""
    try:
        ws = _connect(status)
    except (OSError, OBSError, ConnectionError):
        return None
    try:
        return _request(ws, "GetInputKindList").get("inputKinds", [])
    except Exception:
        return None
    finally:
        ws.close()


def create_exclude_source(status, input_kind):
    """Legt EINE Quelle des (Plugin-)Typs an, die spaeter auf 'except' gestellt
    wird. Bewusst ohne geratene Settings - den Ausschluss waehlst du im
    OBS-Quellen-Dialog. (ok, meldung)."""
    try:
        ws = _connect(status)
    except (OSError, OBSError, ConnectionError) as e:
        return False, str(e)
    try:
        _request(ws, "CreateInput", {
            "sceneName": _scene_name(ws),
            "inputName": "Rest – alles außer … (Fluneit)",
            "inputKind": input_kind,
            "inputSettings": {},
        })
        return True, "Quelle angelegt – in OBS jetzt „Mode: Exclude“ + Apps wählen."
    except OBSError as e:
        if "exist" in str(e).lower() or "NOT_UNIQUE" in str(e):
            return False, "„Rest …“-Quelle existiert in OBS bereits."
        return False, f"OBS meldet: {e}"
    finally:
        ws.close()


def test_connection(status):
    """Prueft Verbindung + Auth ohne etwas zu aendern. (ok, meldung)."""
    try:
        ws = _connect(status)
    except (OSError, OBSError, ConnectionError) as e:
        return False, str(e)
    try:
        ver = _request(ws, "GetVersion")
        return True, f"Verbunden mit OBS {ver.get('obsVersion', '?')}."
    except Exception as e:
        return False, str(e)
    finally:
        ws.close()
