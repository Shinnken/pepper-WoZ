import socket
import threading
from video_maker import make_video_from_frames
import time
import os
class TCPSocketHandler:
    """
    Responsible for sending commands to Pepper camera service
    """
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.bind((self.host, self.port))

    def start(self) -> None | tuple[str, int]:
        self.socket.listen(1)
        self.socket.settimeout(5)  # Set a timeout for the accept call

    def accept_connection(self):
        self.conn, addr = self.socket.accept()
        print(f"Connection accepted from {addr}")
        return addr

    def exit(self):
        self.socket.close()
        if hasattr(self, "conn"):
            self.conn.close()

    def send(self, data: bytes):
        if hasattr(self, "conn"):
            self.conn.sendall(data)
    
    def receive(self, lenght: int):
        if hasattr(self, "conn"):
            return self.conn.recv(lenght)

    def set_timeout(self, timeout_sec: float | None):
        if hasattr(self, "conn"):
            try:
                self.conn.settimeout(timeout_sec if timeout_sec is not None else 0.0)
            except Exception:
                pass

    def receive_line(self, max_len: int = 4096, timeout: float | None = None) -> bytes | None:
        if not hasattr(self, "conn"):
            return None
        try:
            if timeout is not None:
                self.conn.settimeout(timeout)
            buf = bytearray()
            while len(buf) < max_len:
                ch = self.conn.recv(1)
                if not ch:
                    break
                buf += ch
                if ch == b"\n":
                    break
            return bytes(buf) if buf else None
        except socket.timeout:
            return None
        except Exception:
            return None

    def receive_exact(self, nbytes: int, timeout: float | None = None) -> bytes | None:
        if not hasattr(self, "conn"):
            return None
        try:
            if timeout is not None:
                self.conn.settimeout(timeout)
            chunks = []
            total = 0
            while total < nbytes:
                chunk = self.conn.recv(min(65536, nbytes - total))
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
            return b"".join(chunks) if total == nbytes else None
        except socket.timeout:
            return None
        except Exception:
            return None

    

