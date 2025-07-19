import qi
import threading
from frame_compresser import compress_frame_data
#test

class PepperCamera():
    def __init__(self):

        self.init_qi_session()
        
        self.frames = []

        self.pepper_camera_recorder = None

    def init_qi_session(self):
        CAMERA_INDEX = 0
        RESOLUTION_INDEX = 2
        COLORSPACE_INDEX = 11
        FRAMERATE = 15
        self.session = qi.Session()
        self.session.connect("tcp://127.0.0.1:9559")
        self.delete_subs("kamera")
        self.vid_handle = self.session.service("ALVideoDevice").subscribeCamera(
            "kamera",
            CAMERA_INDEX,
            RESOLUTION_INDEX,
            COLORSPACE_INDEX,
            FRAMERATE
        
        )
        print("Camera subscribed successfully.")


    def delete_subs(self, name):
        all_subscribers = self.session.service("ALVideoDevice").getSubscribers()
        sub_to_delete = [subscriber for subscriber in all_subscribers if unicode(name, "utf-8") in unicode(subscriber, "utf-8")] # type: ignore
        for sub in sub_to_delete:
            self.session.service("ALVideoDevice").unsubscribe(sub)

    def start_recording(self):
        if not self.pepper_camera_recorder:
            self.pepper_camera_recorder = PepperCameraRecorder(self.session, self.vid_handle, self.frames)
            self.pepper_camera_recorder.is_recording = True
            self.pepper_camera_recorder.start()

    def stop_recording(self):
        if self.pepper_camera_recorder:
            self.pepper_camera_recorder.is_recording = False
            self.pepper_camera_recorder.join()
            self.pepper_camera_recorder = None

    def exit(self):
        if self.pepper_camera_recorder:
            self.stop_recording()
        self.session.service("ALVideoDevice").unsubscribe(self.vid_handle)
    
    def wez_powiedz(self, message):
        self.session.service("ALTextToSpeech").say(message)
        print("said: ", message)


class PepperCameraRecorder(threading.Thread):
    def __init__(self, session, vid_handle, frames):
        threading.Thread.__init__(self)
        self.frames = frames
        self.session = session
        self.vid_handle = vid_handle
        self.is_recording = False


    def run(self):
        while self.is_recording:
            frame_data = self.session.service("ALVideoDevice").getImageRemote(self.vid_handle)
            frame_data = compress_frame_data(frame_data)
            self.frames.append(frame_data)
