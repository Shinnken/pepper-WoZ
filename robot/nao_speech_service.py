# -*- coding: utf-8 -*-
"""Usługa mowy uruchamiana NA ROBOCIE (NAO / Pepper, NAOqi).

Łączy się zwrotnie z komputerem operatora (TCP) i wykonuje polecenia mowy.
Protokół: jedna linia JSON na wiadomość, w obie strony.

  PC -> robot: {"cmd": "say", "id": 3, "text": "...", "animated": true}
               {"cmd": "stop"} {"cmd": "lang", "value": "Polish"} {"cmd": "volume", "value": 60}
               {"cmd": "tts_file", "id": 7, "text": "..."}   (synteza do pliku, bez mówienia)
               {"cmd": "ping"} {"cmd": "exit"}
  robot -> PC: {"ev": "hello", ...} {"ev": "started", "id": 3} {"ev": "done", "id": 3}
               {"ev": "cancelled", "id": 3} {"ev": "error", "id": 3, "msg": "..."} {"ev": "state", ...}
               {"ev": "file", "id": 7, "data": "<base64>", "language": "Polish", "pitch_shift": 1.15} {"ev": "file_error", "id": 7, "msg": ""}

Działa pod Pythonem 2.7 i 3.x. Flaga --fake symuluje robota (bez qi) - do testów na PC.
"""
from __future__ import print_function

import argparse
import base64
import json
import math
import os
import struct
import socket
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


class FakeRobot(object):
    """Symulacja: 'mówi' przez czas proporcjonalny do długości tekstu."""

    def __init__(self):
        self.language = "Polish"
        self.volume = 70
        self._stop = threading.Event()

    def languages(self):
        return ["Polish", "English"]

    def say(self, text, animated):
        self._stop.clear()
        log("SAY%s: %s" % (" (anim)" if animated else "", text))
        end = time.time() + min(12.0, 0.6 + len(text) * 0.045)
        while time.time() < end:
            if self._stop.wait(0.05):
                return False
        return True

    def stop(self):
        self._stop.set()

    def pitch_shift(self):
        return 1.0

    def say_to_file(self, text, path):
        """Symulacja: krótkie dźwięki, długość zależna od tekstu."""
        rate = 22050
        seconds = min(12.0, 0.6 + len(text) * 0.045)
        frames = []
        for i in range(int(rate * seconds)):
            t = float(i) / rate
            env = 0.5 + 0.5 * math.sin(2 * math.pi * 3 * t)
            frames.append(struct.pack("<h", int(6000 * env * math.sin(2 * math.pi * (300 + 40 * (int(t * 6) % 5)) * t))))
        w = wave.open(path, "wb")
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(frames))
        w.close()

    def set_language(self, value):
        self.language = value

    def set_volume(self, value):
        self.volume = value


class QiRobot(object):
    def __init__(self, url):
        import qi
        self.session = qi.Session()
        self.session.connect(url)
        self.tts = self.session.service("ALTextToSpeech")
        self.anim = self.session.service("ALAnimatedSpeech")
        try:
            self.audio = self.session.service("ALAudioDevice")
        except Exception:
            self.audio = None
        self._stopped = False

    @property
    def language(self):
        return self.tts.getLanguage()

    @property
    def volume(self):
        return self.audio.getOutputVolume() if self.audio else None

    def languages(self):
        return list(self.tts.getAvailableLanguages())

    def say(self, text, animated):
        self._stopped = False
        if PY2 and not isinstance(text, str):
            text = text.encode("utf-8")
        if animated:
            self.anim.say(text)
        else:
            self.tts.say(text)
        return not self._stopped

    def stop(self):
        self._stopped = True
        self.tts.stopAll()

    def pitch_shift(self):
        """sayToFile zapisuje głos BEZ pitchShift, który robot nakłada przy mówieniu (NAO: 1.15)."""
        try:
            return float(self.tts.getParameter("pitchShift"))
        except Exception:
            return 1.0

    def say_to_file(self, text, path):
        if PY2 and not isinstance(text, str):
            text = text.encode("utf-8")
        self.tts.sayToFile(text, path)

    def set_language(self, value):
        self.tts.setLanguage(value)
        try:
            self.anim.setLanguage(value)  # nie wszystkie wersje NAOqi to mają
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
        self.file_jobs = queue.Queue()
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
            self.send(ev=ev, language=self.robot.language, volume=self.robot.volume,
                      languages=self.robot.languages(), pitch_shift=self.robot.pitch_shift())
        except Exception as exc:
            self.send(ev="error", msg="Nie udało się odczytać stanu robota: %s" % exc)

    def speech_worker(self):
        while self.running:
            try:
                job = self.jobs.get(timeout=0.5)
            except queue.Empty:
                continue
            if job is None:
                break
            job_id, text, animated = job
            self.current_id = job_id
            self.send(ev="started", id=job_id)
            try:
                finished = self.robot.say(text, animated)
                self.send(ev="done" if finished else "cancelled", id=job_id)
            except Exception as exc:
                self.send(ev="error", id=job_id, msg=str(exc))
            self.current_id = None

    def file_worker(self):
        """Synteza do pliku - osobna kolejka, żeby STOP i mówienie jej nie blokowały."""
        while self.running:
            try:
                job = self.file_jobs.get(timeout=0.5)
            except queue.Empty:
                continue
            if job is None:
                break
            job_id, text = job
            tmp_dir = tempfile.gettempdir() if isinstance(self.robot, FakeRobot) else "/tmp"
            path = os.path.join(tmp_dir, "naowoz_tts_%s_%s.wav" % (os.getpid(), job_id))
            try:
                self.robot.say_to_file(text, path)
                with open(path, "rb") as fh:
                    data = fh.read()
                if not data:
                    raise IOError("sayToFile utworzył pusty plik")
                self.send(ev="file", id=job_id, language=self.robot.language,
                          pitch_shift=self.robot.pitch_shift(), data=base64.b64encode(data).decode("ascii"))
            except Exception as exc:
                self.send(ev="file_error", id=job_id, msg=str(exc))
            finally:
                try:
                    os.remove(path)
                except OSError:
                    pass

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
        if cmd == "say":
            text = (msg.get("text") or "").strip()
            if text:
                self.jobs.put((msg.get("id"), text, bool(msg.get("animated", True))))
        elif cmd == "tts_file":
            self.file_jobs.put((msg.get("id"), (msg.get("text") or "").strip()))
        elif cmd == "stop":
            self.clear_queue()
            self.robot.stop()
        elif cmd == "lang":
            self.robot.set_language(msg.get("value"))
            self.send_state()
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
        file_worker = threading.Thread(target=self.file_worker)
        file_worker.daemon = True
        file_worker.start()
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
        self.file_jobs.put(None)


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
