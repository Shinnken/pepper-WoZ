import io
from PIL import Image
import cv2
import numpy as np

def compress_frame_data_but_slower(frame_data, quality=80):
    print "tutaj zaczynam kompresowac"
    width = frame_data[0]
    height = frame_data[1]
    raw_bytes = frame_data[6]  # Could be a list of ints

    print('frame:', frame_data[:6])
    
    # Convert to a string/buffer:
    buffer_data = ''.join(chr(b) for b in raw_bytes)

    image = Image.frombytes("RGB", (width, height), buffer_data, "raw", "RGB") # type: ignore
    output = io.BytesIO()
    image.save(output, format="JPEG", quality=quality)

    timestamp_ms = frame_data[4]
    timestamp_us = frame_data[5]
    timestamp = timestamp_ms + timestamp_us / 1e6

    print "a tutaj kurde bele koncze"

    return output.getvalue()

def compress_frame_data(frame_data, quality=80):
    print "tutaj zaczynam kompresowac"
    width = frame_data[0]
    height = frame_data[1]
    raw_bytes = frame_data[6]  # list of ints

    print('frame:', frame_data[:6])

    np_arr = np.frombuffer(bytearray(raw_bytes), dtype=np.uint8)

    image = np_arr.reshape((height, width, 3))
    image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)

    encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), quality]
    result, encimg = cv2.imencode('.jpg', image, encode_param)

    if not result:
        raise Exception("Nie udalo sie zakodowac obrazu")

    compressed_data = encimg.tobytes()  # Python 2 compatible

    timestamp_ms = frame_data[4]
    timestamp_us = frame_data[5]
    timestamp = timestamp_ms + timestamp_us / 1e6

    print "a tutaj kurde bele koncze"

    return compressed_data