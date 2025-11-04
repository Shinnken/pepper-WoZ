import sys
import wave
from array import array
from io import BytesIO
import numpy as np


PY2 = sys.version_info[0] == 2
try:
    _bytes_type = bytes
except NameError:  # pragma: no cover
    _bytes_type = str


def _as_bytes(chunk):
    if isinstance(chunk, _bytes_type):
        return chunk
    if isinstance(chunk, bytearray):
        if PY2:
            return array('B', chunk).tostring()
        return bytes(chunk)
    if hasattr(chunk, 'tobytes'):
        return chunk.tobytes()
    if hasattr(chunk, 'tostring'):
        return chunk.tostring()
    tmp = array('h')
    try:
        tmp.extend(chunk)
    except TypeError:
        tmp.fromlist(list(chunk))
    try:
        return tmp.tobytes()
    except AttributeError:
        return tmp.tostring()


def _join_chunks(chunks):
    normalized = [_as_bytes(chunk) for chunk in chunks]
    if PY2:
        return ''.join(normalized)
    return b''.join(normalized)


class SoundReceiverModule(object):
    """Minimal audio capture for Pepper; mixes 4 channels at 48 kHz down to mono WAV."""

    def __init__(self, session, name="SoundReceiverModule"):
        super(SoundReceiverModule, self).__init__()
        self.audio_service = session.service("ALAudioDevice")
        self.module_name = name
        self.sample_rate = 48000
        self.default_channels = 4
        self.chunks = []
        self.is_recording = False
        self.last_nb_channels = self.default_channels

    def start(self):
        try:
            self.audio_service.closeAudioInputs()
        except Exception:
            pass
        try:
            self.audio_service.setClientPreferences(self.module_name, self.sample_rate, self.default_channels, 0)
            self.audio_service.subscribe(self.module_name)
            self.chunks = []
            self.is_recording = True
        except Exception as exc:
            print("[SoundReceiver] start error: {}".format(exc))
            self.is_recording = False

    def stop(self):
        if not self.is_recording:
            return None
        self.is_recording = False
        try:
            self.audio_service.unsubscribe(self.module_name)
        except Exception:
            pass
        if not self.chunks:
            return None
        raw_bytes = _join_chunks(self.chunks)
        self.chunks = []
        nb_channels = int(self.last_nb_channels or 1)
        return self._to_wav(raw_bytes, nb_channels)

    def _to_wav(self, audio_bytes, nb_channels):
        samples_np = np.frombuffer(audio_bytes, dtype=np.int16)

        if nb_channels > 1:
            try:
                samples_np = samples_np.reshape(-1, nb_channels)
                mono_np = samples_np.mean(axis=1).astype(np.int16)
            
            except ValueError as e:
                # Handle potential partial buffer
                print("Audio buffer warning (reshape failed): {}. Truncating.".format(e))
                cutoff = (len(samples_np) // nb_channels) * nb_channels
                samples_np = samples_np[:cutoff].reshape(-1, nb_channels)
                mono_np = samples_np.mean(axis=1).astype(np.int16)
        else:
            mono_np = samples_np
        
        if hasattr(mono_np, "tobytes"):
            mono_bytes = mono_np.tobytes()
        else:
            mono_bytes = mono_np.tostring() # Python 2 fallback

        buf = BytesIO()
        wav = wave.open(buf, 'wb')
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(self.sample_rate)
        wav.writeframes(mono_bytes)
        wav.close()
        data = buf.getvalue()
        buf.close()
        return data


    def processRemote(self, nbOfChannels, nbrOfSamplesByChannel, timestamp, buffer):
        self.last_nb_channels = nbOfChannels or self.default_channels
        if not self.is_recording:
            return
        try:
            self.chunks.append(_as_bytes(buffer))
        except Exception:
            pass
