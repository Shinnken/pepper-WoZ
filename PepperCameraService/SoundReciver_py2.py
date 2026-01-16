import asyncio
from typing import Optional

import numpy as np


class SoundReceiverModule(object):
    """Stream audio chunks into an asyncio.Queue to avoid buffering everything in RAM."""

    def __init__(self, session, audio_queue: asyncio.Queue[Optional[bytes]], loop: Optional[asyncio.AbstractEventLoop] = None, name: str = "SoundReceiverModule"):
        super(SoundReceiverModule, self).__init__()
        self.audio_service = session.service("ALAudioDevice")
        self.module_name = name
        self.sample_rate = 48000
        self.default_channels = 4
        self.is_recording = False
        self.last_nb_channels = self.default_channels
        self.queue = audio_queue
        self.loop = loop or asyncio.get_event_loop()

    def start(self) -> None:
        try:
            self.audio_service.closeAudioInputs()
        except Exception:
            pass
        try:
            self.audio_service.setClientPreferences(self.module_name, self.sample_rate, self.default_channels, 0)
            self.audio_service.subscribe(self.module_name)
            self.is_recording = True
        except Exception as exc:
            print("[SoundReceiver] start error: {}".format(exc))
            self.is_recording = False

    def stop(self) -> None:
        if not self.is_recording:
            return
        self.is_recording = False
        try:
            self.audio_service.unsubscribe(self.module_name)
        except Exception:
            pass
        # Signal audio consumer that recording is done
        try:
            self.loop.call_soon_threadsafe(self.queue.put_nowait, None)
        except Exception:
            pass

    def _downmix(self, audio_bytes: bytes, nb_channels: int) -> bytes:
        samples_np = np.frombuffer(audio_bytes, dtype=np.int16)
        if nb_channels > 1:
            try:
                samples_np = samples_np.reshape(-1, nb_channels)
                mono_np = samples_np.mean(axis=1).astype(np.int16)
            except ValueError:
                cutoff = (len(samples_np) // nb_channels) * nb_channels
                samples_np = samples_np[:cutoff].reshape(-1, nb_channels)
                mono_np = samples_np.mean(axis=1).astype(np.int16)
            return mono_np.tobytes()
        return samples_np.tobytes()

    def processRemote(self, nbOfChannels, nbrOfSamplesByChannel, timestamp, buffer):
        self.last_nb_channels = nbOfChannels or self.default_channels
        if not self.is_recording:
            return
        try:
            raw_bytes = bytes(buffer)
            mono_bytes = self._downmix(raw_bytes, self.last_nb_channels)
            self.loop.call_soon_threadsafe(self.queue.put_nowait, mono_bytes)
        except asyncio.QueueFull:
            # Drop if the consumer falls behind; prevents unbounded growth
            return
        except Exception as exc:
            print("[SoundReceiver] failed to enqueue audio: {}".format(exc))
