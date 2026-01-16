import asyncio
from typing import Iterable, Tuple

import cv2
import numpy as np


def compress_frame_data(frame_data: Iterable, quality: int = 80) -> Tuple[int, bytes]:
    """Encode an ALVideoDevice frame to JPEG and return (timestamp_us, bytes)."""
    width = int(frame_data[0])
    height = int(frame_data[1])
    raw_bytes = frame_data[6]

    np_arr = np.frombuffer(bytearray(raw_bytes), dtype=np.uint8)
    image = np_arr.reshape((height, width, 3))
    image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)

    encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), quality]
    result, encimg = cv2.imencode('.jpg', image, encode_param)
    if not result:
        raise RuntimeError("Failed to encode frame")

    timestamp_sec = int(frame_data[4])
    timestamp_usec = int(frame_data[5])
    capture_timestamp_us = (timestamp_sec * 1_000_000) + timestamp_usec

    return capture_timestamp_us, encimg.tobytes()


async def compress_frame_data_async(frame_data: Iterable, quality: int = 80) -> Tuple[int, bytes]:
    """Async wrapper around compress_frame_data using asyncio.to_thread."""
    return await asyncio.to_thread(compress_frame_data, frame_data, quality)
