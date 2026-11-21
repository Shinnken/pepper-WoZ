#!/usr/bin/env python3
"""NAO WoZ - odtwarzanie nagrań dialogowych. Serwer WWW dla operatora + łącze z robotem.

Dwa wyjścia dźwięku (w obu odtwarzane są wyłącznie dostarczone pliki audio z folderu nagrania/):
  robot   - NAO odtwarza plik audio ze swojego głośnika (ALAudioPlayer) + wykonuje gesty (ALAnimationPlayer)
  speaker - "narrator": ten sam plik audio odtwarzany z głośnika komputera.
Syntezator TTS robota jest całkowicie wyłączony.

Uruchom:  python3 server.py            (potem otwórz http://localhost:8080)
          python3 server.py --demo     (symulowany robot, do testów bez NAO)
"""

import argparse
import base64
import glob
import hashlib
import itertools
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import traceback
import unicodedata
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
DEFAULT_TABLE = "transfer_stylu_faza1.tsv"   # tabela startowa, gdy nie ma zapamiętanego wyboru
ROBOT_SCRIPT = os.path.join(BASE_DIR, "robot", "nao_speech_service.py")
REMOTE_SCRIPT_NAME = "nao_speech_service.py"
IS_WINDOWS = os.name == "nt"
# Na Windows procesy ffmpeg/ffplay uruchamiamy bez osobnego okna konsoli.
NO_WINDOW = {"creationflags": subprocess.CREATE_NO_WINDOW} if IS_WINDOWS else {}

# Przenośny ffmpeg rozpakowany do folderu ffmpeg\ obok server.py (ffmpeg\bin\ albo
# ffmpeg\ffmpeg-7.1-essentials_build\bin\) - działa bez zmiany PATH.
_FFMPEG_DIR = os.path.join(BASE_DIR, "ffmpeg")
for _dir in [os.path.join(_FFMPEG_DIR, "bin"), _FFMPEG_DIR] + sorted(glob.glob(os.path.join(_FFMPEG_DIR, "*", "bin"))):
    if os.path.isdir(_dir):
        os.environ["PATH"] = _dir + os.pathsep + os.environ.get("PATH", "")

# Ustawienia środowiska Pythona na robocie - skopiowane z działającego pepper-WoZ-UI-demo.
REMOTE_PYTHON = "/home/nao/apps/python3nao/bin/python3"
REMOTE_ENV = (
    'export LD_PRELOAD="/home/nao/.local/share/PackageManager/apps/python3nao/bin/libcrypt.so.1":$LD_PRELOAD && '
    'export PYTHONPATH="/data/home/nao/.local/share/PackageManager/apps/python3nao/lib/python3.9/site-packages"'
    '${PYTHONPATH:+:$PYTHONPATH} && '
)

AUDIO_EXTS = (".wav", ".mp3", ".ogg", ".flac", ".m4a", ".mp4", ".aac", ".webm", ".wma")


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


def slugify(text, limit=80):
    text = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_")
    return text[:limit].rstrip("_") or "kwestia"


def norm_key(text):
    text = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def strip_audio_exts(filename):
    """Usuwa jedno lub kilka rozszerzeń audio z końca nazwy pliku (np. 'Uprzejmy8.m4a.mp4' -> 'Uprzejmy8')."""
    base = filename
    while True:
        root, ext = os.path.splitext(base)
        if ext.lower() in AUDIO_EXTS and root:
            base = root
        else:
            break
    return base


