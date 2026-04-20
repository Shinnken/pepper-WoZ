import asyncio
from collections import deque
from typing import Deque, Optional, Tuple

import qi

from frame_compresser import compress_frame_data_async
from SoundReciver_py2 import SoundReceiverModule


class PepperCamera(object):
    def __init__(self, disable_life_mode: bool = False, disable_awareness: bool = False, loop: Optional[asyncio.AbstractEventLoop] = None):
        self.frames: Deque[Tuple[int, bytes]] = deque()
        self.audio_queue: asyncio.Queue[Optional[bytes]] = asyncio.Queue(maxsize=128)
        self.sound_module_instance: Optional[SoundReceiverModule] = None
        self.session: Optional[qi.Session] = None
        self.vid_handle: Optional[str] = None
        self.disable_life_mode = disable_life_mode
        self.disable_awareness = disable_awareness
        self._recording_task: Optional[asyncio.Task] = None
        self._is_recording = False
        self.loop = loop or asyncio.get_event_loop()

    async def init_qi_session(self) -> None:
        await asyncio.to_thread(self._init_qi_session_blocking)

    def _init_qi_session_blocking(self) -> None:
        camera_index = 0
        resolution_index = 2
        colorspace_index = 11
        framerate = 15

        self.session = qi.Session()
        self.session.connect("tcp://127.0.0.1:9559")
        self.session.service("ALTextToSpeech").setLanguage("English")
        if self.disable_life_mode:
            self.session.service("ALAutonomousLife").setState("disabled")
            self.session.service("ALMotion").wakeUp()
            self.session.service("ALRobotPosture").goToPosture("StandInit", 1.0)
        else:
            self.session.service("ALAutonomousLife").setState("solitary")

        self._delete_subs("kamera")
        self.vid_handle = self.session.service("ALVideoDevice").subscribeCamera(
            "kamera",
            camera_index,
            resolution_index,
            colorspace_index,
            framerate,
        )
        try:
            self.sound_module_instance = SoundReceiverModule(self.session, audio_queue=self.audio_queue, loop=self.loop, name="SoundProcessingModule")
            self.session.registerService("SoundProcessingModule", self.sound_module_instance)
            print("Sound module registered successfully.")
        except Exception as exc:
            print("Failed to initialize sound module:", exc)

    def _delete_subs(self, name: str) -> None:
        assert self.session is not None
        subscribers = self.session.service("ALVideoDevice").getSubscribers()
        for subscriber in subscribers:
            if name in subscriber:
                try:
                    self.session.service("ALVideoDevice").unsubscribe(subscriber)
                except Exception:
                    pass

    async def start_recording(self) -> None:
        assert self.session is not None and self.vid_handle is not None
        if self.disable_life_mode:
            await asyncio.to_thread(self.session.service("ALMotion").angleInterpolationWithSpeed, ("HeadYaw", "HeadPitch"), (0, 0.0), 1.0)
            await asyncio.sleep(1.0)
        elif self.disable_awareness:
            await asyncio.to_thread(self.session.service("ALAutonomousLife").setAutonomousAbilityEnabled, "BasicAwareness", False)

        if not self._recording_task:
            self._is_recording = True
            self._recording_task = asyncio.create_task(self._record_frames())

        if self.sound_module_instance:
            self.sound_module_instance.start()

    async def stop_recording(self) -> None:
        if self.disable_awareness and self.session is not None:
            await asyncio.to_thread(self.session.service("ALAutonomousLife").setAutonomousAbilityEnabled, "BasicAwareness", True)

        self._is_recording = False
        if self._recording_task:
            await self._recording_task
            self._recording_task = None
        if self.sound_module_instance:
            self.sound_module_instance.stop()

    async def exit(self) -> None:
        if self._recording_task:
            await self.stop_recording()
        if self.session and self.vid_handle:
            try:
                await asyncio.to_thread(self.session.service("ALVideoDevice").unsubscribe, self.vid_handle)
            except Exception:
                pass
        if self.sound_module_instance:
            try:
                self.sound_module_instance.stop()
            except Exception:
                pass

    async def wez_powiedz(self, message: str) -> None:
        if not self.session:
            return
        await asyncio.to_thread(self.session.service("ALAnimatedSpeech").say, message)
        print("said:", message)

    async def ustaw_jezyk(self, language_name: str) -> None:
        if not self.session:
            return

        normalized = (language_name or "").strip().lower()
        language_map = {
            "en": "English",
            "english": "English",
            "zh": "Chinese",
            "chinese": "Chinese",
            "polish": "Polish",
            "pl": "Polish",
        }
        resolved_language = language_map.get(normalized, language_name)
        await asyncio.to_thread(self.session.service("ALTextToSpeech").setLanguage, resolved_language)
        try:
            await asyncio.to_thread(self.session.service("ALAnimatedSpeech").setLanguage, resolved_language)
        except Exception:
            pass
        print("language set:", resolved_language)

    async def wez_usiadz(self) -> None:
        if self.session:
            await asyncio.to_thread(self.session.service("ALRobotPosture").goToPosture, "Sit", 1.0)

    async def wez_spij(self) -> None:
        if self.session:
            await asyncio.to_thread(self.session.service("ALAutonomousLife").setState, "disabled")
            await asyncio.to_thread(self.session.service("ALLeds").off, "AllLeds")

    async def wez_wstawaj(self) -> None:
        if self.session:
            await asyncio.to_thread(self.session.service("ALAutonomousLife").setState, "solitary")

    async def _record_frames(self) -> None:
        assert self.session is not None and self.vid_handle is not None
        video_service = self.session.service("ALVideoDevice")
        while self._is_recording:
            try:
                frame_data_raw = await asyncio.to_thread(video_service.getImageRemote, self.vid_handle)
                frame_data = await compress_frame_data_async(frame_data_raw)
                self.frames.append(frame_data)
            except Exception as exc:
                print("Frame capture error:", exc)
                await asyncio.sleep(0.05)
