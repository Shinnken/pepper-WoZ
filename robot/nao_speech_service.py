# -*- coding: utf-8 -*-
"""Usługa odtwarzania nagrań uruchamiana NA ROBOCIE (NAO / Pepper, NAOqi).

Łączy się zwrotnie z komputerem operatora (TCP) i odtwarza dostarczone pliki audio (ALAudioPlayer)
z opcjonalną gestykulacją w trakcie mówienia (ALAnimationPlayer). Syntezator TTS jest wyłączony.
Protokół: jedna linia JSON na wiadomość, w obie strony.

  PC -> robot: {"cmd": "play", "id": 3, "name": "Powitanie.wav", "data": "<base64>", "animated": true}
               {"cmd": "stop"} {"cmd": "volume", "value": 60}
               {"cmd": "ping"} {"cmd": "exit"}
  robot -> PC: {"ev": "hello", ...} {"ev": "started", "id": 3} {"ev": "done", "id": 3}
               {"ev": "cancelled", "id": 3} {"ev": "error", "id": 3, "msg": "..."} {"ev": "state", ...}

Działa pod Pythonem 2.7 i 3.x. Flaga --fake symuluje robota (bez qi) - do testów na PC.
"""
from __future__ import print_function

import argparse
import base64
import hashlib
import json
import os
import random
import re
import socket
import struct
import sys
import tempfile
import threading
import time
import wave

try:
    import queue
except ImportError:  # Python 2
    import Queue as queue

PY2 = sys.version_info[0] == 2


def log(*args):
    print("[nao_speech]", *args)
    sys.stdout.flush()


