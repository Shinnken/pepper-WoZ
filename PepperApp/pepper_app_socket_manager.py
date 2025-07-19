from pepper_app_socket import TCPSocketHandler, UDPSocketHandler

class SocketManager:
    def __init__(self, host: str, port_tcp: int, port_udp: int):
        self.tcp_socket: TCPSocketHandler = TCPSocketHandler(host, port_tcp)
        self.udp_socket: UDPSocketHandler = UDPSocketHandler(host, port_udp)
        self.is_connected = False
        
    def start(self):
        self.tcp_socket.start()
        self.udp_socket.start()

    
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
        if command.startswith("speak"):
            if len(args) == 0:
                print("No text provided for 'speak' command.")
                return
            text = args[0]
            command_to_send = f"speak {text}"
        else:
            command_to_send = command

        print("sending command: ", command_to_send)
        
        # Don't send commands if not connected (except exit)
        if not self.is_connected and command != "exit":
            print("Not connected, command ignored")
            return
            
        try:
            command_bytes: bytes = command_to_send.encode('utf-8')
            self.tcp_socket.send(command_bytes)
        except (OSError, AttributeError) as e:
            print(f"Failed to send command: {e}")
            return
        
        match command:
            case "start":
                if args:
                    self.udp_socket.set_patient_id(int(args[0]))
                self.udp_socket.listening = True
            case "stop":
                self.stop()
            case "exit":
                self.exit()
        print("command sent")

    def stop(self):
        while True:
            print("waiting for frame countdown")
            frames_left_bytes: bytes | None = self.tcp_socket.receive(1024)
            if frames_left_bytes is not None:
                break
        frames_left = int(str(frames_left_bytes.decode('utf-8')).strip())
        print(f"Frames left: {frames_left}")
        self.udp_socket.frames_countdown = frames_left


    def exit(self):
        self.is_connected = False
        self.tcp_socket.exit()
        self.udp_socket.exit()
        if self.udp_socket.is_alive():
            self.udp_socket.join(timeout=2)  # Add timeout to prevent hanging
