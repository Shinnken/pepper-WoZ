import asyncio
import contextlib
import os
import struct
from typing import Optional


class PepperSocketManager(object):
    def __init__(self, host: str, port_tcp: int, port_udp: int, pepper_camera, loop: Optional[asyncio.AbstractEventLoop] = None):
        self.host = host
        self.port_tcp = port_tcp
        self.port_udp = port_udp
        self.pepper_camera = pepper_camera
        self.loop = loop or asyncio.get_event_loop()

        self.tcp_reader: Optional[asyncio.StreamReader] = None
        self.tcp_writer: Optional[asyncio.StreamWriter] = None
        self.udp_transport: Optional[asyncio.DatagramTransport] = None
        self.running = False

        self.command_task: Optional[asyncio.Task] = None
        self.frame_task: Optional[asyncio.Task] = None
        self.audio_task: Optional[asyncio.Task] = None
        self._audio_started = False

    async def start(self) -> None:
        print("Connecting to:", (self.host, self.port_tcp), (self.host, self.port_udp))
        self.tcp_reader, self.tcp_writer = await asyncio.open_connection(self.host, self.port_tcp)
        transport, _ = await self.loop.create_datagram_endpoint(lambda: asyncio.DatagramProtocol(), remote_addr=(self.host, self.port_udp))
        self.udp_transport = transport
        try:
            udp_sock = self.udp_transport.get_extra_info("socket")
            if udp_sock:
                udp_sock.setsockopt(os.SOL_SOCKET, os.SO_SNDBUF, 4 * 1024 * 1024)
        except Exception as exc:
            print("Failed to set UDP send buffer:", exc)

        await self.pepper_camera.init_qi_session()
        print("Connected successfully")

        self.running = True
        self.command_task = asyncio.create_task(self._handle_commands())
        self.frame_task = asyncio.create_task(self._stream_frames())
        self.audio_task = asyncio.create_task(self._stream_audio())

    async def _handle_commands(self) -> None:
        assert self.tcp_reader is not None
        while self.running:
            data = await self.tcp_reader.read(1024)
            if not data:
                break
            raw_command = data.decode("utf-8").strip()
            if not raw_command:
                continue

            command, argument = self._split_command(raw_command)
            if command == "speak" and argument:
                await self.pepper_camera.wez_powiedz(argument)
                continue
            if command == "lang" and argument:
                await self.pepper_camera.ustaw_jezyk(argument)
                continue

            print("received command:", command, " len:", len(self.pepper_camera.frames))
            if command == "start":
                await self.pepper_camera.start_recording()
            elif command == "stop":
                await self._handle_stop()
            elif command == "exit":
                await self.close()
            elif command == "sleep":
                await self.pepper_camera.wez_spij()
            elif command == "wake":
                await self.pepper_camera.wez_wstawaj()

    def _split_command(self, raw_command: str) -> tuple[str, str]:
        parts = raw_command.split(" ", 1)
        if len(parts) == 1:
            return parts[0], ""
        return parts[0], parts[1].strip()

    async def _handle_stop(self) -> None:
        await self.pepper_camera.stop_recording()
        await self._send_tcp_line(str(len(self.pepper_camera.frames)))

    async def _stream_frames(self) -> None:
        while self.running:
            if self.pepper_camera.frames:
                frame = self.pepper_camera.frames.popleft()
                await self._send_frame(frame)
            else:
                await asyncio.sleep(0.01)

    async def _stream_audio(self) -> None:
        queue = self.pepper_camera.audio_queue
        while self.running:
            chunk = await queue.get()
            if chunk is None:
                if self._audio_started:
                    self._send_udp(b"AUDIO_END")
                self._audio_started = False
                continue

            if not self._audio_started:
                self._audio_started = True
                self._send_udp(b"AUDIO_START")

            pace_sleep = float(os.getenv("PEPPER_AUDIO_PACE_US", "500")) / 1_000_000.0
            # Keep total UDP packet size at ~1200 bytes including prefix
            chunk_size = 1199
            for start in range(0, len(chunk), chunk_size):
                # Prefix audio packets so receiver can demux from video
                self._send_udp(b"A" + chunk[start:start + chunk_size])
                if pace_sleep:
                    await asyncio.sleep(pace_sleep)

    async def _send_frame(self, frame) -> None:
        timestamp_us, payload = frame
        header = struct.pack("!QI", int(timestamp_us), len(payload))
        packet = header + payload
        # Keep total UDP packet size at ~1200 bytes including prefix
        chunk_size = 1199
        for start in range(0, len(packet), chunk_size):
            # Prefix video packets so receiver can demux from audio
            self._send_udp(b"V" + packet[start:start + chunk_size])
        self._send_udp(b"END")

    async def _send_tcp_line(self, text: str) -> None:
        if not self.tcp_writer:
            return
        self.tcp_writer.write((text + "\n").encode("utf-8"))
        await self.tcp_writer.drain()

    def _send_udp(self, data: bytes) -> None:
        if self.udp_transport:
            self.udp_transport.sendto(data)

    async def close(self) -> None:
        self.running = False
        await self.pepper_camera.exit()
        for task in (self.command_task, self.frame_task, self.audio_task):
            if task:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        if self.tcp_writer:
            try:
                self.tcp_writer.close()
                await self.tcp_writer.wait_closed()
            except Exception:
                pass
        if self.udp_transport:
            self.udp_transport.close()