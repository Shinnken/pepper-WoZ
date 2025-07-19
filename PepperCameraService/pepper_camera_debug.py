class PepperCamera():
    def __init__(self):
        self.frames = []

    def start_recording(self):
        for i in range(10):
            frame_bytes = b"123123123123lfmds;klgfjsklgsdf123123"
            self.frames.append((frame_bytes, i))

    def stop_recording(self):
        pass

    def exit(self):
        pass