def wav_duration(data):
    """Szacuje długość pliku WAV w sekundach (do symulacji --fake)."""
    try:
        if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
            pos, rate, channels, bits = 12, 22050, 1, 16
            while pos + 8 <= len(data):
                cid = data[pos:pos + 4]
                size = struct.unpack("<I", data[pos + 4:pos + 8])[0]
                body = pos + 8
                if cid == b"fmt " and size >= 16:
                    _, channels, rate, _, _, bits = struct.unpack("<HHIIHH", data[body:body + 16])
                elif cid == b"data":
                    end = min(len(data), body + size) if size not in (0, 0xFFFFFFFF) else len(data)
                    bps = max(1, rate * channels * (bits // 8))
                    return max(0.4, float(end - body) / bps)
                pos = body + size + (size & 1)
    except Exception:
        pass
    return max(1.0, min(12.0, len(data) / 44100.0))


class FakeRobot(object):
    """Symulacja: 'odtwarza' plik przez czas odpowiadający jego długości."""

    def __init__(self):
        self.volume = 70
        self._stop = threading.Event()
        self.cache_dir = os.path.join(tempfile.gettempdir(), "naowoz_audio_fake")
        try:
            os.makedirs(self.cache_dir)
        except OSError:
            pass

    def play_audio(self, path, animated):
        self._stop.clear()
        try:
            with open(path, "rb") as fh:
                dur = wav_duration(fh.read(512 * 1024))
        except Exception:
            dur = 2.0
        log("PLAY%s (%.1fs): %s" % (" (anim)" if animated else "", dur, os.path.basename(path)))
        end = time.time() + dur
        while time.time() < end:
            if self._stop.wait(0.05):
                return False
        return True

    def stop(self):
        self._stop.set()

    def set_volume(self, value):
        self.volume = int(value)


# Standardowe animacje gestykulacji podczas mówienia w NAOqi (animations/Stand/Gestures/*)
SPEAKING_GESTURES = [
    "animations/Stand/Gestures/Explain_1",
    "animations/Stand/Gestures/Explain_2",
    "animations/Stand/Gestures/Explain_3",
    "animations/Stand/Gestures/Explain_4",
    "animations/Stand/Gestures/Explain_5",
    "animations/Stand/Gestures/Explain_6",
    "animations/Stand/Gestures/Explain_7",
    "animations/Stand/Gestures/Explain_8",
    "animations/Stand/Gestures/Explain_10",
    "animations/Stand/Gestures/Explain_11",
    "animations/Stand/Gestures/You_1",
    "animations/Stand/Gestures/You_4",
    "animations/Stand/Gestures/Me_1",
    "animations/Stand/Gestures/Me_2",
    "animations/Stand/Gestures/Give_3",
    "animations/Stand/Gestures/Give_4",
    "animations/Stand/Gestures/ShowFloor_1",
    "animations/Stand/Gestures/ShowFloor_3",
]


class QiRobot(object):
    def __init__(self, url):
        import qi
        self.session = qi.Session()
        self.session.connect(url)
        self.player = self.session.service("ALAudioPlayer")
        try:
            self.audio = self.session.service("ALAudioDevice")
        except Exception:
            self.audio = None
        try:
            self.anim_player = self.session.service("ALAnimationPlayer")
        except Exception:
            self.anim_player = None
        try:
            self.posture = self.session.service("ALRobotPosture")
        except Exception:
            self.posture = None
        self._stopped = False
        self.cache_dir = "/tmp/naowoz_audio"
        try:
            os.makedirs(self.cache_dir)
        except OSError:
            pass

    @property
    def volume(self):
        return self.audio.getOutputVolume() if self.audio else None

    def _gesture_loop(self, done_event):
        if not self.anim_player:
            return
        last = None
        while not done_event.is_set() and not self._stopped:
            choices = [g for g in SPEAKING_GESTURES if g != last]
            gesture = random.choice(choices)
            last = gesture
            try:
                fut = self.anim_player.run(gesture, _async=True)
                while not fut.isFinished():
                    if done_event.wait(0.08) or self._stopped:
                        try:
                            self.anim_player.stopAll()
                        except Exception:
                            pass
                        return
            except Exception:
                try:
                    self.anim_player.runTag("explain")
                except Exception:
                    return
            if done_event.wait(0.15):
                break

    def play_audio(self, path, animated):
        self._stopped = False
        if PY2 and not isinstance(path, str):
            path = path.encode("utf-8")
        done_event = threading.Event()
        g_thread = None
        if animated and self.anim_player:
            g_thread = threading.Thread(target=self._gesture_loop, args=(done_event,))
            g_thread.daemon = True
            g_thread.start()
        try:
            self.player.playFile(path)
        finally:
            done_event.set()
            if self.anim_player:
                try:
                    self.anim_player.stopAll()
                except Exception:
                    pass
            if g_thread:
                g_thread.join(timeout=1.0)
        return not self._stopped

    def stop(self):
        self._stopped = True
        try:
            self.player.stopAll()
        except Exception:
            pass
        if self.anim_player:
            try:
                self.anim_player.stopAll()
            except Exception:
                pass

    def set_volume(self, value):
        if self.audio:
            self.audio.setOutputVolume(int(value))


class Service(object):
    def __init__(self, robot, sock):
        self.robot = robot
        self.sock = sock
        self.send_lock = threading.Lock()
        self.jobs = queue.Queue()
        self.running = True
        self.current_id = None

    def send(self, **msg):
        data = (json.dumps(msg) + "\n").encode("utf-8")
        with self.send_lock:
            try:
                self.sock.sendall(data)
            except socket.error as exc:
                log("send failed:", exc)
                self.running = False

    def send_state(self, ev="state"):
        try:
            self.send(ev=ev, volume=self.robot.volume)
        except Exception as exc:
            self.send(ev="error", msg="Nie udało się odczytać stanu robota: %s" % exc)

    def _store_audio(self, name, raw_bytes):
        ext = os.path.splitext(name or "")[1].lower()
        if ext not in (".wav", ".mp3", ".ogg", ".flac"):
            ext = ".wav"
        digest = hashlib.sha1(raw_bytes).hexdigest()[:16]
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", os.path.splitext(os.path.basename(name or "audio"))[0])[:40]
        fname = "%s_%s%s" % (safe or "audio", digest, ext)
        path = os.path.join(self.robot.cache_dir, fname)
        if not os.path.isfile(path) or os.path.getsize(path) != len(raw_bytes):
            tmp = path + ".tmp.%s" % threading.current_thread().ident
            with open(tmp, "wb") as fh:
                fh.write(raw_bytes)
            try:
                os.replace(tmp, path)
            except AttributeError:  # Python 2
                if os.path.exists(path):
                    try:
                        os.remove(path)
                    except OSError:
                        pass
                os.rename(tmp, path)
        return path

    def speech_worker(self):
        while self.running:
            try:
                job = self.jobs.get(timeout=0.5)
            except queue.Empty:
                continue
            if job is None:
                break
            job_id, name, raw_bytes, animated = job
            self.current_id = job_id
            self.send(ev="started", id=job_id)
            try:
                path = self._store_audio(name, raw_bytes)
                finished = self.robot.play_audio(path, animated)
                self.send(ev="done" if finished else "cancelled", id=job_id)
            except Exception as exc:
                self.send(ev="error", id=job_id, msg=str(exc))
            self.current_id = None

    def clear_queue(self):
        while True:
            try:
                job = self.jobs.get_nowait()
            except queue.Empty:
                return
            if job is not None:
                self.send(ev="cancelled", id=job[0])

    def handle(self, msg):
        cmd = msg.get("cmd")
        if cmd == "play":
            b64 = msg.get("data") or ""
            raw_bytes = base64.b64decode(b64.encode("ascii") if PY2 else b64)
            if not raw_bytes:
                self.send(ev="error", id=msg.get("id"), msg="Pusty plik audio.")
                return
            self.jobs.put((msg.get("id"), msg.get("name") or "audio.wav",
                           raw_bytes, bool(msg.get("animated", True))))
        elif cmd == "stop":
            self.clear_queue()
            self.robot.stop()
        elif cmd == "volume":
            self.robot.set_volume(msg.get("value"))
            self.send_state()
        elif cmd == "ping":
            self.send(ev="pong")
        elif cmd == "exit":
            self.running = False
        else:
            self.send(ev="error", msg="Nieznane polecenie: %s" % cmd)

    def run(self):
        worker = threading.Thread(target=self.speech_worker)
        worker.daemon = True
        worker.start()
        self.send_state("hello")
        reader = self.sock.makefile("rb")
        while self.running:
            line = reader.readline()
            if not line:
                log("connection closed by PC")
                break
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line.decode("utf-8"))
            except ValueError:
                log("bad message:", line[:200])
                continue
            try:
                self.handle(msg)
            except Exception as exc:
                self.send(ev="error", msg=str(exc))
        self.running = False
        self.clear_queue()
        try:
            self.robot.stop()
        except Exception:
            pass
        self.jobs.put(None)


def connect(host, port, timeout):
    deadline = time.time() + timeout
    while True:
        try:
            sock = socket.create_connection((host, port), timeout=5)
            sock.settimeout(None)
            return sock
        except socket.error as exc:
            if time.time() > deadline:
                raise
            log("waiting for PC %s:%s (%s)" % (host, port, exc))
            time.sleep(1)


def main():
    parser = argparse.ArgumentParser(description="NAO speech service (WoZ)")
    parser.add_argument("--host", required=True, help="IP komputera operatora")
    parser.add_argument("--port", type=int, default=54331)
    parser.add_argument("--qi", default="tcp://127.0.0.1:9559", help="adres NAOqi")
    parser.add_argument("--fake", action="store_true", help="symulacja bez robota")
    parser.add_argument("--connect-timeout", type=float, default=30.0)
    args = parser.parse_args()

    robot = FakeRobot() if args.fake else QiRobot(args.qi)
    sock = connect(args.host, args.port, args.connect_timeout)
    log("connected to %s:%s" % (args.host, args.port))
    Service(robot, sock).run()
    sock.close()
    log("bye")


if __name__ == "__main__":
    main()
