import cv2
import numpy as np
from datetime import datetime
import os
import subprocess
import wave
import io


def _compute_median(values):
    if not values:
        return None
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    mid = n // 2
    if n % 2 == 1:
        return float(sorted_vals[mid])
    return (sorted_vals[mid - 1] + sorted_vals[mid]) / 2.0


def _audio_duration_seconds(audio_bytes):
    if not audio_bytes:
        return None
    try:
        with wave.open(io.BytesIO(audio_bytes), 'rb') as wf:
            frame_rate = wf.getframerate()
            nframes = wf.getnframes()
            if frame_rate > 0:
                return nframes / float(frame_rate)
    except Exception as exc:
        print(f"Failed to read audio duration: {exc}")
    return None


def make_video_from_frames(frames, patient_id, audio_bytes=None, mux_audio=True):
    if not frames:
        print("No frames to process.")
        return

    current_time = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    width, height = 640, 480

    structured_frames = []
    for idx, source in enumerate(frames):
        if isinstance(source, tuple) and len(source) == 2:
            ts_us, buffer_bytes = source
        else:
            ts_us = None
            buffer_bytes = source
        if not buffer_bytes:
            continue
        structured_frames.append({
            "idx": idx,
            "ts": ts_us,
            "data": buffer_bytes,
        })

    if not structured_frames:
        print("No decodable frames available after parsing.")
        return

    structured_frames.sort(key=lambda item: (item["ts"] is None, item["ts"] if item["ts"] is not None else item["idx"]))

    filtered_frames = []
    last_ts = None
    for entry in structured_frames:
        ts_us = entry["ts"]
        if ts_us is not None:
            if last_ts is not None and ts_us <= last_ts:
                # Skip duplicate or retrograde frames to avoid visual rewinds
                continue
            last_ts = ts_us
        filtered_frames.append(entry)

    if not filtered_frames:
        print("All frames were filtered out due to invalid timestamps.")
        return

    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    video_path = f'output_{current_time}_{patient_id}.mp4'

    ts_values = [entry["ts"] for entry in filtered_frames if entry["ts"] is not None]
    delta_values = []
    for i in range(1, len(ts_values)):
        delta = ts_values[i] - ts_values[i - 1]
        if delta > 0:
            delta_values.append(delta)
    median_delta = _compute_median(delta_values)
    capture_span_us = ts_values[-1] - ts_values[0] if len(ts_values) >= 2 else None
    capture_span_sec = (capture_span_us / 1e6) if capture_span_us and capture_span_us > 0 else None
    audio_duration = _audio_duration_seconds(audio_bytes) if audio_bytes else None

    expected_interval_us = None
    if median_delta and median_delta > 0:
        expected_interval_us = median_delta
    elif capture_span_sec and len(ts_values) > 1:
        expected_interval_us = int((capture_span_sec * 1e6) / (len(ts_values) - 1))
    elif audio_duration and len(filtered_frames) > 1:
        expected_interval_us = int((audio_duration * 1e6) / (len(filtered_frames) - 1))

    target_duration_sec = None
    if audio_duration and audio_duration > 0:
        target_duration_sec = audio_duration
    elif capture_span_sec and capture_span_sec > 0:
        target_duration_sec = capture_span_sec
    elif expected_interval_us and expected_interval_us > 0:
        target_duration_sec = (expected_interval_us / 1e6) * len(filtered_frames)
    else:
        target_duration_sec = len(filtered_frames) / 15.0 if len(filtered_frames) > 0 else 1.0

    fill_plan = [0] * len(filtered_frames)
    planned_fill = 0
    if expected_interval_us:
        last_ts = None
        GAP_TOLERANCE = 1.2
        MAX_DUP_FILL = 180
        for idx, entry in enumerate(filtered_frames):
            ts = entry["ts"]
            if ts is not None and last_ts is not None:
                gap_us = ts - last_ts
                if gap_us > expected_interval_us * GAP_TOLERANCE:
                    missing = int(round(gap_us / expected_interval_us)) - 1
                    if missing > 0:
                        capped = min(missing, MAX_DUP_FILL)
                        fill_plan[idx] = capped
                        planned_fill += capped
            if ts is not None:
                last_ts = ts

    planned_total_frames = len(filtered_frames) + planned_fill
    if not target_duration_sec or target_duration_sec <= 0:
        target_duration_sec = max(1.0, len(filtered_frames) / 15.0)
    fps = planned_total_frames / target_duration_sec if target_duration_sec > 0 else 15.0
    fps = max(1.0, min(60.0, fps))

    if not expected_interval_us and fps:
        expected_interval_us = int(1e6 / fps)

    out = cv2.VideoWriter(video_path, fourcc, fps, (width, height))

    last_ts = None
    duplicates_inserted = 0
    estimated_missing = 0
    frames_written = 0
    last_frame_image = None

    for idx, entry in enumerate(filtered_frames):
        frame_data = entry["data"]
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
        if expected_interval_us and last_ts is not None and entry["ts"] is not None and last_frame_image is not None:
            requested_fill = fill_plan[idx] if idx < len(fill_plan) else 0
            if requested_fill > 0:
                for _ in range(requested_fill):
                    out.write(last_frame_image)
                duplicates_inserted += requested_fill
                estimated_missing += requested_fill
        out.write(image)
        frames_written += 1
        if entry["ts"] is not None:
            last_ts = entry["ts"]
        last_frame_image = image

    out.release()
    total_frames_output = frames_written + duplicates_inserted
    if duplicates_inserted:
        print(f"Inserted {duplicates_inserted} placeholder frames (planned {planned_fill}) to cover ~{estimated_missing} missing intervals.")
    if capture_span_sec:
        print(f"Capture span: {capture_span_sec:.2f}s, target fps: {fps:.2f}, frames written: {total_frames_output}")
    elif audio_duration:
        print(f"Audio duration: {audio_duration:.2f}s, target fps: {fps:.2f}, frames written: {total_frames_output}")
    else:
        print(f"Frames written: {total_frames_output}, fps fallback: {fps:.2f}")

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
