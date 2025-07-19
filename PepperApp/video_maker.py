import cv2
import numpy as np
from datetime import datetime


def make_video_from_frames(frames, patient_id):
    if not frames:
        print("No frames to process.")
        return

    current_time = datetime.now().strftime("%Y%m%d_%H%M%S")
    width, height = 640, 480

    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(f'output_{current_time}_{patient_id}.mp4', fourcc, 4.3, (width, height))

    for frame_data in frames:
        np_data = np.frombuffer(frame_data, dtype=np.uint8)
        image = cv2.imdecode(np_data, cv2.IMREAD_COLOR)
        out.write(image)

    out.release()
    print("Video created successfully.")

def make_picture_from_frame(frame):
    pass