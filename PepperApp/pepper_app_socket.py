import socket
import threading
from video_maker_old import make_video_from_frames
import time
import os
import struct

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
        self.socket.settimeout(10)  # Set a timeout for the accept call

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
        self._frame_header = struct.Struct('!QI')
        self._last_frame_ts = None
        self._reset_requested = False
        try:
            self._timestamp_reset_threshold = int(os.getenv('PEPPER_TS_RESET_DELTA_US', '1000000000'))
        except Exception:
            self._timestamp_reset_threshold = 1000000000

    def set_patient_id(self, patient_id: int):
        self.patient_id = patient_id

    def prepare_capture(self, patient_id: int | None = None):
        if patient_id is not None:
            self.patient_id = patient_id
        self.frames = []
        self.frames_countdown = -1
        self.audio_bytes = None
        self.audio_done = False
        self._frames_zero_at = None
        self._last_packet_ts = None
        self._pre_audio_chunks = []
        self._pre_audio_bytes = 0
        self._audio_chunks = 0
        self._audio_bytes_accum = 0
        self._last_frame_ts = None
        self._reset_requested = True
        self.listening = True

    def run(self):
        RECV_SIZE = 1400
        self.running = True
        bytes_received = bytearray()
        receiving_audio = False
        audio_buf = bytearray() 

        while self.running:
            if self._reset_requested:
                bytes_received.clear()
                audio_buf.clear()
                receiving_audio = False
                self._reset_requested = False
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
                    time.sleep(0.02)
                    continue
                if not data:
                    time.sleep(0.02)
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
                        frame_blob = bytes(bytes_received)
                        bytes_received.clear()
                        self._handle_frame_blob(frame_blob, suffix=" (forced finalize on AUDIO_START)")
                    receiving_audio = True
                    self._audio_chunks = 0
                    self._audio_bytes_accum = 0
                    # If any audio data arrived before the marker, include it
                    if self._pre_audio_chunks:
                        audio_buf = bytearray(b"".join(self._pre_audio_chunks))
                        self._pre_audio_chunks = []
                        self._pre_audio_bytes = 0
                    else:
                        audio_buf.clear() # Reset
                        print("AUDIO_START received; preloaded {} bytes".format(len(audio_buf)))
                    continue
                if self.use_udp_audio and data == b"AUDIO_END":
                    receiving_audio = False
                    self.audio_bytes = bytes(audio_buf)
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
                        frame_blob = bytes(bytes_received)
                        bytes_received.clear()
                        self._handle_frame_blob(frame_blob, suffix="")
                    else:
                        # Ignore stray END without data (could be due to packet loss or overlap with AUDIO markers)
                        print("Warning: received END without frame data; skipping")
                    if self.frames_countdown < 0:
                        # Unknown total; rely on inactivity to detect completion
                        pass
                else:
                    # odebrano czesc klatki
                    bytes_received += data
                    # print(f"udp thread received {len(data)} bytes")
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
                self._last_packet_ts = None
                self._pre_audio_chunks = []
                self._pre_audio_bytes = 0
                self._audio_chunks = 0
                self._audio_bytes_accum = 0
                self._last_frame_ts = None




    def exit(self):
        self.listening = False
        self.running = False
        self.socket.close()

    def _decode_frame_blob(self, blob):
        try:
            if len(blob) >= self._frame_header.size:
                ts_us, payload_len = self._frame_header.unpack_from(blob)
                frame_bytes = blob[self._frame_header.size:]
                if payload_len != len(frame_bytes):
                    print("Discarding frame: payload size mismatch (expected {} got {})".format(payload_len, len(frame_bytes)))
                    return None
                if payload_len <= 0 or payload_len > (3 * 1024 * 1024):
                    print("Discarding frame: unreasonable payload length {}".format(payload_len))
                    return None
                if ts_us < 0 or ts_us > 10**15:
                    print("Discarding frame: timestamp {} outside expected range".format(ts_us))
                    return None
                if self._last_frame_ts is None:
                    self._last_frame_ts = ts_us
                    return (ts_us, frame_bytes)
                if ts_us > self._last_frame_ts:
                    self._last_frame_ts = ts_us
                    return (ts_us, frame_bytes)
                delta_back = self._last_frame_ts - ts_us
                if delta_back > self._timestamp_reset_threshold:
                    print("Timestamp jump backwards by {} us; resetting baseline.".format(delta_back))
                    self._last_frame_ts = ts_us
                    return (ts_us, frame_bytes)
                print("Dropping out-of-order frame with timestamp {} (last {})".format(ts_us, self._last_frame_ts))
                return None
            else:
                print("Frame blob too small for header ({} bytes); treating as legacy frame".format(len(blob)))
        except struct.error as exc:
            print("Failed to unpack frame header: {}".format(exc))
        # Legacy support: no timestamp header
        return (None, blob)

    def _handle_frame_blob(self, blob, suffix=""):
        frame_entry = self._decode_frame_blob(blob)
        if frame_entry is not None:
            self.frames.append(frame_entry)
            if self.frames_countdown > 0:
                self.frames_countdown -= 1
                print(f"Frames left: {self.frames_countdown}{suffix}")
                if self.frames_countdown == 0 and self._frames_zero_at is None:
                    self._frames_zero_at = time.time()
            elif self.frames_countdown == 0 and self._frames_zero_at is None:
                self._frames_zero_at = time.time()
        return frame_entry is not None