class Hub:
    """Wspólny stan: historia wypowiedzi obu wyjść."""

    def __init__(self):
        self.lock = threading.RLock()
        self.ids = itertools.count(1)
        self.history = deque(maxlen=200)
        self.by_id = {}
        self.speaking = None

    def new_entry(self, text, label, output, audio_path=None):
        with self.lock:
            entry = {"id": next(self.ids), "text": text, "label": label, "output": output,
                     "file": os.path.basename(audio_path) if audio_path else "",
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
                self.speaking = {k: entry[k] for k in ("id", "text", "label", "output", "file")}
            elif self.speaking and self.speaking["id"] == job_id:
                self.speaking = None


class Recordings:
    """Zarządzanie dostarczonymi plikami nagrań kwestii dialogowych w folderze nagrania/.

    Rozpoznawana struktura plików (WAV, MP3, OGG, FLAC, M4A):
      1. Ścieżka z opcjonalnej kolumny `plik` / `nagranie` w tabeli
      2. nagrania/<zestaw>/<etykieta>.wav (.mp3)  np. nagrania/uprzejmy/Powitanie.wav albo 1_Owoc.wav
      3. nagrania/<zestaw>_<etykieta>.wav (.mp3)  np. nagrania/uprzejmy_Powitanie.wav
      4. nagrania/<etykieta>.wav (.mp3)           (gdy jeden zestaw lub wspólny plik)
      5. Wpisy z nagrania/manifest.json (np. wgrane przez przeciągnij-i-upuść na przycisk w UI)

    Dopasowanie nazw ignoruje wielkość liter, polskie znaki i interpunkcję
    (np. „1. Owoc?” pasuje do `1. Owoc.wav`, `1_Owoc.wav`, `1_owoc.mp3`, `Osiem_pytan_zasady.wav`).
    Dla wyjścia NAO pliki inne niż WAV są automatycznie konwertowane przez ffmpeg do WAV (cache).
    """

    def __init__(self, folder):
        self.folder = folder
        self.lock = threading.RLock()
        self.manifest_path = os.path.join(folder, "manifest.json")
        self.cache_dir = os.path.join(folder, ".robot_wav")
        self.version = 0
        self.ffmpeg = shutil.which("ffmpeg")
        self._last_sig = None
        try:
            with open(self.manifest_path, encoding="utf-8") as fh:
                self.manifest = json.load(fh)
        except (OSError, ValueError):
            self.manifest = {"items": {}, "assigned": {}}
        self.manifest.setdefault("items", {})
        self.manifest.setdefault("assigned", {})

    def _save(self):
        tmp_manifest = self.manifest_path + ".tmp"
        os.makedirs(self.folder, exist_ok=True)
        with open(tmp_manifest, "w", encoding="utf-8") as fh:
            json.dump(self.manifest, fh, ensure_ascii=False, indent=1)
        os.replace(tmp_manifest, self.manifest_path)

    def ensure_set_dirs(self, table):
        """Tworzy podfoldery nagrania/<zestaw>/ dla bieżącej tabeli, żeby łatwo wrzucić pliki."""
        os.makedirs(self.folder, exist_ok=True)
        if not table:
            return
        for s in table.get("sets") or []:
            if s and s != "default":
                os.makedirs(os.path.join(self.folder, s), exist_ok=True)

    def check_changes(self):
        """Sprawdza, czy zawartość folderu nagrania/ zmieniła się na dysku."""
        sig = []
        if os.path.isdir(self.folder):
            for root, dirs, files in os.walk(self.folder):
                dirs[:] = [d for d in sorted(dirs) if not d.startswith(".")]
                for f in sorted(files):
                    if os.path.splitext(f)[1].lower() in AUDIO_EXTS:
                        p = os.path.join(root, f)
                        try:
                            st = os.stat(p)
                            sig.append((p, st.st_mtime_ns, st.st_size))
                        except OSError:
                            pass
        sig = tuple(sig)
        with self.lock:
            if self._last_sig is not None and sig != self._last_sig:
                self.version += 1
            self._last_sig = sig
            return self.version

    @staticmethod
    def _text_key(text, lang=""):
        return hashlib.sha1(("%s\x1f%s" % (lang or "", (text or "").strip())).encode("utf-8")).hexdigest()[:16]

    def _dir_audio_files(self, directory):
        """Zwraca listę (nazwa_bez_rozsz, norm_nazwa, pelna_sciezka) dla plików audio w katalogu."""
        if not os.path.isdir(directory):
            return []
        ext_prio = {ext: i for i, ext in enumerate(AUDIO_EXTS)}
        raw = []
        try:
            names = os.listdir(directory)
        except OSError:
            return []
        for f in names:
            _, ext = os.path.splitext(f)
            ext_l = ext.lower()
            if ext_l in ext_prio and not f.startswith("."):
                full = os.path.join(directory, f)
                if os.path.isfile(full):
                    base = strip_audio_exts(f)
                    raw.append((ext_prio[ext_l], f, base, norm_key(base), full))
        raw.sort(key=lambda x: (x[0], x[1]))
        return [(base, nk, full) for _, _, base, nk, full in raw]

    def _match_in_dir(self, directory, candidates):
        """Szuka pliku w `directory` pasującego do jednej z nazw w `candidates`."""
        entries = self._dir_audio_files(directory)
        if not entries:
            return None
        for cand in candidates:
            if not cand:
                continue
            for base, _, full in entries:
                if base == cand or base.lower() == cand.lower():
                    return full
            cn = norm_key(cand)
            if not cn:
                continue
            for _, nk, full in entries:
                if nk == cn:
                    return full
        return None

    def _resolve_explicit(self, spec, set_name):
        """Rozwiązuje ścieżkę podaną wprost (np. w kolumnie `plik` albo w manifest['assigned'])."""
        if not spec:
            return None
        search_dirs = []
        if set_name and set_name != "default":
            search_dirs.append(os.path.join(self.folder, set_name))
            search_dirs.append(os.path.join(self.folder, slugify(set_name)))
        search_dirs.extend([self.folder, BASE_DIR])
        for base_dir in search_dirs:
            p = spec if os.path.isabs(spec) else os.path.join(base_dir, spec)
            if os.path.isfile(p):
                return os.path.abspath(p)
            if not os.path.splitext(p)[1]:
                for ext in AUDIO_EXTS:
                    if os.path.isfile(p + ext):
                        return os.path.abspath(p + ext)
        return None

    @staticmethod
    def _index_candidates(index, set_name):
        """Generuje warianty nazw numerowanych od 1 (np. Uprzejmy8, uprzejmy_8, 8, 08)."""
        if not index:
            return [], []
        idx_s = str(int(index))
        idx_pad = "%02d" % int(index)
        with_set = []
        if set_name and set_name != "default":
            for s in (set_name, slugify(set_name), norm_key(set_name)):
                for n in (idx_s, idx_pad):
                    with_set.extend(["%s%s" % (s, n), "%s_%s" % (s, n), "%s-%s" % (s, n)])
        bare = [idx_s, idx_pad]
        return with_set, bare

    def resolve(self, label="", set_name="", text="", explicit_file="", item_id="", index=None):
        """Zwraca pełną ścieżkę do pliku nagrania dla danej kwestii albo None."""
        with self.lock:
            # 1. Jawnie przypisany plik w UI (przeciągnij i upuść na przycisk)
            if item_id:
                for akey in ("%s|%s" % (item_id, set_name), "%s|default" % item_id, item_id):
                    assigned = self.manifest.get("assigned", {}).get(akey)
                    if assigned:
                        p = self._resolve_explicit(assigned, set_name)
                        if p:
                            return p

            # 2. Kolumna `plik` / `nagranie` z tabeli
            if explicit_file:
                p = self._resolve_explicit(explicit_file, set_name)
                if p:
                    return p

            idx_with_set, idx_bare = self._index_candidates(index, set_name)
            label_cands = []
            if label:
                label_cands.extend([label, slugify(label)])
            if text and text != label:
                label_cands.append(slugify(text, 50))

            set_dirs = []
            if set_name and set_name != "default":
                for dname in (set_name, slugify(set_name), norm_key(set_name)):
                    dpath = os.path.join(self.folder, dname)
                    if os.path.isdir(dpath) and dpath not in set_dirs:
                        set_dirs.append(dpath)
                if os.path.isdir(self.folder):
                    sn = norm_key(set_name)
                    try:
                        for sub in sorted(os.listdir(self.folder)):
                            sub_p = os.path.join(self.folder, sub)
                            if os.path.isdir(sub_p) and not sub.startswith(".") and norm_key(sub) == sn and sub_p not in set_dirs:
                                set_dirs.append(sub_p)
                    except OSError:
                        pass

            # 3. Katalogi zestawu: nagrania/<zestaw>/ (np. Uprzejmy8.m4a.mp4, 8.mp4, Powitanie.wav)
            for sdir in set_dirs:
                p = self._match_in_dir(sdir, idx_with_set + idx_bare + label_cands)
                if p:
                    return p

            # 4. Główny folder nagrania/: najpierw <zestaw><nr> (np. Uprzejmy8.m4a.mp4) i <zestaw>_<etykieta>, potem <nr> / <etykieta>
            root_cands = list(idx_with_set)
            if set_name and set_name != "default":
                for c in label_cands:
                    root_cands.append("%s_%s" % (set_name, c))
                    root_cands.append("%s_%s" % (slugify(set_name), c))
            root_cands.extend(idx_bare)
            root_cands.extend(label_cands)
            p = self._match_in_dir(self.folder, root_cands)
            if p:
                return p

            # 5. Wpisy w manifest.json po kluczu tekstu (kompatybilność wsteczna)
            if text:
                for lang in (self.manifest.get("last_language") or "Polish", "Polish", ""):
                    info = self.manifest.get("items", {}).get(self._text_key(text, lang))
                    if info:
                        for field in ("file", "source"):
                            if info.get(field):
                                fp = os.path.join(self.folder, info[field])
                                if os.path.isfile(fp):
                                    return fp
        return None

    def assign_upload(self, item_id, set_name, label, filename, data, index=None):
        """Zapisuje wgrany plik audio dla danej kwestii w nagrania/<zestaw>/<Zestaw><nr>.<ext>."""
        if not data:
            raise ValueError("Plik audio jest pusty.")
        ext = os.path.splitext(filename or "")[1].lower()
        if ext not in AUDIO_EXTS:
            raise ValueError("Nieobsługiwany format audio (%s). Użyj: %s" % (ext or "brak", ", ".join(AUDIO_EXTS)))
        sub = slugify(set_name) if (set_name and set_name != "default") else ""
        if set_name and set_name != "default" and os.path.isdir(os.path.join(self.folder, set_name)):
            sub = set_name
        target_dir = os.path.join(self.folder, sub) if sub else self.folder
        os.makedirs(target_dir, exist_ok=True)
        if index:
            prefix = slugify(set_name).capitalize() if (set_name and set_name != "default") else ""
            base_name = "%s%d" % (prefix, int(index))
        else:
            base_name = slugify(label or strip_audio_exts(filename) or "kwestia")
        out_path = os.path.join(target_dir, base_name + ext)
        tmp_path = out_path + ".tmp"
        with open(tmp_path, "wb") as fh:
            fh.write(data)
        os.replace(tmp_path, out_path)
        rel = os.path.relpath(out_path, self.folder)
        with self.lock:
            if item_id:
                self.manifest.setdefault("assigned", {})["%s|%s" % (item_id, set_name or "default")] = rel
                self._save()
            self.version += 1
            self._last_sig = None
        return rel

    def prepare_for_speaker(self, path):
        """Zwraca ścieżkę gotową do odtworzenia na PC (bez obrazu wideo dla .mp4/.webm)."""
        ext = os.path.splitext(path)[1].lower()
        if ext in (".mp4", ".webm") and self.ffmpeg:
            wav_name, _ = self.prepare_for_robot(path)
            cached = os.path.join(self.cache_dir, wav_name)
            if os.path.isfile(cached):
                return cached
        return path

    def prepare_for_robot(self, path):
        """Zwraca (nazwa_pliku, bajty) gotowe do wysłania na NAO.
        Jeśli plik nie jest WAV, a dostępny jest ffmpeg, konwertuje go do WAV 16-bit PCM (z cache)."""
        ext = os.path.splitext(path)[1].lower()
        if ext != ".wav":
            if not self.ffmpeg:
                raise RuntimeError("Plik %s wymaga ffmpeg do wyciągnięcia dźwięku (WAV) dla robota."
                                   % os.path.basename(path))
            st = os.stat(path)
            key = hashlib.sha1(("%s|%d|%d" % (path, st.st_mtime_ns, st.st_size)).encode("utf-8")).hexdigest()[:16]
            os.makedirs(self.cache_dir, exist_ok=True)
            cached = os.path.join(self.cache_dir, "%s_%s.wav" % (slugify(os.path.splitext(os.path.basename(path))[0], 40), key))
            if not os.path.isfile(cached):
                tmp = cached + ".tmp.wav"
                proc = subprocess.run(
                    [self.ffmpeg, "-y", "-loglevel", "error", "-i", path, "-vn",
                     "-acodec", "pcm_s16le", "-ac", "1", "-ar", "22050", tmp],
                    capture_output=True, text=True, encoding="utf-8", errors="replace", **NO_WINDOW
                )
                if proc.returncode != 0 or not os.path.isfile(tmp):
                    try:
                        os.remove(tmp)
                    except OSError:
                        pass
                    raise RuntimeError("ffmpeg nie mógł odczytać dźwięku z %s: %s"
                                       % (os.path.basename(path), proc.stderr.strip()[-200:]))
                os.replace(tmp, cached)
            path = cached
        with open(path, "rb") as fh:
            return os.path.basename(path), fh.read()


def find_player():
    """(nazwa, polecenie) lokalnego odtwarzacza audio na PC."""
    candidates = (
        ("ffplay", ["-nodisp", "-autoexit", "-loglevel", "quiet"]),
        ("mpv", ["--no-video", "--really-quiet"]),
        ("pw-play", []), ("paplay", []), ("aplay", ["-q"]),
    )
    for name, args in candidates:
        path = shutil.which(name)
        if path:
            return name, [path] + args
    return None, None


class RobotLink:
    """Połączenie TCP z usługą na robocie (robot łączy się do nas)."""

    def __init__(self, args, hub):
        self.args = args
        self.hub = hub
        self.lock = hub.lock
        self.status = "disconnected"   # disconnected | connecting | connected
        self.message = ""
        self.error = ""
        self.host = ""
        self.conn = None
        self.volume = None
        self.generation = 0
        self.local_proc = None
        self.pending_robot = set()   # wypowiedzi wysłane do robota, jeszcze niezakończone

    @property
    def connected(self):
        return self.status == "connected"

    def snapshot(self):
        return {"status": self.status, "message": self.message, "error": self.error,
                "host": self.host, "volume": self.volume}

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

    def play(self, entry, filename, raw_bytes, animated):
        b64 = base64.b64encode(raw_bytes).decode("ascii")
        with self.lock:
            if not self.connected:
                self.hub.set_status(entry["id"], "error", "Robot nie jest połączony.")
                raise RuntimeError("Robot nie jest połączony.")
            self.pending_robot.add(entry["id"])
            self._send_locked({"cmd": "play", "id": entry["id"], "name": filename,
                               "data": b64, "animated": bool(animated)})

    def command(self, msg):
        with self.lock:
            if not self.connected:
                raise RuntimeError("Robot nie jest połączony.")
            self._send_locked(msg)

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
            self.volume = msg.get("volume", self.volume)
        elif ev == "started":
            self.hub.set_status(job_id, "speaking")
        elif ev in ("done", "cancelled"):
            self.pending_robot.discard(job_id)
            self.hub.set_status(job_id, ev)
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
            _, out, _ = ssh.exec_command("pkill -f '[n]ao_speech_service.py'; true")
            out.channel.recv_exit_status()
            env = "" if self.args.no_remote_env else REMOTE_ENV
            command = ("%ssetsid nohup %s %s --host %s --port %d > /tmp/nao_speech.log 2>&1 < /dev/null &"
                       % (env, self.args.remote_python, remote_path, my_ip, self.args.robot_port))
            _, out, err = ssh.exec_command(command)
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
    """Wyjście "narrator": odtwarzanie dostarczonych plików audio z głośnika PC."""

    def __init__(self, hub, recordings):
        self.hub, self.rec = hub, recordings
        self.player_name, self.player_cmd = find_player()
        self.queue = deque()
        self.cond = threading.Condition(hub.lock)
        self.current = None
        self.proc = None
        self.cancel_current = False
        threading.Thread(target=self._worker, daemon=True).start()

    def enqueue(self, entry, path):
        if not self.player_cmd:
            self.hub.set_status(entry["id"], "error", "Brak odtwarzacza")
            raise RuntimeError("Brak odtwarzacza audio (zainstaluj ffmpeg albo mpv).")
        with self.cond:
            self.queue.append((entry, path))
            self.cond.notify()

    def stop(self):
        with self.cond:
            while self.queue:
                self.hub.set_status(self.queue.popleft()[0]["id"], "cancelled")
            if self.current is not None:
                self.cancel_current = True
            proc = self.proc
        if proc and proc.poll() is None:
            proc.terminate()

    def _worker(self):
        while True:
            with self.cond:
                while not self.queue:
                    self.cond.wait()
                entry, path = self.queue.popleft()
                self.current, self.cancel_current = entry["id"], False
            try:
                if not path or not os.path.isfile(path):
                    raise RuntimeError("Nie znaleziono pliku nagrania.")
                play_path = self.rec.prepare_for_speaker(path)
                cmd = self.player_cmd + [play_path]
                with self.cond:
                    if self.cancel_current:
                        raise InterruptedError
                    self.hub.set_status(entry["id"], "speaking")
                    self.proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL,
                                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                                 **NO_WINDOW)
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
        # bez zapamiętanego wyboru (świeży klon, .ostatnia_tabela jest w .gitignore) startujemy
        # z tabelą z procedury, a nie z pierwszą alfabetycznie
        candidates.append(os.path.join(TABLES_DIR, DEFAULT_TABLE))
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
    store: DialogueStore = None
    demo = False
    server_version = "NaoWoZ/2.0"

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
        rec_ver = self.speaker.rec.check_changes()
        with self.hub.lock:
            s = self.robot.snapshot()
            s.update({
                "speaking": self.hub.speaking,
                "history": list(self.hub.history)[-60:],
                "demo": self.demo,
                "player": self.speaker.player_name,
                "rec_version": rec_ver,
            })
        return s

    def _recorded(self):
        table = self.store.current
        have = []
        files = {}
        if table:
            self.speaker.rec.ensure_set_dirs(table)
            for sec in table["sections"]:
                for grp in sec["groups"]:
                    for item in grp["items"]:
                        for set_name, text in item["values"].items():
                            explicit = (item.get("files") or {}).get(set_name, "")
                            p = self.speaker.rec.resolve(
                                label=item["label"], set_name=set_name,
                                text=text, explicit_file=explicit, item_id=item["id"],
                                index=item.get("index")
                            )
                            if p:
                                key = "%s|%s" % (item["id"], set_name)
                                have.append(key)
                                try:
                                    files[key] = os.path.relpath(p, self.speaker.rec.folder)
                                except ValueError:
                                    files[key] = os.path.basename(p)
        return {"have": have, "files": files, "folder": os.path.relpath(self.speaker.rec.folder, BASE_DIR)}

    def _find_item(self, item_id):
        table = self.store.current
        if not table or not item_id:
            return None
        for sec in table["sections"]:
            for grp in sec["groups"]:
                for item in grp["items"]:
                    if item["id"] == item_id:
                        return item
        return None

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
                label = (body.get("label") or "").strip()
                set_name = (body.get("set") or "").strip()
                item_id = (body.get("item_id") or "").strip()
                explicit_file = (body.get("file") or "").strip()
                item_index = body.get("index")
                item = self._find_item(item_id)
                if item:
                    label = label or item["label"]
                    if not item_index:
                        item_index = item.get("index")
                    if not explicit_file:
                        files_map = item.get("files") or {}
                        explicit_file = files_map.get(set_name) or files_map.get("default") or ""
                    if not text:
                        vals = item.get("values") or {}
                        text = vals.get(set_name) or vals.get("default") or label
                path = self.speaker.rec.resolve(
                    label=label, set_name=set_name, text=text,
                    explicit_file=explicit_file, item_id=item_id, index=item_index
                )
                if not path:
                    prefix = slugify(set_name).capitalize() if (set_name and set_name != "default") else ""
                    num_hint = "%s%s.mp4 (lub %s.mp4)" % (prefix, item_index, item_index) if item_index else "%s.mp4" % slugify(label or "1")
                    raise RuntimeError(
                        "Brak pliku nagrania dla kwestii #%s „%s” (zestaw: %s). "
                        "Wrzuć plik np. %s do folderu nagrania/ (lub przeciągnij go na przycisk)."
                        % (item_index or "?", label or text[:40] or "?", set_name or "domyślny", num_hint)
                    )
                output = "speaker" if body.get("output") == "speaker" else "robot"
                entry = self.hub.new_entry(text or label or os.path.basename(path), label, output, path)
                if output == "speaker":
                    self.speaker.enqueue(entry, path)
                else:
                    fname, raw_bytes = self.speaker.rec.prepare_for_robot(path)
                    self.robot.play(entry, fname, raw_bytes, body.get("animated", True))
                return self._json({"ok": True, "id": entry["id"], "file": os.path.basename(path)})
            if url.path == "/api/recordings/upload":
                q = parse_qs(url.query)
                item_id = unquote(q.get("item_id", [""])[0]).strip()
                set_name = unquote(q.get("set", ["default"])[0]).strip() or "default"
                label = unquote(q.get("label", [""])[0]).strip()
                name = unquote(q.get("name", ["audio.wav"])[0]).strip()
                item = self._find_item(item_id)
                item_index = item.get("index") if item else None
                if item and not label:
                    label = item["label"]
                rel = self.speaker.rec.assign_upload(item_id, set_name, label, name, self._body(), index=item_index)
                return self._json({"ok": True, "file": rel})
            if url.path == "/api/stop":
                self.speaker.stop()
                if self.robot.connected:
                    self.robot.command({"cmd": "stop"})
                return self._json({"ok": True})
            if url.path == "/api/volume":
                self.robot.command({"cmd": "volume", "value": int(self._body_json().get("value"))})
                return self._json({"ok": True})
            if url.path == "/api/dialogues/file":
                name = os.path.basename(self._body_json().get("name") or "")
                path = os.path.join(TABLES_DIR, name)
                if not name or not os.path.isfile(path):
                    raise ValueError("Nie ma takiego pliku w folderze dialogi/.")
                tbl = self.store.load_file(path)
                self.speaker.rec.ensure_set_dirs(tbl)
                return self._json({"ok": True, "table": tbl, "source": name})
            if url.path == "/api/dialogues/upload":
                name = unquote(parse_qs(url.query).get("name", ["wgrany"])[0])
                tbl = self.store.load_bytes(self._body(), name)
                self.speaker.rec.ensure_set_dirs(tbl)
                return self._json({"ok": True, "table": tbl})
            if url.path == "/api/dialogues/paste":
                text = self._body_json().get("text") or ""
                tbl = self.store.load_bytes(text.encode("utf-8"), "wklejone")
                self.speaker.rec.ensure_set_dirs(tbl)
                return self._json({"ok": True, "table": tbl})
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
    p = argparse.ArgumentParser(description="NAO WoZ - panel odtwarzania nagrań dialogowych")
    p.add_argument("--port", type=int, default=8080, help="port panelu WWW")
    p.add_argument("--bind", default="127.0.0.1", help="0.0.0.0 = dostęp z innych komputerów w sieci")
    p.add_argument("--robot-port", type=int, default=54331, help="port TCP, na który łączy się robot")
    p.add_argument("--table", help="tabela wczytywana na starcie (domyślnie ostatnio używana z dialogi/)")
    p.add_argument("--recordings", default=RECORDINGS_DIR, help="folder z plikami nagrań audio (domyślnie nagrania/)")
    p.add_argument("--demo", action="store_true", help="symulowany robot (bez NAO)")
    p.add_argument("--ssh-user", default="nao")
    p.add_argument("--ssh-password", default="nao")
    p.add_argument("--remote-python", default=REMOTE_PYTHON, help="python na robocie")
    p.add_argument("--no-remote-env", action="store_true",
                   help="nie ustawiaj LD_PRELOAD/PYTHONPATH na robocie (np. dla wbudowanego pythona)")
    p.add_argument("--accept-timeout", type=int, default=30)
    p.add_argument("--no-browser", action="store_true")
    args = p.parse_args()
    # konsola Windows nie zawsze jest w UTF-8 - polskie znaki w komunikatach nie mogą wywalić serwera
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    hub = Hub()
    robot = RobotLink(args, hub)
    recordings = Recordings(os.path.abspath(args.recordings))
    speaker = Speaker(hub, recordings)
    store = DialogueStore(args.table)
    recordings.ensure_set_dirs(store.current)
    Handler.hub, Handler.robot, Handler.speaker = hub, robot, speaker
    Handler.store = store
    Handler.demo = args.demo
    if not speaker.player_cmd:
        print("UWAGA: brak odtwarzacza audio (ffplay/mpv/pw-play) - wyjście „głośnik” nie zadziała.")
        if IS_WINDOWS:
            print("       Rozpakuj ffmpeg (wersja z ffplay.exe) do folderu ffmpeg\\ obok server.py.")

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
