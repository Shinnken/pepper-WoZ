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
        self.conn = None

    def start(self) -> None | tuple[str, int]:
        self.socket.listen(1)
        self.socket.settimeout(10)  # Set a timeout for the accept call

    def accept_connection(self):
        self.conn, addr = self.socket.accept()
        print(f"Connection accepted from {addr}")
        return addr
    

    def exit(self):
        if hasattr(self, "conn") and self.conn:
            try:
                self.conn.close()
            except:
                pass
        try:
            self.socket.close()
        except:
            pass

    def send(self, data: bytes):
        if hasattr(self, "conn") and self.conn:
            try:
                self.conn.sendall(data)
            except (OSError, AttributeError):
                print("Failed to send data - connection closed")
    
    def receive(self, lenght: int):
        if hasattr(self, "conn") and self.conn:
            try:
                return self.conn.recv(lenght)
            except (OSError, AttributeError):
                print("Failed to receive data - connection closed")
                return None

class UDPSocketHandler(threading.Thread):
    """
    Responsible for receiving frames form Pepper camera service
    """
    def __init__(self, host, port):
        threading.Thread.__init__(self)
        self.daemon = True  # Make thread daemon so it doesn't block shutdown
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.bind((host, port))
        self.socket.settimeout(1.0)  # Add timeout to allow checking running flag
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
                try:
                    data, _ = self.socket.recvfrom(RECV_SIZE)
                except socket.timeout:
                    continue  # Check running flag again
                except OSError:
                    break  # Socket closed
                    
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
        try:
            self.socket.close()
        except:
            pass