import socket
import threading
import os
import struct

class PepperSocketManager():
    def __init__(self, host, port_tcp, port_udp, pepper_camera):
        self.pepper_camera = pepper_camera
        self.socket_tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket_udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Increase UDP send buffer to handle bursts
        try:
            self.socket_udp.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4 * 1024 * 1024)
        except Exception:
            pass
        self.target_tcp = (host, port_tcp)
        self.target_udp = (host, port_udp)

        self.tcp_thread = threading.Thread(target=self.tcp_thread_job)
        self.udp_thread = threading.Thread(target=self.udp_thread_job)
        # self.tcp_thread.setDaemon(True)
        # self.udp_thread.setDaemon(True)

        self.tcp_thread_running = False
        self.udp_thread_running = False
        # Audio staging state
        self.pending_audio = None  # None = no stop requested; b'' = explicitly no audio; bytes = audio
        self.audio_sent = False

        print("trying to connect to:", self.target_tcp, self.target_udp)

        self.socket_tcp.connect((host, port_tcp))

        print("connected succesfuly")

        self.tcp_thread.start()
        self.udp_thread.start()

    def tcp_thread_job(self):
        '''
        Listen to TCP commands
        '''
        print("tcp thread started")
        def stop_command():
            self.pepper_camera.stop_recording()
            camera_frames_str = str(len(self.pepper_camera.frames))
            print("attempting to send ", camera_frames_str)
            # Send frame count as a line to delimit from subsequent audio header/data
            msg = (camera_frames_str + "\n").encode('utf-8')
            self.socket_tcp.sendall(msg)
            bytes_sent = len(msg)
            print("succesfuly sent bytes number:", bytes_sent)
            # Stage audio to be sent; either via UDP (default) or send directly over TCP if PEPPER_TCP_AUDIO=1
            try:
                audio_bytes = getattr(self.pepper_camera, 'audio_bytes', None)
                tcp_audio_flag = os.getenv('PEPPER_TCP_AUDIO', '1').strip().lower()
                use_tcp_audio = tcp_audio_flag not in ('0', 'false', 'no', 'off')
                if use_tcp_audio:
                    try:
                        if audio_bytes and len(audio_bytes) > 0:
                            header = "AUDIO_LEN:{}\n".format(len(audio_bytes)).encode('utf-8')
                            self.socket_tcp.sendall(header)
                            self.socket_tcp.sendall(audio_bytes)
                            print("Audio sent over TCP:", len(audio_bytes))
                        else:
                            self.socket_tcp.sendall(b"AUDIO_NONE\n")
                            print("Sent AUDIO_NONE over TCP")
                    except Exception as e:
                        print("Failed to send audio over TCP:", e)
                        # Fallback to UDP staging
                        self.pending_audio = audio_bytes if audio_bytes else b''
                        self.audio_sent = False
                else:
                    self.pending_audio = audio_bytes if audio_bytes else b''
                    self.audio_sent = False
                    if self.pending_audio:
                        print("Audio staged for sending. Size:", len(self.pending_audio))
                    else:
                        print("No audio captured; will notify client.")
            except Exception as e:
                print("Failed to stage audio:", e)

        commands = {
            "start": self.pepper_camera.start_recording,
            "stop":  stop_command,
            "exit": self.exit,
        }

        self.tcp_thread_running = True
        while self.tcp_thread_running:
            command = str(self.socket_tcp.recv(1024).decode('utf-8')).strip()
            if len(command) > 6:
                print("Just about to say: ", command)
                args = command[6:]
                command = command[:5]
                self.pepper_camera.wez_powiedz(args)
            print("received command: ", command, " len:" , len(self.pepper_camera.frames))
            if command in commands:
                commands[command]()
        self.tcp_thread_running = False


    def udp_thread_job(self):
        '''
        Send buffer to server
        '''
        print("udp thread started")
        self.udp_thread_running = True
        while self.udp_thread_running:
            while len(self.pepper_camera.frames) > 0:
                frame_data = self.pepper_camera.frames.popleft()
                # print("sending bytes")
                # print(len(frame_data))
                # print(type(frame_data))
                self.udp_thread_send_frame(frame_data)
            # If no frames to send, see if we need to send audio (staged on stop)
            if len(self.pepper_camera.frames) == 0:
                # Send audio once, if staged and not yet sent
                if self.pending_audio is not None and not self.audio_sent:
                    try:
                        if len(self.pending_audio) == 0:
                            self.socket_udp.sendto(b"AUDIO_NONE", self.target_udp)
                            print("Sent AUDIO_NONE marker")
                        else:
                            # Send AUDIO_START multiple times for robustness
                            try:
                                self.socket_udp.sendto(b"AUDIO_START", self.target_udp)
                                self.socket_udp.sendto(b"AUDIO_START", self.target_udp)
                                self.socket_udp.sendto(b"AUDIO_START", self.target_udp)
                            except Exception:
                                pass
                            CHUNK_SIZE = 1200  # leave headroom for lower MTU paths
                            # Pace chunks slightly to reduce kernel drops on receiver
                            pace_sleep = 0.0005  # default 500us between packets
                            try:
                                # Allow environment override, e.g., PEPPER_AUDIO_PACE_US=1000
                                import os, time as _t
                                pace_us = int(os.getenv('PEPPER_AUDIO_PACE_US', str(int(pace_sleep * 1e6))))
                                pace_sleep = max(0.0, pace_us / 1e6)
                                # Give receiver time to switch state after AUDIO_START
                                _t.sleep(max(0.002, 4 * pace_sleep))
                            except Exception:
                                pass
                            for start in range(0, len(self.pending_audio), CHUNK_SIZE):
                                end = start + CHUNK_SIZE
                                if end > len(self.pending_audio):
                                    end = len(self.pending_audio)
                                chunk = self.pending_audio[start:end]
                                self.socket_udp.sendto(chunk, self.target_udp)
                                if pace_sleep:
                                    import time as _t
                                    _t.sleep(pace_sleep)
                            # Send AUDIO_END multiple times for robustness
                            try:
                                self.socket_udp.sendto(b"AUDIO_END", self.target_udp)
                                self.socket_udp.sendto(b"AUDIO_END", self.target_udp)
                                self.socket_udp.sendto(b"AUDIO_END", self.target_udp)
                            except Exception:
                                pass
                            print("Audio bytes sent: {}".format(len(self.pending_audio)))
                    except Exception as e:
                        print("Failed to send staged audio:", e)
                    finally:
                        self.audio_sent = True
                        self.pending_audio = None
                import time
                time.sleep(0.01)
    
    def udp_thread_send_frame(self, frame):
        '''
        Send single frame to server
        '''
        print("sending frame")
        CHUNK_SIZE = 1400
        timestamp_us, payload = frame
        header = struct.pack('!QI', int(timestamp_us), len(payload))
        frame_packet = header + payload

        for start in range(0, len(frame_packet), CHUNK_SIZE):
            end = start + CHUNK_SIZE
            if end > len(frame_packet):
                end = len(frame_packet)
            chunk = frame_packet[start:end]
            self.socket_udp.sendto(chunk, self.target_udp)

        self.socket_udp.sendto(b"END", self.target_udp)


    def exit(self):
        print("exiting")
        self.pepper_camera.exit()
        self.tcp_thread_running = False
        self.udp_thread_running = False
        self.socket_tcp.close()
        self.socket_udp.close()
        print("exited")