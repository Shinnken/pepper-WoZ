#!/usr/bin/env python3
"""NAO WoZ - mowa. Serwer WWW dla operatora + łącze z robotem.

Dwa wyjścia mowy:
  robot   - NAO mówi sam (ALAnimatedSpeech / ALTextToSpeech)
  speaker - "narrator": ten sam głos NAO odtwarzany z głośnika PC. Kwestie są syntetyzowane
            na robocie (ALTextToSpeech.sayToFile), konwertowane do MP3 i zapisywane w nagrania/.
            Nagrane kwestie działają potem nawet bez podłączonego robota.

Uruchom:  python3 server.py            (potem otwórz http://localhost:8080)
          python3 server.py --demo     (symulowany robot, do testów bez NAO)
"""

import argparse
import base64
import hashlib
import itertools
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import unicodedata
import wave
import webbrowser
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

import tables

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
TABLES_DIR = os.path.join(BASE_DIR, "dialogi")
RECORDINGS_DIR = os.path.join(BASE_DIR, "nagrania")
LAST_TABLE_FILE = os.path.join(TABLES_DIR, ".ostatnia_tabela")
ROBOT_SCRIPT = os.path.join(BASE_DIR, "robot", "nao_speech_service.py")
REMOTE_SCRIPT_NAME = "nao_speech_service.py"

# Ustawienia środowiska Pythona na robocie - skopiowane z działającego pepper-WoZ-UI-demo.
REMOTE_PYTHON = "/home/nao/apps/python3nao/bin/python3"
REMOTE_ENV = (
    'export LD_PRELOAD="/home/nao/.local/share/PackageManager/apps/python3nao/bin/libcrypt.so.1":$LD_PRELOAD && '
    'export PYTHONPATH="/data/home/nao/.local/share/PackageManager/apps/python3nao/lib/python3.9/site-packages"'
    '${PYTHONPATH:+:$PYTHONPATH} && '
)

# Format, w którym sayToFile zapisuje dźwięk, jeśli plik nie ma nagłówka WAV (surowe PCM).
RAW_PCM = {"rate": 22050, "channels": 1}


def local_ip_for(target):
    try:
        target_ip = socket.gethostbyname(target)
    except OSError:
        target_ip = "8.8.8.8"
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect((target_ip, 80))
            return s.getsockname()[0]
        except OSError:
            return "127.0.0.1"


def slugify(text, limit=60):
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_")
    return text[:limit].rstrip("_") or "kwestia"


class Hub:
    """Wspólny stan: historia wypowiedzi obu wyjść."""

    def __init__(self):
        self.lock = threading.RLock()
        self.ids = itertools.count(1)
        self.history = deque(maxlen=200)
        self.by_id = {}
        self.speaking = None

    def new_entry(self, text, label, output):
        with self.lock:
            entry = {"id": next(self.ids), "text": text, "label": label, "output": output,
                     "status": "queued", "t": time.strftime("%H:%M:%S")}
            self.history.append(entry)
            self.by_id[entry["id"]] = entry
            return entry

    def set_status(self, job_id, status, error=None):
        with self.lock:
            entry = self.by_id.get(job_id)
            if not entry:
                return
            entry["status"] = status
            if error:
                entry["error"] = error
            if status == "speaking":
                self.speaking = {k: entry[k] for k in ("id", "text", "label", "output")}
            elif self.speaking and self.speaking["id"] == job_id:
                self.speaking = None


PITCH_MIN, PITCH_MAX = 0.7, 1.6


def pitch_filter(rate, pitch):
    """Filtr ffmpeg: wysokość * pitch, tempo bez zmian."""
    return "asetrate=%d,aresample=%d,atempo=%.6f" % (round(rate * pitch), rate, 1.0 / pitch)


def wav_rate(path):
    with wave.open(path, "rb") as w:
        return w.getframerate()


