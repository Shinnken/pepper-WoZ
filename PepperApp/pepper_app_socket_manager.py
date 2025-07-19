from pepper_app_socket import TCPSocketHandler, UDPSocketHandler

class SocketManager:
    def __init__(self, host: str, port_tcp: int, port_udp: int):
        self.tcp_socket: TCPSocketHandler = TCPSocketHandler(host, port_tcp)
        self.udp_socket: UDPSocketHandler = UDPSocketHandler(host, port_udp)
        
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
                if args:
                    self.udp_socket.set_patient_id(int(args[0]))
                self.udp_socket.listening = True
            case "stop":
                self.stop()
            case "exit":
                self.exit()
            case _:
                print(f"Unknown command: {command}")
                return
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
        self.tcp_socket.exit()
        self.udp_socket.exit()
        if self.udp_socket.is_alive():
            self.udp_socket.join()