class UDPSocketHandler(threading.Thread):
    """
    Responsible for receiving frames form Pepper camera service
    """
    def __init__(self, host, port):
        threading.Thread.__init__(self)
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Increase kernel receive buffer to reduce UDP drops on bursts (e.g., during audio send)
        try:
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 16 * 1024 * 1024)
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        except Exception:
            pass
        self.socket.bind((host, port))
        # Allow periodic checks instead of blocking forever on recv
        try:
            self.socket.settimeout(0.2)
        except Exception:
            pass
        # State
        self.running = False
        self.listening = False
        self.frames = []
        self.frames_countdown = -1
        self.patient_id = 0
        self.audio_bytes = None
        self.audio_done = False
        # Timers/markers
        self._frames_zero_at = None  # timestamp when frames_countdown reached 0
        self._last_packet_ts = None  # last time any UDP packet was received
        # Audio assemble buffers
        self._pre_audio_chunks = []  # audio data that may arrive before AUDIO_START due to UDP reordering
        self._pre_audio_bytes = 0
        self._audio_chunks = 0
        self._audio_bytes_accum = 0
        # Config flags
        env_flag = os.getenv('PEPPER_MUX_AUDIO', '1').strip().lower()
        self.mux_audio = env_flag not in ('0', 'false', 'no', 'off')
        # If PEPPER_TCP_AUDIO=1, we won't receive audio via UDP; instead, TCPSocketHandler will deliver it.
        tcp_audio_flag = os.getenv('PEPPER_TCP_AUDIO', '1').strip().lower()
        self.use_udp_audio = tcp_audio_flag in ('0', 'false', 'no', 'off')

    def set_patient_id(self, patient_id: int):
        self.patient_id = patient_id


    def run(self):
        RECV_SIZE = 1400
        self.running = True
        bytes_received = b""
        receiving_audio = False
        audio_buf = b""
        while self.running:
            if not self.listening:
                time.sleep(0.1)
                continue

            # Keep receiving while there are frames remaining OR a partial frame in progress
            need_more_video = (self.frames_countdown != 0) or (len(bytes_received) > 0)
            need_more_audio = (not self.audio_done)
            now = time.time()
            # If frames finished but audio hasn’t arrived for a while, finalize without audio (graceful timeout)
            if (self.frames_countdown == 0) and (not self.audio_done) and self._frames_zero_at is not None:
                # Longer timeout before audio starts
                no_audio_yet = not receiving_audio and (now - self._frames_zero_at > 10.0)
                # If audio started but stalled (no packets), allow stall timeout
                stalled = receiving_audio and (self._last_packet_ts is not None) and (now - self._last_packet_ts > 8.0)
                if no_audio_yet:
                    if self._pre_audio_bytes > 0:
                        # Assume start marker lost; promote pre-audio to real audio
                        print("Promoting pre-audio buffer ({} bytes) to audio due to missing AUDIO_START.".format(self._pre_audio_bytes))
                        audio_buf = b"".join(self._pre_audio_chunks)
                        self._pre_audio_chunks = []
                        self._pre_audio_bytes = 0
                        self.audio_bytes = audio_buf
                        self.audio_done = True
                    else:
                        print("Audio timed out waiting to start; finalizing without audio.")
                        self.audio_done = True
                elif stalled:
                    # If we accumulated any audio, finalize with what we have (assume AUDIO_END lost)
                    if self._audio_bytes_accum > 0:
                        print("Audio stalled after start; finalizing with {} bytes (missing AUDIO_END).".format(self._audio_bytes_accum))
                        self.audio_bytes = audio_buf
                        self.audio_done = True
                    else:
                        print("Audio stalled with no data; finalizing without audio.")
                        self.audio_done = True
            # If frame count is unknown (<0) but we received at least one frame and saw no packets recently,
            # assume frames are done and arm audio timeout
            if (self.frames_countdown < 0) and (len(self.frames) > 0) and (self._last_packet_ts is not None):
                if now - self._last_packet_ts > 2.0:
                    self.frames_countdown = 0
                    if self._frames_zero_at is None:
                        self._frames_zero_at = now

            if need_more_video or need_more_audio:
                # sluchanie kiedy sa klatki do odbioru
                try:
                    data, _ = self.socket.recvfrom(RECV_SIZE)
                except socket.timeout:
                    continue
                except Exception:
                    time.sleep(0.05)
                    continue
                if not data:
                    time.sleep(0.05)
                    continue
                self._last_packet_ts = now
                # Handle audio control markers
                if self.use_udp_audio and data == b"AUDIO_START":
                    # Ignore duplicate start markers once in audio mode
                    if 'receiving_audio' in locals() and receiving_audio:
                        print("AUDIO_START duplicate; already receiving audio")
                        continue
                    # If audio starts while a video frame is mid-assembly (rare UDP reordering),
                    # finish the partial frame so we don't stall waiting for its END.
                    if bytes_received:
                        # Finalize any partial frame before switching to audio mode
                        self.frames.append(bytes_received)
                        bytes_received = b""
                        if self.frames_countdown > 0:
                            self.frames_countdown -= 1
                            print(f"Frames left: {self.frames_countdown} (forced finalize on AUDIO_START)")
                            if self.frames_countdown == 0 and self._frames_zero_at is None:
                                self._frames_zero_at = time.time()
                    receiving_audio = True
                    self._audio_chunks = 0
                    self._audio_bytes_accum = 0
                    # If any audio data arrived before the marker, include it
                    if self._pre_audio_chunks:
                        audio_buf = b"".join(self._pre_audio_chunks)
                        self._pre_audio_chunks = []
                        self._pre_audio_bytes = 0
                    else:
                        audio_buf = b""
                    print("AUDIO_START received; preloaded {} bytes".format(len(audio_buf)))
                    continue
                if self.use_udp_audio and data == b"AUDIO_END":
                    receiving_audio = False
                    self.audio_bytes = audio_buf
                    self.audio_done = True
                    print(f"Audio received: {len(self.audio_bytes)} bytes in {self._audio_chunks} chunks")
                    self._audio_chunks = 0
                    self._audio_bytes_accum = 0
                    continue
                if self.use_udp_audio and data == b"AUDIO_NONE":
                    self.audio_bytes = None
                    self.audio_done = True
                    print("No audio will be received")
                    continue

                if self.use_udp_audio and receiving_audio:
                    audio_buf += data
                    self._audio_chunks += 1
                    self._audio_bytes_accum += len(data)
                    if (self._audio_chunks % 50) == 0:
                        print("Audio receiving... {} bytes so far".format(self._audio_bytes_accum))
                    continue
                # If frames are finished and we haven't started receiving_audio yet,
                # stash unknown packets (not control markers) as potential early audio.
                if self.use_udp_audio and self.frames_countdown == 0 and data not in (b"END", b"AUDIO_END", b"AUDIO_NONE"):
                    # Buffer as pre-audio chunk
                    self._pre_audio_chunks.append(data)
                    self._pre_audio_bytes += len(data)
                    if (len(self._pre_audio_chunks) % 20) == 0:
                        print("Pre-audio buffering... {} bytes".format(self._pre_audio_bytes))
                    # If we accumulated enough without seeing AUDIO_START, assume marker lost and switch
                    if self._pre_audio_bytes >= 4096 and not receiving_audio:
                        audio_buf = b"".join(self._pre_audio_chunks)
                        self._pre_audio_chunks = []
                        self._pre_audio_bytes = 0
                        receiving_audio = True
                        self._audio_chunks = 0
                        self._audio_bytes_accum = len(audio_buf)
                        print("Assuming AUDIO_START lost; switching to audio mode with {} preloaded bytes".format(len(audio_buf)))
                    continue
                if data == b"END":
                    # odebrano wszystkie dane z klatki
                    if bytes_received:
                        self.frames.append(bytes_received)
                    else:
                        # Ignore stray END without data (could be due to packet loss or overlap with AUDIO markers)
                        print("Warning: received END without frame data; skipping")
                    bytes_received = b""
                    if self.frames_countdown > 0:
                        self.frames_countdown -= 1
                        print(f"Frames left: {self.frames_countdown}")
                        if self.frames_countdown == 0:
                            self._frames_zero_at = time.time()
                    elif self.frames_countdown == 0:
                        # We were already told there are 0 frames left, but we just finished the trailing frame.
                        # Arm the audio timeout window now if not already set.
                        if self._frames_zero_at is None:
                            self._frames_zero_at = time.time()
                    elif self.frames_countdown < 0:
                        # Unknown total; rely on inactivity to detect completion
                        pass
                else:
                    # odebrano czesc klatki
                    bytes_received += data
                    print(f"udp thread received {len(data)} bytes")
            else:
                # nie ma juz klatek do odbioru
                # trzeba przygotować filmik z tego co jest (audio_done == True here)
                print("Finalizing: frames={}, audio={} bytes".format(len(self.frames), 0 if self.audio_bytes is None else len(self.audio_bytes)))
                self.listening = False
                make_video_from_frames(self.frames, self.patient_id, self.audio_bytes, self.mux_audio)
                self.frames_countdown = -1
                self.frames = []
                self.audio_bytes = None
                self.audio_done = False
                self._frames_zero_at = None




    def exit(self):
        self.listening = False
        self.running = False
        self.socket.close()