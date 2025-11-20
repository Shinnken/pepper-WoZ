#!/usr/bin/env python2
import qi
import threading
from collections import deque
from frame_compresser import compress_frame_data
from SoundReciver_py2 import SoundReceiverModule
from time import sleep

#test




class PepperCamera(object):
    def __init__(self):
        # Initialize fields BEFORE creating services, so init_qi_session can set them.
        # Deque gives O(1) pops from the left, avoiding quadratic slowdowns when streaming frames
        self.frames = deque()
        self.pepper_camera_recorder = None
        self.sound_module_instance = None
        self.audio_bytes = None
        self.init_qi_session()

    def init_qi_session(self):
        CAMERA_INDEX = 0
        RESOLUTION_INDEX = 2
        COLORSPACE_INDEX = 11
        FRAMERATE = 15
        self.session = qi.Session()
        self.session.connect("tcp://127.0.0.1:9559")
        self.session.service("ALTextToSpeech").setLanguage("Polish")
        self.session.service("ALAutonomousLife").setState("solitary")
        self.session.service("ALAutonomousLife").setAutonomousAbilityEnabled("BasicAwareness", False)  # Disable basic awareness to prevent interruptions
        self.delete_subs("kamera")
        self.vid_handle = self.session.service("ALVideoDevice").subscribeCamera(
            "kamera",
            CAMERA_INDEX,
            RESOLUTION_INDEX,
            COLORSPACE_INDEX,
            FRAMERATE
        
        )
        print("Camera subscribed successfully.")

        self.session.service("ALAutonomousLife").switchFocus("nao_blank-52a8bb/behavior_1")  # Prevent autonomous behaviors from interrupting
        self.session.service("ALAutonomousLife").setAutonomousAbilityEnabled("BasicAwareness", False)
        self.session.service("ALAutonomousLife").setAutonomousAbilityEnabled("ListeningMovement", False)
        #ListeningMovement ALFaceDetection.setRecognitionEnabled
        # self.session.service("ALBasicAwareness").pauseAwareness()
        # self.session.service("ALPeoplePerception").setMovementDetectionEnabled(False)
        # self.session.service("ALFaceDetection").setRecognitionEnabled(False)
        


        # Initialize and register sound receiver service (Python 2.7)
        try:
            self.sound_module_instance = SoundReceiverModule(self.session, name="SoundProcessingModule")
            # Register the module as a service so ALAudioDevice can call processRemote
            self.session.registerService("SoundProcessingModule", self.sound_module_instance)
            print("Sound module registered successfully.")
        except Exception as e:
            print("Failed to initialize sound module:", e)

        sleep(0.5)
        self.session.service("ALMotion").angleInterpolationWithSpeed(("HeadYaw", "HeadPitch"), (0, 0.3), 1.0)
        sleep(0.5)

    def delete_subs(self, name):
        all_subscribers = self.session.service("ALVideoDevice").getSubscribers()
        sub_to_delete = [subscriber for subscriber in all_subscribers if unicode(name, "utf-8") in unicode(subscriber, "utf-8")] # type: ignore
        for sub in sub_to_delete:
            self.session.service("ALVideoDevice").unsubscribe(sub)

    def start_recording(self):
        self.session.service("ALMotion").wakeUp() 
        self.session.service("ALMotion").angleInterpolationWithSpeed(("HeadYaw", "HeadPitch"), (0, 0.3), 1.0)
        sleep(1.0)
        #ListeningMovement ALFaceDetection.setRecognitionEnabled
        # self.session.service("ALBasicAwareness").pauseAwareness()
        # self.session.service("ALPeoplePerception").setMovementDetectionEnabled(False)
        # self.session.service("ALFaceDetection").setRecognitionEnabled(False)
        # self.session.service("ALAutonomousLife").setAutonomousAbilityEnabled("ListeningMovement", False)
        self.session.service("ALAutonomousLife").setAutonomousAbilityEnabled("BasicAwareness", False)
        if not self.pepper_camera_recorder:
            self.pepper_camera_recorder = PepperCameraRecorder(self.session, self.vid_handle, self.frames)
            self.pepper_camera_recorder.is_recording = True
            self.pepper_camera_recorder.start()
        # Start audio recording if available
        if self.sound_module_instance:
            try:
                print("Attempting to start audio module...")
                self.sound_module_instance.start()
                self.audio_bytes = None
                print("Audio recording started.")
            except Exception as e:
                print("Failed to start audio recording:", e)
        else:
            print("sound_module_instance is None; audio will not start.")

    def stop_recording(self):
        if self.pepper_camera_recorder:
            self.pepper_camera_recorder.is_recording = False
            self.pepper_camera_recorder.join()
            self.pepper_camera_recorder = None
        # Stop audio recording and capture compressed audio bytes
        if self.sound_module_instance:
            try:
                self.audio_bytes = self.sound_module_instance.stop()
                print("Audio recording stopped. Bytes:", 0 if self.audio_bytes is None else len(self.audio_bytes))
            except Exception as e:
                print("Failed to stop audio recording:", e)

    def exit(self):
        if self.pepper_camera_recorder:
            self.stop_recording()
        self.session.service("ALVideoDevice").unsubscribe(self.vid_handle)
        # Ensure audio module unsubscribes if still active
        try:
            if self.sound_module_instance:
                self.sound_module_instance.stop()
        except:
            pass
    
    def wez_powiedz(self, message):
        self.session.service("ALAnimatedSpeech").say(message)
        print("said: ", message)

    def wez_usiadz(self):
        self.session.service("ALRobotPosture").goToPosture("Sit", 1.0)

    def wez_spij(self):
        self.session.service("ALMotion").angleInterpolationWithSpeed(("HeadYaw", "HeadPitch"), (0, 0.6), 0.05)
        self.session.service("ALAutonomousLife").setState("disabled")
        self.session.service("ALLeds").off("AllLeds")

    def wez_wstawaj(self):
        self.session.service("ALAutonomousLife").setState("solitary")
        self.session.service("ALMotion").angleInterpolationWithSpeed(("HeadYaw", "HeadPitch"), (0, 0.3), 0.05)




class PepperCameraRecorder(threading.Thread):
    def __init__(self, session, vid_handle, frames):
        threading.Thread.__init__(self)
        self.frames = frames
        self.session = session
        self.vid_handle = vid_handle
        self.is_recording = False


    def run(self):
        while self.is_recording:
            frame_data_raw = self.session.service("ALVideoDevice").getImageRemote(self.vid_handle)
            frame_data = compress_frame_data(frame_data_raw)
            self.frames.append(frame_data)
