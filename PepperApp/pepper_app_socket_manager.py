from pepper_app_socket import TCPSocketHandler, UDPSocketHandler
import os

class SocketManager:
    def __init__(self, host: str, port_tcp: int, port_udp: int):
        self._host = host
        self._port_tcp = port_tcp
        self._port_udp = port_udp
        self.tcp_socket: TCPSocketHandler = TCPSocketHandler(host, port_tcp)
        self.udp_socket: UDPSocketHandler = UDPSocketHandler(host, port_udp)
        self._udp_started = False
        
    def start(self):
        self.tcp_socket.start()
        if self.udp_socket.is_alive():
            return

        if self._udp_started and not self.udp_socket.is_alive():
            # Thread objects cannot be restarted, so create a fresh handler if needed.
            self.udp_socket = UDPSocketHandler(self._host, self._port_udp)

        self.udp_socket.start()
        self._udp_started = True

    
    def check_connection(self) -> bool:
        if self.tcp_socket.conn is None:
            print("TCP connection is not established.")
            return False
        else:
            print("TCP connection is established.")
            return True


    def handle_command(self, command: str, *args: str) -> None:
        """
        Sends the command to camera service
        """
        if command == "speak":
            if len(args) == 0:
                print("No text provided for 'speak' command.")
                return
            text = args[0]
            command = f"speak {text}"

        print("sending command: ", command)
        command_bytes: bytes = command.encode('utf-8')
        self.tcp_socket.send(command_bytes)
        
        match command:
            case "start":
                patient_id = int(args[0]) if args else None
                self.udp_socket.prepare_capture(patient_id)
            case "stop":
                self.stop()
            case "exit":
                self.exit()
            case "sleep" | "wake":
                pass
            case _:
                print(f"Unknown command: {command}")
                return
        print("command sent")




    def stop(self):
        print("waiting for frame countdown (line)")
        header = self.tcp_socket.receive_line(timeout=30.0)
        if not header:
            raise RuntimeError("Timeout waiting for frame count over TCP")
        try:
            frames_left = int(header.decode('utf-8', errors='strict').strip())
        except Exception:
            # Last resort: strip non-digits
            s = ''.join(ch for ch in header.decode('utf-8', errors='ignore') if ch.isdigit())
            frames_left = int(s) if s else 0
        print(f"Frames left: {frames_left}")
        self.udp_socket.frames_countdown = frames_left
        # Optionally receive audio over TCP for reliability
        tcp_audio_flag = os.getenv('PEPPER_TCP_AUDIO', '1').strip().lower()
        use_tcp_audio = tcp_audio_flag not in ('0', 'false', 'no', 'off')
        if use_tcp_audio:
            try:
                # Protocol: server sends a line 'AUDIO_LEN:<n>\n' or 'AUDIO_NONE\n' after frames count
                header = self.tcp_socket.receive_line(timeout=5.0)
                if not header:
                    print("No audio header over TCP; falling back to UDP or none.")
                    return
                header_s = header.decode('utf-8', errors='ignore').strip()
                if header_s == 'AUDIO_NONE':
                    self.udp_socket.audio_bytes = None
                    self.udp_socket.audio_done = True
                    print("TCP reported no audio.")
                    return
                if header_s.startswith('AUDIO_LEN:'):
                    try:
                        n = int(header_s.split(':', 1)[1])
                    except Exception:
                        n = -1
                    if n is None or n < 0 or n > (64 * 1024 * 1024):
                        print(f"Invalid audio length over TCP: {header_s}")
                        return
                    data = self.tcp_socket.receive_exact(n, timeout=max(10.0, n / (64*1024.0)))
                    if data is None:
                        print("Failed to receive full audio over TCP; will finalize without or with partial via UDP.")
                        return
                    self.udp_socket.audio_bytes = data
                    self.udp_socket.audio_done = True
                    print(f"Audio received over TCP: {len(data)} bytes")
            except Exception as e:
                print(f"TCP audio receive error: {e}")


    def exit(self):
        self.tcp_socket.exit()
        self.udp_socket.exit()
        if self.udp_socket.is_alive():
            self.udp_socket.join()
