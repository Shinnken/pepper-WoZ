import socket
import threading
from video_maker import make_video_from_frames
import time
class TCPSocketHandler:
    """
    Responsible for sending commands to Pepper camera service
    """
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.bind((self.host, self.port))

    def start(self) -> None | tuple[str, int]:
        self.socket.listen(1)
        self.socket.settimeout(5)  # Set a timeout for the accept call

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

    

class UDPSocketHandler(threading.Thread):
    """
    Responsible for receiving frames form Pepper camera service
    """
    def __init__(self, host, port):
        threading.Thread.__init__(self)
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.bind((host, port))
        self.running = False
        self.listening = False
        self.frames: list[bytes] = []
        self.frames_countdown = -1
        self.patient_id = 0

    def set_patient_id(self, patient_id: int):
        self.patient_id = patient_id


    def run(self):
        RECV_SIZE = 1400
        self.running = True
        bytes_received = b""
        while self.running:
            if not self.listening:
                time.sleep(0.1)
                continue


            if self.frames_countdown != 0:
                # sluchanie kiedy sa klatki do odbioru
                data, _ = self.socket.recvfrom(RECV_SIZE)
                if not data:
                    time.sleep(0.1)
                    continue
                if data == b"END":
                    # odebrano wszystkie dane z klatki
                    self.frames.append(bytes_received)
                    bytes_received = b""
                    if self.frames_countdown > 0:
                        self.frames_countdown -= 1
                        print(f"Frames left: {self.frames_countdown}")
                else:
                    # odebrano czesc klatki
                    bytes_received += data
                    print(f"udp thread received {len(data)} bytes")
            else:
                # nie ma juz klatek do odbioru
                # trzeba przygotować filmik z tego co jest
                self.listening = False
                make_video_from_frames(self.frames, self.patient_id)
                self.frames_countdown = -1
                self.frames = []




    def exit(self):
        self.listening = False
        self.running = False
        self.socket.close()