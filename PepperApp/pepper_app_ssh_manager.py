import paramiko

class SSHManager:
    def __init__(self, username, password):
        self.host = None
        self.port = None
        self.username = username
        self.password = password
        self.client = None

    def set_target(self, host, port):
        self.host = host
        self.port = port

    def connect(self):
        if not self.host or not self.port:
            print("Host and port must be set before connecting")
            return
        try:
            self.client = paramiko.SSHClient()
            self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            self.client.connect(self.host, port=self.port, username=self.username, password=self.password)
            print(f"Connected to {self.host}:{self.port}")
        except Exception as e:
            print(f"Failed to connect: {e}")

    def disconnect(self):
        if self.client:
            self.client.close()
            print("Disconnected")

    def execute_command(self, command):
        if not self.client:
            print("Not connected to any server")
            return None
        self.client.exec_command(command)
        return 0