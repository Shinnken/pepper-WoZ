import socket
import threading
import io

class PepperSocketManager():
    def __init__(self, host, port_tcp, port_udp, pepper_camera):
        self.pepper_camera = pepper_camera
        self.socket_tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket_udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.target_tcp = (host, port_tcp)
        self.target_udp = (host, port_udp)

        self.tcp_thread = threading.Thread(target=self.tcp_thread_job)
        self.udp_thread = threading.Thread(target=self.udp_thread_job)
        # self.tcp_thread.setDaemon(True)
        # self.udp_thread.setDaemon(True)

        self.tcp_thread_running = False
        self.udp_thread_running = False

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
            bytes_sent = self.socket_tcp.send(camera_frames_str.encode('utf-8'))
            print("succesfuly sent bytes number:", bytes_sent)

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
                frame_data = self.pepper_camera.frames.pop(0)
                print("sending bytes")
                print(len(frame_data))
                print(type(frame_data))
                self.udp_thread_send_frame(frame_data)
    
    def udp_thread_send_frame(self, frame):
        '''
        Send single frame to server
        '''
        print("sending frame")
        CHUNK_SIZE = 1400

        for start in range(0, len(frame), CHUNK_SIZE):
            end = start + CHUNK_SIZE
            if end > len(frame):
                end = len(frame)
            chunk = frame[start:end]
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