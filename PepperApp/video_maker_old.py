import cv2
import numpy as np
from datetime import datetime
import os
import tempfile
import subprocess


def make_video_from_frames(frames, patient_id, audio_bytes=None, mux_audio=True):
    if not frames:
        print("No frames to process.")
        return

    current_time = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    width, height = 640, 480

    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    video_path = f'output_{current_time}_{patient_id}.mp4'
    # Derive FPS from audio duration if available; else default to 15
    fps = 15.0
    if audio_bytes:
        try:
            import wave, io
            with wave.open(io.BytesIO(audio_bytes), 'rb') as wf:
                fr = wf.getframerate()
                n_frames_a = wf.getnframes()
                dur = n_frames_a / float(fr) if fr > 0 else 0
                if dur > 0:
                    fps = max(1.0, min(60.0, len(frames) / dur))
        except Exception:
            pass
    out = cv2.VideoWriter(video_path, fourcc, fps, (width, height))

    for idx, frame_data in enumerate(frames):
        # Skip empty or obviously invalid buffers to avoid OpenCV assertion
        if not frame_data or len(frame_data) < 16:
            print(f"Skipping frame {idx}: empty or too small buffer ({0 if not frame_data else len(frame_data)} bytes)")
            continue
        try:
            np_data = np.frombuffer(frame_data, dtype=np.uint8)
            if np_data.size == 0:
                print(f"Skipping frame {idx}: empty decoded buffer")
                continue
            image = cv2.imdecode(np_data, cv2.IMREAD_COLOR)
        except Exception as e:
            print(f"Skipping frame {idx}: imdecode error: {e}")
            continue
        if image is None:
            print(f"Skipping frame {idx}: decode returned None")
            continue
        # Ensure 3 channels BGR
        if len(image.shape) == 2:
            image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        elif image.shape[2] == 1:
            image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        # Ensure size is consistent
        if (image.shape[1], image.shape[0]) != (width, height):
            image = cv2.resize(image, (width, height))
        out.write(image)

    out.release()

    if audio_bytes:
        try:
            # Persist audio to a WAV file for debugging and reuse it for muxing
            audio_path = f'audio_{current_time}_{patient_id}.wav'
            with open(audio_path, 'wb') as f:
                f.write(audio_bytes)

            # Keep audio_path for debugging
            print(f"Saved debug WAV: {audio_path}")

            if mux_audio:
                # Mux using ffmpeg if available
                output_path = f'output_{current_time}_{patient_id}_with_audio.mp4'
                ffmpeg_cmd = [
                    'ffmpeg', '-y',
                    '-i', video_path,
                    '-i', audio_path,
                    '-c:v', 'copy',
                    '-c:a', 'aac', '-b:a', '128k',
                    '-shortest',
                    output_path
                ]
                try:
                    subprocess.run(ffmpeg_cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    print(f"Video with audio created successfully: {output_path}")
                    # Optionally remove the video without audio
                    os.remove(video_path)
                except Exception as e:
                    print(f"ffmpeg failed to mux audio: {e}. Keeping video without audio at {video_path}")
            else:
                print("Muxing disabled; keeping separate WAV and silent MP4.")
        except Exception as e:
            print(f"Failed to handle audio muxing: {e}. Keeping video without audio at {video_path}")
    else:
        print("Video created successfully (no audio provided).")
