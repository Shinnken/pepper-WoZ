import numpy as np
import pyaudio
import wave
import io


class SoundReceiverModule(object):
    """
    A NAOqi module to subscribe to ALAudioDevice and record microphone data.
    """
    def __init__(self, session, name="SoundReceiverModule"):
        super(SoundReceiverModule, self).__init__()
        self.session = session
        self.audio_service = session.service("ALAudioDevice")
        self.module_name = name
        self.channels = 1  # Assuming you want to process the front microphone
        self.accumulated_frames = []
        self.is_recording = False

    def start(self):
        """
        Subscribes to the audio device and starts recording.
        """
        self.audio_service.closeAudioInputs()
        self.audio_service.setClientPreferences(self.module_name, 16000, self.channels, 0)
        self.audio_service.subscribe(self.module_name)
        self.is_recording = True
        self.accumulated_frames = []
        print("[SoundReceiver] Started recording.")

    def stop(self):
        """
        Stops recording, unsubscribes from the audio device, and compresses the recording.
        """
        self.is_recording = False
        self.audio_service.unsubscribe(self.module_name)
        
        if self.accumulated_frames:
            full_recording = b''.join(self.accumulated_frames)
            compressed_audio = self._compress_recording(full_recording)
            print(f"[SoundReceiver] Recording stopped and compressed. Original size: {len(full_recording)} bytes, Compressed size: {len(compressed_audio)} bytes")
            self.accumulated_frames = []
            return compressed_audio
        else:
            print("[SoundReceiver] No audio data recorded.")
            return None

    def _compress_recording(self, audio_data):
        """
        Compress the recorded audio by downsampling.
        """
        try:
            # Convert bytes to numpy array for processing
            audio_array = np.frombuffer(audio_data, dtype=np.int16)
            
            # Simple compression: downsample by taking every other sample
            compressed_audio = audio_array[::2]
            
            # Create compressed WAV file in memory
            p = pyaudio.PyAudio()
            audio_format = pyaudio.paInt16
            channels = 1
            rate = 8000  # Half the original rate due to downsampling

            byte_buffer = io.BytesIO()
            with wave.open(byte_buffer, "wb") as wf:
                wf.setnchannels(channels)
                wf.setsampwidth(p.get_sample_size(audio_format))
                wf.setframerate(rate)
                wf.writeframes(compressed_audio.tobytes())

            byte_buffer.seek(0)
            compressed_data = byte_buffer.getvalue()
            p.terminate()
            
            return compressed_data
            
        except Exception as e:
            print(f"[SoundReceiver] Error during audio compression: {e}")
            return audio_data  # Return original data if compression fails

    def processRemote(self, nbOfChannels, nbrOfSamplesByChannel, timestamp, buffer):
        """
        Process incoming audio buffer from the robot's microphone.
        This method is called by the robot operating system.
        """
        if self.is_recording:
            self.accumulated_frames.append(buffer)
