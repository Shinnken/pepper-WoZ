import cv2
import numpy as np


def compress_frame_data(frame_data, quality=80):
    width = frame_data[0]
    height = frame_data[1]
    raw_bytes = frame_data[6]

    np_arr = np.frombuffer(bytearray(raw_bytes), dtype=np.uint8)
    image = np_arr.reshape((height, width, 3))
    image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)

    encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), quality]
    result, encimg = cv2.imencode('.jpg', image, encode_param)

    if not result:
        raise Exception("Nie udalo sie zakodowac obrazu")

    compressed_data = encimg.tobytes()

    timestamp_sec = int(frame_data[4])
    timestamp_usec = int(frame_data[5])
    capture_timestamp_us = (timestamp_sec * 1000000) + timestamp_usec

    return capture_timestamp_us, compressed_data
