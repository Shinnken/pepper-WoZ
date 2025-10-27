try:
    import numpy as np  # Optional; we'll fallback if unavailable
except Exception:
    np = None
import wave
from array import array
from io import BytesIO
import time


class SoundReceiverModule(object):
    """
    Python 2.7-compatible audio capture module for ALAudioDevice.
    Accumulates raw buffers during start(); returns a compressed WAV (16 kHz, mono) on stop().
    """
    def __init__(self, session, name="SoundReceiverModule"):
        super(SoundReceiverModule, self).__init__()
        self.session = session
        self.audio_service = session.service("ALAudioDevice")
        self.module_name = name
        # Request all microphones; Pepper has 4 mics. We'll fold to mono on stop().
        # ALAudioDevice will deliver interleaved buffers when deinterleaved=0.
        self.channels = 4
        self.accumulated_frames = []
        self.is_recording = False
        self.last_nb_channels = self.channels
        self._first_callback_logged = False
        self._start_time = None
        self._duration_s = None

    def start(self):
        try:
            self.audio_service.closeAudioInputs()
        except Exception as e:
            print("[SoundReceiver] closeAudioInputs error: {}".format(e))
        try:
            # 16000 Hz; 4 channels; interleaved=0. ALAudioDevice will call processRemote.
            self.audio_service.setClientPreferences(self.module_name, 16000, self.channels, 0)
            self.audio_service.subscribe(self.module_name)
            self.is_recording = True
            self.accumulated_frames = []
            self._start_time = time.time()
            print("[SoundReceiver] Started recording. (module={}, rate=16000, channels={})".format(self.module_name, self.channels))
        except Exception as e:
            print("[SoundReceiver] subscribe error: {}".format(e))

    def stop(self):
        try:
            self.is_recording = False
            self.audio_service.unsubscribe(self.module_name)
        except Exception as e:
            print("[SoundReceiver] unsubscribe error: {}".format(e))
        print("[SoundReceiver] Stopping. Accumulated buffers: {}".format(len(self.accumulated_frames)))
        if self.accumulated_frames:
            # Join raw buffers
            try:
                full_recording = b''.join(self.accumulated_frames)
            except Exception:
                # Python 2 safe join
                full_recording = ''.join(self.accumulated_frames)
            # Compute actual recording duration
            try:
                if self._start_time is not None:
                    self._duration_s = max(0.001, time.time() - self._start_time)
                else:
                    self._duration_s = None
            except Exception:
                self._duration_s = None
            compressed_audio = self._compress_recording(full_recording, self._duration_s)
            print("[SoundReceiver] Recording stopped and compressed. Original size: {} bytes, Compressed size: {} bytes".format(
                len(full_recording), len(compressed_audio)))
            self.accumulated_frames = []
            return compressed_audio
        else:
            print("[SoundReceiver] No audio data recorded.")
            return None

    def _compress_recording(self, audio_data, duration_s=None):
        """
        Assume little-endian 16-bit PCM at 16kHz. Mix to mono if multi-channel, write in-memory WAV and return bytes.
        """
        try:
            nb_ch = int(self.last_nb_channels) if self.last_nb_channels else 1
            # Decode little-endian 16-bit PCM
            if np is not None:
                data = np.frombuffer(audio_data, dtype='<i2')
                if nb_ch > 1:
                    try:
                        # Trim to full multi-channel frames before reshape
                        trim_len = (data.size // nb_ch) * nb_ch
                        if trim_len != data.size:
                            data = data[:trim_len]
                        frames = data.reshape((-1, nb_ch))
                        mono = frames.mean(axis=1).astype(np.int16)
                    except Exception:
                        mono = data.astype(np.int16)
                else:
                    mono = data.astype(np.int16)
                audio_bytes = mono.tostring() if hasattr(mono, 'tostring') else bytes(mono)
            else:
                # Fallback without numpy
                arr16 = array('h')
                try:
                    arr16.fromstring(audio_data)
                except Exception:
                    arr16.frombytes(audio_data)
                if nb_ch > 1:
                    mono = array('h')
                    total_frames = len(arr16) // nb_ch
                    i = 0
                    while i < total_frames:
                        s = 0
                        base = i * nb_ch
                        c = 0
                        while c < nb_ch:
                            s += arr16[base + c]
                            c += 1
                        mono.append(int(s / nb_ch))
                        i += 1
                    try:
                        audio_bytes = mono.tostring()
                    except Exception:
                        audio_bytes = mono.tobytes()
                else:
                    try:
                        audio_bytes = arr16.tostring()
                    except Exception:
                        audio_bytes = arr16.tobytes()

            # Optional denoise: simple high-pass + soft noise gate + spectral gating (if NumPy available)
            try:
                raise NotImplementedError("Denoise disabled for now")
                if np is not None:
                    # Convert to int32 for headroom
                    x = np.frombuffer(audio_bytes, dtype='<i2').astype(np.int32)
                    # One-pole high-pass: y[n] = x[n] - x[n-1] + r*y[n-1]
                    r = 0.98  # ~100-150 Hz cutoff at 16kHz
                    y = np.empty_like(x)
                    prev_x = int(x[0]) if x.size else 0
                    prev_y = 0
                    for i in range(x.size):
                        xi = int(x[i])
                        yi = xi - prev_x + int(r * prev_y)
                        y[i] = yi
                        prev_x = xi
                        prev_y = yi
                    # Soft noise gate
                    abs_y = np.abs(y)
                    med = int(np.median(abs_y)) if y.size else 0
                    thr = max(100, 2 * med)
                    if thr > 0:
                        atten = 0.3
                        mask = abs_y < thr
                        # Apply attenuation where below threshold
                        y = y.astype(np.float32)
                        y[mask] *= atten
                    # Spectral gating (STFT-based) for steady noise reduction
                    try:
                        fs = 16000  # provisional; true rate set later, not critical for STFT sizing
                        # Use estimated rate if available from duration
                        try:
                            n_samp_tmp = len(y)
                            if duration_s and duration_s > 0.001:
                                fs_est = int(round(float(n_samp_tmp) / float(duration_s)))
                                if fs_est >= 8000 and fs_est <= 48000:
                                    fs = fs_est
                        except Exception:
                            pass
                        # Prepare float signal in [-1, 1]
                        yf = np.clip(y, -32768, 32767).astype(np.float32) / 32768.0
                        win = 1024
                        hop = 256
                        if yf.size > win:
                            w = np.hanning(win).astype(np.float32)
                            n_frames = 1 + (yf.size - win) // hop
                            # Estimate noise from first 0.4s or at least 10 frames
                            n_noise = max(10, int(min(n_frames, (0.4 * fs) / hop)))
                            # Accumulate noise spectrum
                            noise_mag = None
                            for k in range(n_noise):
                                start = k * hop
                                seg = yf[start:start + win] * w
                                spec = np.fft.rfft(seg)
                                mag = np.abs(spec)
                                if noise_mag is None:
                                    noise_mag = mag
                                else:
                                    # Median-like update via running min of max to avoid speech bursts raising noise too much
                                    noise_mag = np.minimum(noise_mag * 1.02, mag * 1.0)
                            if noise_mag is None:
                                noise_mag = np.ones(win // 2 + 1, dtype=np.float32) * 1e-3
                            out = np.zeros(yf.size + win, dtype=np.float32)
                            win_norm = np.zeros(yf.size + win, dtype=np.float32)
                            floor = 0.15  # minimum gain
                            for k in range(n_frames):
                                start = k * hop
                                seg = yf[start:start + win] * w
                                spec = np.fft.rfft(seg)
                                mag = np.abs(spec)
                                # Subtractive mask
                                gain = (mag - noise_mag)
                                gain = gain / (mag + 1e-8)
                                gain = np.maximum(gain, floor).astype(np.float32)
                                spec_d = spec * gain
                                seg_d = np.fft.irfft(spec_d).astype(np.float32)
                                out[start:start + win] += seg_d * w
                                win_norm[start:start + win] += (w * w)
                            # Normalize overlap-add
                            nz = win_norm > 1e-6
                            out[nz] = out[nz] / win_norm[nz]
                            out = np.clip(out[:yf.size], -1.0, 1.0)
                            y = (out * 32767.0).astype(np.int16)
                        else:
                            # Too short for STFT; just clip and cast
                            y = np.clip(y, -32768, 32767).astype(np.int16)
                    except Exception:
                        # Fallback to simple path
                        y = np.clip(y, -32768, 32767).astype(np.int16)
                    audio_bytes = y.tostring() if hasattr(y, 'tostring') else bytes(y)
                else:
                    # Fallback without numpy
                    from array import array
                    arr = array('h')
                    try:
                        arr.fromstring(audio_bytes)
                    except Exception:
                        arr.frombytes(audio_bytes)
                    # High-pass
                    r = 0.98
                    prev_x = arr[0] if len(arr) else 0
                    prev_y = 0
                    y = array('h')
                    # For noise threshold compute running avg abs
                    sum_abs = 0
                    count = 0
                    tmp_vals = []
                    for xi in arr:
                        yi = int(xi) - int(prev_x) + int(r * prev_y)
                        if yi < -32768:
                            yi = -32768
                        elif yi > 32767:
                            yi = 32767
                        tmp_vals.append(yi)
                        a = yi if yi >= 0 else -yi
                        sum_abs += a
                        count += 1
                        prev_x = xi
                        prev_y = yi
                    thr = 100
                    if count > 0:
                        avg_abs = sum_abs // count
                        thr = max(thr, 2 * avg_abs)
                    # Soft gate
                    y2 = array('h')
                    for yi in tmp_vals:
                        a = yi if yi >= 0 else -yi
                        if a < thr:
                            yi = int(0.3 * yi)
                        if yi < -32768:
                            yi = -32768
                        elif yi > 32767:
                            yi = 32767
                        y2.append(yi)
                    try:
                        audio_bytes = y2.tostring()
                    except Exception:
                        audio_bytes = y2.tobytes()
            except Exception as _:
                # Denoise is best-effort; continue with raw audio_bytes on failure
                pass

            # Lock the output sample rate to 16 kHz for consistency
            try:
                n_samples = len(audio_bytes) // 2
            except Exception:
                n_samples = 0
            est_rate = 16000

            # In-memory WAV buffer
            buf = BytesIO()

            wf = wave.open(buf, 'wb')
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(est_rate)
            wf.writeframes(audio_bytes)
            wf.close()
            try:
                print("[SoundReceiver] WAV sample rate set to {} Hz ({} samples, {:.2f}s, channels mix: {})".format(
                    est_rate, n_samples, (float(n_samples) / float(est_rate)) if est_rate else 0.0, nb_ch))
            except Exception:
                pass

            try:
                buf.seek(0)
                wav_bytes = buf.getvalue()
            finally:
                try:
                    buf.close()
                except Exception:
                    pass
            return wav_bytes
        except Exception as e:
            print("[SoundReceiver] Error during audio compression: {}".format(e))
            try:
                return audio_data
            except Exception:
                return None

    def processRemote(self, nbOfChannels, nbrOfSamplesByChannel, timestamp, buffer):
        """Called by ALAudioDevice with raw audio buffer."""
        self.last_nb_channels = nbOfChannels
        if not self._first_callback_logged:
            print("[SoundReceiver] processRemote() first callback. nbOfChannels={}, nbrOfSamplesByChannel={}".format(nbOfChannels, nbrOfSamplesByChannel))
            self._first_callback_logged = True
        if not self.is_recording:
            return
        try:
            # Normalize buffer to a bytes string
            buf_bytes = None
            if isinstance(buffer, bytes):
                buf_bytes = buffer
            elif isinstance(buffer, str):  # Python 2 raw string
                buf_bytes = buffer
            else:
                try:
                    # numpy array or array('h')
                    buf_bytes = buffer.tostring()
                except Exception:
                    try:
                        from array import array
                        buf_bytes = array('h', buffer).tostring()
                    except Exception:
                        # Last resort: convert using numpy
                        if np is not None:
                            np_buf = np.array(buffer, dtype=np.int16)
                            buf_bytes = np_buf.tostring()
                        else:
                            return

            self.accumulated_frames.append(buf_bytes)
            if len(self.accumulated_frames) % 100 == 0:
                print("[SoundReceiver] Buffers accumulated: {}".format(len(self.accumulated_frames)))
        except Exception as e:
            print("[SoundReceiver] Error appending buffer: {}".format(e))