class Recordings:
    """Pamięć podręczna nagrań głosu NAO.

    nagrania/<Język>/zrodla/<nazwa>.wav  - czysty wynik sayToFile (bez podwyższenia)
    nagrania/<Język>/<nazwa>.mp3         - gotowe MP3 z bieżącą wysokością głosu
    Wysokość: ręczna (suwak w panelu) albo pitchShift zgłoszony przez robota (NAO: 1.15).
    """

    def __init__(self, folder):
        self.folder = folder
        self.lock = threading.RLock()
        self.manifest_path = os.path.join(folder, "manifest.json")
        self.version = 0
        self.ffmpeg = shutil.which("ffmpeg")
        self.render_gen = 0
        self.render_state = {"running": False, "done": 0, "total": 0}
        try:
            with open(self.manifest_path, encoding="utf-8") as fh:
                self.manifest = json.load(fh)
        except (OSError, ValueError):
            self.manifest = {"items": {}, "last_language": ""}
        self.manifest.setdefault("pitch_override", None)
        self.manifest.setdefault("robot_pitch", None)

    # ------------------------------------------------------------ wysokość
    @property
    def robot_pitch(self):
        return self.manifest.get("robot_pitch") or 1.0

    @property
    def pitch(self):
        override = self.manifest.get("pitch_override")
        return float(override) if override is not None else float(self.robot_pitch)

    def pitch_info(self):
        return {"value": round(self.pitch, 3), "manual": self.manifest.get("pitch_override") is not None,
                "robot": round(self.robot_pitch, 3), "min": PITCH_MIN, "max": PITCH_MAX,
                "rendering": dict(self.render_state)}

    def set_robot_pitch(self, value):
        try:
            value = float(value)
        except (TypeError, ValueError):
            return
        with self.lock:
            if abs(value - self.robot_pitch) > 1e-4 or self.manifest.get("robot_pitch") is None:
                self.manifest["robot_pitch"] = value
                self._save()
                if self.manifest.get("pitch_override") is None:
                    self.rerender_async()

    def set_pitch(self, value):
        """value = liczba (ręcznie) albo None (jak robot)."""
        with self.lock:
            if value is not None:
                value = min(PITCH_MAX, max(PITCH_MIN, float(value)))
            self.manifest["pitch_override"] = value
            self._save()
            self.version += 1
        self.rerender_async()

    # ------------------------------------------------------------ wyszukiwanie
    @staticmethod
    def key(text, lang):
        return hashlib.sha1(("%s\x1f%s" % (lang or "", text.strip())).encode("utf-8")).hexdigest()[:16]

    @property
    def last_language(self):
        return self.manifest.get("last_language", "")

    def _info(self, text, lang):
        info = self.manifest["items"].get(self.key(text, lang))
        if info and os.path.isfile(os.path.join(self.folder, info["file"])):
            return info
        if info and info.get("source") and os.path.isfile(os.path.join(self.folder, info["source"])):
            return info
        return None

    def find(self, text, lang):
        return self._info(text, lang) is not None

    def play_spec(self, text, lang, live_filter):
        """(ścieżka, filtr|None). Gdy odtwarzacz umie filtry - źródło + bieżąca wysokość na żywo
        (zmiana suwaka działa natychmiast); w przeciwnym razie gotowe MP3."""
        info = self._info(text, lang)
        if not info:
            return None, None
        src = os.path.join(self.folder, info["source"]) if info.get("source") else None
        if live_filter and src and os.path.isfile(src):
            pitch = self.pitch
            return src, (pitch_filter(wav_rate(src), pitch) if abs(pitch - 1) > 0.005 else None)
        return os.path.join(self.folder, info["file"]), None

    # ------------------------------------------------------------ zapis
    def _render(self, src, out, pitch):
        if not self.ffmpeg:
            shutil.copyfile(src, out)
            return
        filters = ["-af", pitch_filter(wav_rate(src), pitch)] if abs(pitch - 1.0) > 0.005 else []
        proc = subprocess.run([self.ffmpeg, "-y", "-loglevel", "error", "-i", src] + filters +
                              ["-codec:a", "libmp3lame", "-q:a", "2", out + ".tmp.mp3"],
                              capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError("ffmpeg: " + proc.stderr.strip()[-300:])
        os.replace(out + ".tmp.mp3", out)

    def _save(self):
        tmp_manifest = self.manifest_path + ".tmp"
        os.makedirs(self.folder, exist_ok=True)
        with open(tmp_manifest, "w", encoding="utf-8") as fh:
            json.dump(self.manifest, fh, ensure_ascii=False, indent=1)
        os.replace(tmp_manifest, self.manifest_path)

    def store(self, text, lang, data, hint, robot_pitch=None):
        if robot_pitch:
            self.set_robot_pitch(robot_pitch)
        lang_dir = slugify(lang or "nieznany", 30)
        key = self.key(text, lang)
        name = "%s_%s" % (slugify(hint or text, 50), key[:8])
        rel = os.path.join(lang_dir, name + (".mp3" if self.ffmpeg else ".wav"))
        rel_src = os.path.join(lang_dir, "zrodla", name + ".wav")
        out, src = os.path.join(self.folder, rel), os.path.join(self.folder, rel_src)
        os.makedirs(os.path.dirname(src), exist_ok=True)

        if data[:4] == b"RIFF":
            with open(src, "wb") as fh:
                fh.write(data)
        else:  # surowe PCM 16-bit -> opakuj w WAV
            with wave.open(src, "wb") as w:
                w.setnchannels(RAW_PCM["channels"])
                w.setsampwidth(2)
                w.setframerate(RAW_PCM["rate"])
                w.writeframes(data)
        pitch = self.pitch
        self._render(src, out, pitch)

        with self.lock:
            old = self.manifest["items"].get(key)
            for field, new_rel in (("file", rel), ("source", rel_src)):
                if old and old.get(field) and old[field] != new_rel:
                    try:
                        os.remove(os.path.join(self.folder, old[field]))
                    except OSError:
                        pass
            self.manifest["items"][key] = {"file": rel, "source": rel_src, "text": text.strip(),
                                           "language": lang, "rendered_pitch": pitch,
                                           "created": time.strftime("%Y-%m-%d %H:%M:%S")}
            self.manifest["last_language"] = lang
            self._save()
            self.version += 1
        return out

    def rerender_async(self):
        """Po zmianie wysokości: przelicz MP3 ze źródeł w tle (najnowsza zmiana wygrywa)."""
        with self.lock:
            self.render_gen += 1
            gen = self.render_gen
        threading.Thread(target=self._rerender, args=(gen,), daemon=True).start()

    def _rerender(self, gen):
        with self.lock:
            pitch = self.pitch
            todo = [(k, dict(v)) for k, v in self.manifest["items"].items()
                    if v.get("source") and abs(v.get("rendered_pitch", -1) - pitch) > 1e-4]
            self.render_state = {"running": bool(todo), "done": 0, "total": len(todo)}
        for key, info in todo:
            if gen != self.render_gen:
                return
            try:
                self._render(os.path.join(self.folder, info["source"]), os.path.join(self.folder, info["file"]), pitch)
                with self.lock:
                    if key in self.manifest["items"]:
                        self.manifest["items"][key]["rendered_pitch"] = pitch
            except Exception as exc:
                print("Przeliczanie %s: %s" % (info["file"], exc))
            with self.lock:
                self.render_state["done"] += 1
        with self.lock:
            if gen == self.render_gen:
                self.render_state["running"] = False
                self._save()


def find_player():
    """(nazwa, polecenie, funkcja_filtra|None). ffplay/mpv potrafią zmieniać wysokość na żywo."""
    candidates = (
        ("ffplay", ["-nodisp", "-autoexit", "-loglevel", "quiet"], lambda f: ["-af", f]),
        ("mpv", ["--no-video", "--really-quiet"], lambda f: ["--af=lavfi=[%s]" % f]),
        ("pw-play", [], None), ("paplay", [], None), ("aplay", ["-q"], None),
    )
    for name, args, filt in candidates:
        path = shutil.which(name)
        if path:
            return name, [path] + args, filt
    return None, None, None


class RobotLink:
    """Połączenie TCP z usługą mowy na robocie (robot łączy się do nas)."""

    def __init__(self, args, hub):
        self.args = args
        self.hub = hub
        self.lock = hub.lock
        self.status = "disconnected"   # disconnected | connecting | connected
        self.message = ""
        self.error = ""
        self.host = ""
        self.conn = None
        self.languages, self.language, self.volume = [], "", None
        self.generation = 0
        self.local_proc = None
        self.pending_robot = set()   # wypowiedzi wysłane do robota, jeszcze niezakończone
        self.pending_files = {}      # id -> {"event", "data", "language", "error"}
        self.on_pitch = None         # wywoływane, gdy robot zgłosi swój pitchShift

    @property
    def connected(self):
        return self.status == "connected"

    def snapshot(self):
        return {"status": self.status, "message": self.message, "error": self.error, "host": self.host,
                "languages": self.languages, "language": self.language, "volume": self.volume}

    def connect(self, host, manual):
        with self.lock:
            if self.status == "connecting":
                return
            self._close_locked()
            self.generation += 1
            gen = self.generation
            self.status, self.error, self.host = "connecting", "", host
            self.message = "Przygotowanie..."
        threading.Thread(target=self._connect_worker, args=(gen, host, manual), daemon=True).start()

    def disconnect(self):
        with self.lock:
            self.generation += 1
            if self.conn:
                try:
                    self._send_locked({"cmd": "exit"})
                except RuntimeError:
                    pass
            self._close_locked()
            self.status, self.message = "disconnected", "Rozłączono."

    def say(self, entry, animated):
        with self.lock:
            if not self.connected:
                self.hub.set_status(entry["id"], "error", "Robot nie jest połączony.")
                raise RuntimeError("Robot nie jest połączony.")
            self.pending_robot.add(entry["id"])
            self._send_locked({"cmd": "say", "id": entry["id"], "text": entry["text"], "animated": bool(animated)})

    def command(self, msg):
        with self.lock:
            if not self.connected:
                raise RuntimeError("Robot nie jest połączony.")
            self._send_locked(msg)

    def synthesize(self, text, timeout=90):
        """Synteza głosu NAO do pliku. Zwraca (bajty, język, pitch_shift)."""
        with self.lock:
            if not self.connected:
                raise RuntimeError("Robot nie jest połączony - nie da się nagrać nowej kwestii.")
            job_id = next(self.hub.ids)
            slot = {"event": threading.Event()}
            self.pending_files[job_id] = slot
            self._send_locked({"cmd": "tts_file", "id": job_id, "text": text})
        try:
            if not slot["event"].wait(timeout):
                raise RuntimeError("Robot nie zwrócił nagrania w %d s." % timeout)
        finally:
            with self.lock:
                self.pending_files.pop(job_id, None)
        if slot.get("error"):
            raise RuntimeError("Nagrywanie na robocie nie powiodło się: " + slot["error"])
        return slot["data"], slot.get("language") or self.language, slot.get("pitch_shift") or 1.0

    # ---------------------------------------------------------------- internals
    def _set(self, gen, **kw):
        with self.lock:
            if gen != self.generation:
                return False
            for k, v in kw.items():
                setattr(self, k, v)
            return True

    def _send_locked(self, msg):
        try:
            self.conn.sendall((json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8"))
        except (OSError, AttributeError) as exc:
            self._lost_locked("Utracono połączenie: %s" % exc)
            raise RuntimeError(self.error)

    def _lost_locked(self, err):
        self._close_locked()
        self.status, self.error, self.message = "disconnected", err, ""

    def _close_locked(self):
        if self.conn:
            try:
                self.conn.close()
            except OSError:
                pass
        self.conn = None
        for job_id in self.pending_robot:
            self.hub.set_status(job_id, "cancelled")
        self.pending_robot.clear()
        for slot in self.pending_files.values():
            slot["error"] = "rozłączono"
            slot["event"].set()

    def _connect_worker(self, gen, host, manual):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            listener.bind(("0.0.0.0", self.args.robot_port))
            listener.listen(1)
            my_ip = "127.0.0.1" if self.args.demo else local_ip_for(host)
            cmd_hint = "python3 %s --host %s --port %d" % (REMOTE_SCRIPT_NAME, my_ip, self.args.robot_port)

            if self.args.demo:
                self._set(gen, message="Uruchamiam symulowanego robota...")
                self._start_local_fake(my_ip)
                timeout = 15
            elif manual:
                self._set(gen, message="Czekam, aż uruchomisz na robocie: " + cmd_hint)
                timeout = 300
            else:
                self._set(gen, message="Wgrywam i uruchamiam usługę na %s przez SSH..." % host)
                self._deploy(host, my_ip)
                self._set(gen, message="Czekam, aż robot się połączy (%s:%d)..." % (my_ip, self.args.robot_port))
                timeout = self.args.accept_timeout

            listener.settimeout(1.0)
            deadline = time.time() + timeout
            conn = None
            while time.time() < deadline:
                if gen != self.generation:
                    return
                try:
                    conn, addr = listener.accept()
                    break
                except socket.timeout:
                    continue
            if conn is None:
                raise TimeoutError("Robot się nie połączył w %d s. Sprawdź adres, sieć i zaporę (port %d)."
                                   % (timeout, self.args.robot_port))
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            with self.lock:
                if gen != self.generation:
                    conn.close()
                    return
                self.conn = conn
                self.status, self.message = "connected", "Połączono z %s" % addr[0]
            self._reader(gen, conn)
        except Exception as exc:
            traceback.print_exc()
            with self.lock:
                if gen == self.generation:
                    self._lost_locked(str(exc) or exc.__class__.__name__)
        finally:
            listener.close()

    def _reader(self, gen, conn):
        f = conn.makefile("rb")
        try:
            for raw in f:
                try:
                    msg = json.loads(raw.decode("utf-8"))
                except ValueError:
                    continue
                with self.lock:
                    if gen != self.generation:
                        return
                    self._on_event(msg)
        except OSError:
            pass
        with self.lock:
            if gen == self.generation:
                self._lost_locked("Robot zamknął połączenie.")

    def _on_event(self, msg):
        ev, job_id = msg.get("ev"), msg.get("id")
        if ev in ("hello", "state"):
            self.languages = msg.get("languages") or self.languages
            self.language = msg.get("language") or self.language
            self.volume = msg.get("volume", self.volume)
            if msg.get("pitch_shift") is not None and self.on_pitch:
                self.on_pitch(msg["pitch_shift"])
        elif ev == "started":
            self.hub.set_status(job_id, "speaking")
        elif ev in ("done", "cancelled"):
            self.pending_robot.discard(job_id)
            self.hub.set_status(job_id, ev)
        elif ev in ("file", "file_error"):
            slot = self.pending_files.get(job_id)
            if slot:
                if ev == "file":
                    slot["data"] = base64.b64decode(msg.get("data") or "")
                    slot["language"] = msg.get("language")
                    slot["pitch_shift"] = msg.get("pitch_shift")
                else:
                    slot["error"] = msg.get("msg") or "nieznany błąd"
                slot["event"].set()
        elif ev == "error":
            if job_id is not None:
                self.pending_robot.discard(job_id)
                self.hub.set_status(job_id, "error", msg.get("msg"))
            self.error = msg.get("msg", "Błąd robota")

    def _deploy(self, host, my_ip):
        try:
            import paramiko
        except ImportError:
            raise RuntimeError("Brak biblioteki paramiko (pip install paramiko) - albo zaznacz "
                               "„ręcznie” i odpal skrypt na robocie samodzielnie.")
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(host, username=self.args.ssh_user, password=self.args.ssh_password, timeout=10)
        try:
            sftp = ssh.open_sftp()
            remote_path = sftp.normalize(".") + "/" + REMOTE_SCRIPT_NAME
            sftp.put(ROBOT_SCRIPT, remote_path)
            sftp.close()
            # Osobne polecenie: gdyby pkill był w tym samym poleceniu co start, wzorzec trafiłby
            # we własną powłokę (jej linia poleceń też zawiera nazwę skryptu) i zabiłby ją.
            _, out, _ = ssh.exec_command("pkill -f '[n]ao_speech_service.py'; true")
            out.channel.recv_exit_status()
            env = "" if self.args.no_remote_env else REMOTE_ENV
            command = ("%ssetsid nohup %s %s --host %s --port %d > /tmp/nao_speech.log 2>&1 < /dev/null &"
                       % (env, self.args.remote_python, remote_path, my_ip, self.args.robot_port))
            _, out, err = ssh.exec_command(command)
            # czekamy na zakończenie polecenia startowego - porzucony kanał SSH bywa zamykany,
            # zanim proces w tle zdąży wystartować
            if out.channel.recv_exit_status() != 0:
                raise RuntimeError("Nie udało się uruchomić usługi na robocie: "
                                   + err.read().decode("utf-8", "replace")[-300:])
        finally:
            ssh.close()

    def _start_local_fake(self, my_ip):
        if self.local_proc and self.local_proc.poll() is None:
            self.local_proc.terminate()
        self.local_proc = subprocess.Popen([sys.executable, ROBOT_SCRIPT, "--fake", "--host", my_ip,
                                            "--port", str(self.args.robot_port)])


class Speaker:
    """Wyjście "narrator": głos NAO z głośnika PC (nagrania MP3, nagrywane w razie potrzeby)."""

    def __init__(self, hub, robot, recordings):
        self.hub, self.robot, self.rec = hub, robot, recordings
        self.player_name, self.player_cmd, self.player_filter = find_player()
        self.queue = deque()
        self.cond = threading.Condition(hub.lock)
        self.current = None
        self.proc = None
        self.cancel_current = False
        threading.Thread(target=self._worker, daemon=True).start()

    def language(self):
        return self.robot.language or self.rec.last_language

    def enqueue(self, entry):
        if not self.player_cmd:
            self.hub.set_status(entry["id"], "error", "Brak odtwarzacza")
            raise RuntimeError("Brak odtwarzacza audio (zainstaluj ffmpeg albo mpv).")
        with self.cond:
            self.queue.append(entry)
            self.cond.notify()

    def stop(self):
        with self.cond:
            while self.queue:
                self.hub.set_status(self.queue.popleft()["id"], "cancelled")
            if self.current is not None:
                self.cancel_current = True
            proc = self.proc
        if proc and proc.poll() is None:
            proc.terminate()

    def ensure_recording(self, text, hint):
        """Zwraca język, w którym jest nagranie (w razie potrzeby nagrywa na robocie)."""
        lang = self.language()
        if self.rec.find(text, lang):
            return lang
        data, lang, pitch = self.robot.synthesize(text)
        self.rec.store(text, lang, data, hint, pitch)
        return lang

    def _worker(self):
        while True:
            with self.cond:
                while not self.queue:
                    self.cond.wait()
                entry = self.queue.popleft()
                self.current, self.cancel_current = entry["id"], False
            try:
                if not self.rec.find(entry["text"], self.language()):
                    self.hub.set_status(entry["id"], "recording")
                lang = self.ensure_recording(entry["text"], entry["label"] or entry["text"])
                path, filt = self.rec.play_spec(entry["text"], lang, bool(self.player_filter))
                if not path:
                    raise RuntimeError("Nie znaleziono pliku nagrania.")
                cmd = self.player_cmd + (self.player_filter(filt) if filt else []) + [path]
                with self.cond:
                    if self.cancel_current:
                        raise InterruptedError
                    self.hub.set_status(entry["id"], "speaking")
                    self.proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL,
                                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                self.proc.wait()
                self.hub.set_status(entry["id"], "cancelled" if self.cancel_current else "done")
            except InterruptedError:
                self.hub.set_status(entry["id"], "cancelled")
            except RuntimeError as exc:
                self.hub.set_status(entry["id"], "error", str(exc))
            except Exception as exc:
                traceback.print_exc()
                self.hub.set_status(entry["id"], "error", str(exc))
            finally:
                with self.cond:
                    self.current, self.proc = None, None


class BulkRecorder:
    """Nagrywanie do MP3 wszystkich kwestii z bieżącej tabeli."""

    def __init__(self, speaker):
        self.speaker = speaker
        self.lock = threading.Lock()
        self.job = None
        self.cancel = False

    def snapshot(self):
        with self.lock:
            return dict(self.job) if self.job else None

    def start(self, table, force=False):
        with self.lock:
            if self.job and self.job["running"]:
                raise RuntimeError("Nagrywanie już trwa.")
            if not self.speaker.robot.connected:
                raise RuntimeError("Połącz się z robotem - nagrania robi syntezator mowy NAO.")
            todo, seen = [], set()
            for sec in table["sections"]:
                for grp in sec["groups"]:
                    for item in grp["items"]:
                        for set_name, text in item["values"].items():
                            if text in seen:
                                continue
                            seen.add(text)
                            hint = "%s_%s" % (set_name if set_name != "default" else "", item["label"])
                            todo.append((text, hint))
            lang = self.speaker.language()
            if not force:
                todo = [t for t in todo if not self.speaker.rec.find(t[0], lang)]
            self.cancel = False
            self.job = {"running": True, "done": 0, "total": len(todo), "errors": [], "current": ""}
        threading.Thread(target=self._run, args=(todo, force), daemon=True).start()

    def _run(self, todo, force):
        for text, hint in todo:
            if self.cancel:
                break
            with self.lock:
                self.job["current"] = text[:80]
            try:
                data, lang, pitch = self.speaker.robot.synthesize(text)
                self.speaker.rec.store(text, lang, data, hint, pitch)
            except Exception as exc:
                with self.lock:
                    self.job["errors"].append("%s: %s" % (text[:40], exc))
                if not self.speaker.robot.connected:
                    break
            with self.lock:
                self.job["done"] += 1
        with self.lock:
            self.job["running"] = False
            self.job["current"] = ""
            self.job["cancelled"] = self.cancel


class DialogueStore:
    def __init__(self, initial=None):
        self.lock = threading.Lock()
        self.current = None
        self.source = None
        candidates = [initial] if initial else []
        try:
            with open(LAST_TABLE_FILE, encoding="utf-8") as fh:
                candidates.append(os.path.join(TABLES_DIR, fh.read().strip()))
        except OSError:
            pass
        candidates += [os.path.join(TABLES_DIR, f) for f in self.list_files()]
        for path in candidates:
            try:
                self.load_file(path)
                return
            except (tables.TableError, OSError) as exc:
                print("Nie udało się wczytać %s: %s" % (path, exc))

    @staticmethod
    def list_files():
        if not os.path.isdir(TABLES_DIR):
            return []
        ok = set(tables.SUPPORTED_EXT)
        return sorted(f for f in os.listdir(TABLES_DIR)
                      if os.path.splitext(f.lower())[1] in ok and not f.startswith((".", "~$")))

    def load_file(self, path):
        with open(path, "rb") as fh:
            data = fh.read()
        result = tables.load_table(data, os.path.basename(path))
        with self.lock:
            self.current, self.source = result, path
        if os.path.dirname(os.path.abspath(path)) == TABLES_DIR:
            try:
                with open(LAST_TABLE_FILE, "w", encoding="utf-8") as fh:
                    fh.write(os.path.basename(path))
            except OSError:
                pass
        return result

    def load_bytes(self, data, name):
        result = tables.load_table(data, name)
        with self.lock:
            self.current, self.source = result, None
        return result


class Handler(BaseHTTPRequestHandler):
    hub: Hub = None
    robot: RobotLink = None
    speaker: Speaker = None
    bulk: BulkRecorder = None
    store: DialogueStore = None
    demo = False
    server_version = "NaoWoZ/1.1"

    def log_message(self, fmt, *args):
        if not getattr(self, "path", "").startswith(("/api/status", "/favicon")):
            sys.stderr.write("%s - %s\n" % (self.log_date_time_string(), fmt % args))

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length > 50 * 1024 * 1024:
            raise ValueError("Plik za duży.")
        return self.rfile.read(length) if length else b""

    def _body_json(self):
        data = self._body()
        return json.loads(data.decode("utf-8")) if data else {}

    def _status(self):
        with self.hub.lock:
            s = self.robot.snapshot()
            s.update({
                "speaking": self.hub.speaking,
                "history": list(self.hub.history)[-60:],
                "demo": self.demo,
                "player": self.speaker.player_name,
                "mp3": bool(self.speaker.rec.ffmpeg),
                "rec_language": self.speaker.language(),
                "rec_version": self.speaker.rec.version,
                "pitch": self.speaker.rec.pitch_info(),
                "live_pitch": bool(self.speaker.player_filter),
            })
        s["bulk"] = self.bulk.snapshot()
        return s

    def _recorded(self):
        table, lang = self.store.current, self.speaker.language()
        have = []
        if table:
            for sec in table["sections"]:
                for grp in sec["groups"]:
                    for item in grp["items"]:
                        for set_name, text in item["values"].items():
                            if self.speaker.rec.find(text, lang):
                                have.append("%s|%s" % (item["id"], set_name))
        return {"language": lang, "have": have, "folder": os.path.relpath(self.speaker.rec.folder, BASE_DIR)}

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/api/status":
            return self._json(self._status())
        if url.path == "/api/recordings":
            return self._json(self._recorded())
        if url.path == "/api/dialogues":
            src = self.store.source
            return self._json({"table": self.store.current, "files": self.store.list_files(),
                               "source": os.path.basename(src) if src else None,
                               "supported": tables.SUPPORTED_EXT})
        return self._static(url.path)

    def do_POST(self):
        url = urlparse(self.path)
        try:
            if url.path == "/api/connect":
                body = self._body_json()
                host = (body.get("host") or "").strip()
                if not host and not self.demo:
                    raise ValueError("Podaj adres robota.")
                self.robot.connect(host or "demo", bool(body.get("manual")))
                return self._json({"ok": True})
            if url.path == "/api/disconnect":
                self.robot.disconnect()
                return self._json({"ok": True})
            if url.path == "/api/say":
                body = self._body_json()
                text = (body.get("text") or "").strip()
                if not text:
                    raise ValueError("Pusty tekst.")
                output = "speaker" if body.get("output") == "speaker" else "robot"
                entry = self.hub.new_entry(text, body.get("label", ""), output)
                if output == "speaker":
                    self.speaker.enqueue(entry)
                else:
                    self.robot.say(entry, body.get("animated", True))
                return self._json({"ok": True, "id": entry["id"]})
            if url.path == "/api/stop":
                self.speaker.stop()
                if self.robot.connected:
                    self.robot.command({"cmd": "stop"})
                return self._json({"ok": True})
            if url.path == "/api/language":
                self.robot.command({"cmd": "lang", "value": self._body_json().get("value")})
                return self._json({"ok": True})
            if url.path == "/api/volume":
                self.robot.command({"cmd": "volume", "value": int(self._body_json().get("value"))})
                return self._json({"ok": True})
            if url.path == "/api/pitch":
                value = self._body_json().get("value")
                self.speaker.rec.set_pitch(None if value is None else float(value))
                return self._json({"ok": True, "pitch": self.speaker.rec.pitch_info()})
            if url.path == "/api/record_all":
                if not self.store.current:
                    raise ValueError("Najpierw wczytaj tabelę.")
                self.bulk.start(self.store.current, bool(self._body_json().get("force")))
                return self._json({"ok": True})
            if url.path == "/api/record_all/cancel":
                self.bulk.cancel = True
                return self._json({"ok": True})
            if url.path == "/api/dialogues/file":
                name = os.path.basename(self._body_json().get("name") or "")
                path = os.path.join(TABLES_DIR, name)
                if not name or not os.path.isfile(path):
                    raise ValueError("Nie ma takiego pliku w folderze dialogi/.")
                return self._json({"ok": True, "table": self.store.load_file(path), "source": name})
            if url.path == "/api/dialogues/upload":
                name = unquote(parse_qs(url.query).get("name", ["wgrany"])[0])
                return self._json({"ok": True, "table": self.store.load_bytes(self._body(), name)})
            if url.path == "/api/dialogues/paste":
                text = self._body_json().get("text") or ""
                return self._json({"ok": True, "table": self.store.load_bytes(text.encode("utf-8"), "wklejone")})
        except (ValueError, RuntimeError, tables.TableError, OSError) as exc:
            return self._json({"ok": False, "error": str(exc)}, 400)
        except Exception as exc:
            traceback.print_exc()
            return self._json({"ok": False, "error": "Błąd: %s" % exc}, 500)
        self._json({"ok": False, "error": "Nieznany adres"}, 404)

    def _static(self, path):
        if path in ("", "/"):
            path = "/index.html"
        if path == "/favicon.ico":
            path = "/favicon.svg"
        full = os.path.normpath(os.path.join(STATIC_DIR, path.lstrip("/")))
        if not full.startswith(STATIC_DIR) or not os.path.isfile(full):
            self.send_error(404)
            return
        ctype = {".html": "text/html", ".js": "text/javascript", ".css": "text/css",
                 ".svg": "image/svg+xml", ".ico": "image/x-icon"}.get(os.path.splitext(full)[1],
                                                                       "application/octet-stream")
        with open(full, "rb") as fh:
            body = fh.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)


def main():
    p = argparse.ArgumentParser(description="NAO WoZ - panel mowy w przeglądarce")
    p.add_argument("--port", type=int, default=8080, help="port panelu WWW")
    p.add_argument("--bind", default="127.0.0.1", help="0.0.0.0 = dostęp z innych komputerów w sieci")
    p.add_argument("--robot-port", type=int, default=54331, help="port TCP, na który łączy się robot")
    p.add_argument("--table", help="tabela wczytywana na starcie (domyślnie ostatnio używana z dialogi/)")
    p.add_argument("--demo", action="store_true", help="symulowany robot (bez NAO)")
    p.add_argument("--ssh-user", default="nao")
    p.add_argument("--ssh-password", default="nao")
    p.add_argument("--remote-python", default=REMOTE_PYTHON, help="python na robocie")
    p.add_argument("--no-remote-env", action="store_true",
                   help="nie ustawiaj LD_PRELOAD/PYTHONPATH na robocie (np. dla wbudowanego pythona)")
    p.add_argument("--raw-rate", type=int, default=RAW_PCM["rate"],
                   help="częstotliwość próbkowania, gdy sayToFile zwróci surowe PCM bez nagłówka WAV")
    p.add_argument("--accept-timeout", type=int, default=30)
    p.add_argument("--no-browser", action="store_true")
    args = p.parse_args()
    RAW_PCM["rate"] = args.raw_rate

    hub = Hub()
    robot = RobotLink(args, hub)
    # demo zapisuje "piski" symulacji osobno, żeby nie pomieszać ich z prawdziwym głosem NAO
    speaker = Speaker(hub, robot, Recordings(RECORDINGS_DIR + ("_demo" if args.demo else "")))
    robot.on_pitch = speaker.rec.set_robot_pitch
    Handler.hub, Handler.robot, Handler.speaker = hub, robot, speaker
    Handler.bulk = BulkRecorder(speaker)
    Handler.store = DialogueStore(args.table)
    Handler.demo = args.demo
    if not speaker.player_cmd:
        print("UWAGA: brak odtwarzacza audio (ffplay/mpv/pw-play) - wyjście „głośnik” nie zadziała.")
    if not speaker.rec.ffmpeg:
        print("UWAGA: brak ffmpeg - nagrania będą zapisywane jako WAV zamiast MP3.")

    httpd = ThreadingHTTPServer((args.bind, args.port), Handler)
    httpd.daemon_threads = True
    url = "http://%s:%d" % ("localhost" if args.bind in ("127.0.0.1", "0.0.0.0") else args.bind, args.port)
    print("Panel operatora: %s%s" % (url, "   (tryb DEMO - symulowany robot)" if args.demo else ""))
    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        speaker.stop()
        robot.disconnect()
        if robot.local_proc:
            robot.local_proc.terminate()


if __name__ == "__main__":
    main()
