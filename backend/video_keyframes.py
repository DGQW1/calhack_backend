"""Video keyframe detection and streaming helpers."""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

try:
    import imageio_ffmpeg  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    imageio_ffmpeg = None  # type: ignore

_FFMPEG_BINARY = os.getenv("FFMPEG_BINARY")
if not _FFMPEG_BINARY and imageio_ffmpeg is not None:
    try:
        _binary_path = imageio_ffmpeg.get_ffmpeg_exe()
        os.environ["FFMPEG_BINARY"] = _binary_path
        _FFMPEG_BINARY = _binary_path
    except Exception:  # pragma: no cover - defensive
        _FFMPEG_BINARY = None

if _FFMPEG_BINARY:
    os.environ.setdefault("FFMPEG_BINARY", _FFMPEG_BINARY)

import cv2
import ffmpeg
import numpy as np
from fastapi import WebSocket
from skimage.metrics import structural_similarity

from keyframes_models import SlideCandidate, SlideDetectionParams
from storage import SlideStorage


logger = logging.getLogger("backend.keyframes")

if _FFMPEG_BINARY:
    logger.info(f"Using ffmpeg binary at {_FFMPEG_BINARY}")
else:
    logger.warning(
        "FFMPEG binary not configured; attempting to use system ffmpeg. "
        "Set FFMPEG_BINARY env var if ffmpeg is unavailable."
    )


class VideoAccumulator:
    """Accumulates WebM chunks to build a complete playable stream."""

    def __init__(self, max_chunks: int = 5) -> None:
        self.init_segment: Optional[bytes] = None
        self.media_chunks: list[bytes] = []
        self.max_chunks = max_chunks  # Keep only last N chunks
        self.has_init = False
        self.total_chunks_received = 0

    def add_chunk(self, chunk_bytes: bytes) -> Optional[bytes]:
        """Add a chunk and return accumulated data for processing."""
        self.total_chunks_received += 1

        # Check if this chunk has the EBML header (initialization segment)
        if len(chunk_bytes) >= 4 and chunk_bytes[:4] == b'\x1a\x45\xdf\xa3':
            # This is an init segment - reset and start fresh
            self.init_segment = chunk_bytes
            self.media_chunks = []
            self.has_init = True
            logger.info(f"Found init segment in chunk ({len(chunk_bytes)} bytes)")
            return chunk_bytes  # Return just the init segment
        elif self.has_init and self.init_segment:
            # Append media data chunk
            self.media_chunks.append(chunk_bytes)

            # Keep only last N chunks to prevent infinite growth
            if len(self.media_chunks) > self.max_chunks:
                self.media_chunks.pop(0)

            # Build complete WebM: init segment + all media chunks
            complete_data = bytearray(self.init_segment)
            for chunk in self.media_chunks:
                complete_data.extend(chunk)

            logger.debug(f"Accumulated {len(self.media_chunks)} chunks, {len(complete_data)} bytes total")
            return bytes(complete_data)
        else:
            # No init segment yet, can't process
            logger.debug(f"Skipping chunk {self.total_chunks_received} - no init segment yet")
            return None


class SlideKeyframeDetector:
    """Stateful slide detector using SSIM stability heuristics."""

    def __init__(self, lecture_id: str, params: Optional[SlideDetectionParams] = None) -> None:
        self.lecture_id = lecture_id
        self.params = params or SlideDetectionParams()
        self._baseline: Optional[np.ndarray] = None
        self._state: str = "searching"
        self._stable_since_ms: Optional[int] = None
        self._last_lock_ms: Optional[int] = None
        self._transition_frames: int = 0
        self._current_candidate: Optional[SlideCandidate] = None
        self._locked_reference: Optional[np.ndarray] = None
        self._pending_emit: List[SlideCandidate] = []
        self._last_timestamp_ms: Optional[int] = None

    @staticmethod
    def _preprocess(frame: np.ndarray, params: SlideDetectionParams) -> np.ndarray:
        resized = cv2.resize(frame, (params.downscale_width, params.downscale_height))
        ycrcb = cv2.cvtColor(resized, cv2.COLOR_BGR2YCrCb)
        luminance = ycrcb[:, :, 0]
        # Stronger blur to ignore minor variations like cursor movement
        blurred = cv2.GaussianBlur(luminance, (5, 5), 1.0)
        return blurred.astype(np.float32)

    @staticmethod
    def _encode_image(frame: np.ndarray) -> bytes:
        success, buffer = cv2.imencode(".jpg", frame)
        if not success:
            raise RuntimeError("Failed to encode slide frame to JPEG")
        return buffer.tobytes()

    def _lock_slide(
        self,
        frame: np.ndarray,
        processed: np.ndarray,
        timestamp_ms: int,
        ssim_score: float,
        metadata: Dict[str, Any],
    ) -> None:
        if self._current_candidate is not None:
            return

        image_bytes = self._encode_image(frame)
        captured_at = metadata.get("capturedAt")
        self._current_candidate = SlideCandidate(
            lecture_id=self.lecture_id,
            start_ms=timestamp_ms,
            lock_ssim=ssim_score,
            image_bytes=image_bytes,
            metadata=dict(metadata),
            captured_at=captured_at,
        )
        self._last_lock_ms = timestamp_ms
        self._state = "locked"
        self._locked_reference = processed.copy()
        logger.info(f"🔒 Locked onto slide at t={timestamp_ms}ms, ssim={ssim_score:.3f}")

    def process_frame(
        self,
        frame: np.ndarray,
        timestamp_ms: int,
        metadata: Dict[str, Any],
    ) -> List[SlideCandidate]:
        params = self.params
        self._last_timestamp_ms = timestamp_ms

        processed = self._preprocess(frame, params)

        if self._baseline is None:
            self._baseline = processed
            return []

        ssim_baseline = float(structural_similarity(self._baseline, processed, data_range=255.0))

        alpha = params.ema_alpha
        if self._state == "locked":
            alpha *= 0.25  # adapt baseline slowly while locked to avoid masking slide changes
        self._baseline = alpha * processed + (1 - alpha) * self._baseline

        completed: List[SlideCandidate] = []

        # Status logging every 15 frames (more frequent for lower framerates)
        if hasattr(self, '_frame_count'):
            self._frame_count += 1
        else:
            self._frame_count = 0

        if self._frame_count % 15 == 0:
            stable_duration = 0
            if self._stable_since_ms is not None:
                stable_duration = timestamp_ms - self._stable_since_ms
            logger.info(
                f"Detector state={self._state}, ssim={ssim_baseline:.3f}, "
                f"stable_duration={stable_duration}ms, threshold={params.tau_stable:.3f}"
            )

        if self._state == "searching":
            if ssim_baseline >= params.tau_stable:
                if self._stable_since_ms is None:
                    self._stable_since_ms = timestamp_ms
                    logger.info(f"⏱️  Content stabilizing at t={timestamp_ms}ms, ssim={ssim_baseline:.3f}")
                stable_duration = timestamp_ms - self._stable_since_ms
                cooldown_passed = (
                    self._last_lock_ms is None or timestamp_ms - self._last_lock_ms >= params.cooldown_ms
                )
                if stable_duration >= params.min_stable_duration_ms and cooldown_passed:
                    candidate_start = self._stable_since_ms
                    logger.info(f"✅ Content-complete slide detected after {stable_duration}ms of stability")
                    self._lock_slide(frame, processed, candidate_start, ssim_baseline, metadata)
                    if self._pending_emit:
                        completed.extend(self._pending_emit)
                        self._pending_emit = []
            else:
                # Reset if content becomes unstable
                if self._stable_since_ms is not None:
                    logger.info(f"❌ Content unstable, resetting (ssim={ssim_baseline:.3f} < {params.tau_stable})")
                self._stable_since_ms = None
        else:  # locked
            locked_similarity = ssim_baseline
            if self._locked_reference is not None:
                locked_similarity = float(
                    structural_similarity(self._locked_reference, processed, data_range=255.0)
                )

            # Detect significant content change indicating a new slide
            # Both conditions must be met: change from locked reference AND change from baseline
            change_detected = (
                locked_similarity <= params.slide_change_ssim and
                ssim_baseline <= params.tau_change
            )

            if change_detected:
                elapsed = timestamp_ms - (self._last_lock_ms or timestamp_ms)
                if elapsed >= params.min_slide_duration_ms:
                    self._transition_frames += 1
                    if self._transition_frames == 1:
                        logger.info(
                            f"🔄 Slide transition starting at t={timestamp_ms}ms "
                            f"(locked_ssim={locked_similarity:.3f}, baseline_ssim={ssim_baseline:.3f})"
                        )
                else:
                    # Ignore early fluctuations before the slide has been on-screen long enough
                    self._transition_frames = 0
            else:
                # Content still similar to locked slide - reset transition counter
                if self._transition_frames > 0:
                    logger.info(f"🔙 False transition alarm, content stabilized again")
                self._transition_frames = 0

            if self._transition_frames >= params.transition_confirm_frames and self._current_candidate is not None:
                self._current_candidate.end_ms = timestamp_ms
                duration_ms = timestamp_ms - self._current_candidate.start_ms
                logger.info(
                    f"🔓 Slide transition confirmed (duration={duration_ms}ms, "
                    f"baseline_ssim={ssim_baseline:.3f}, locked_ssim={locked_similarity:.3f}). "
                    f"Searching for next content-complete slide..."
                )
                self._pending_emit.append(self._current_candidate)
                self._current_candidate = None
                self._state = "searching"
                self._stable_since_ms = None
                self._transition_frames = 0
                self._locked_reference = None
                self._baseline = processed

        return completed

    def flush(self) -> List[SlideCandidate]:
        completed: List[SlideCandidate] = []
        if self._pending_emit:
            completed.extend(self._pending_emit)
            self._pending_emit = []

        if self._current_candidate is not None:
            if self._current_candidate.end_ms is None:
                end_ms = self._last_timestamp_ms or self._current_candidate.start_ms
                self._current_candidate.end_ms = end_ms
            completed.append(self._current_candidate)
            self._current_candidate = None
        self._locked_reference = None

        return completed


class KeyframeBroadcaster:
    """Tracks downstream WebSocket subscribers and broadcasts keyframes."""

    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def register(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections.add(websocket)

    async def unregister(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections.discard(websocket)

    async def broadcast(self, payload: Dict[str, Any]) -> None:
        async with self._lock:
            connections = list(self._connections)

        for connection in connections:
            try:
                await connection.send_json(payload)
            except Exception:
                await self.unregister(connection)


def _parse_iso_to_epoch_ms(value: Optional[str]) -> int:
    if not value:
        return int(datetime.now(timezone.utc).timestamp() * 1000)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return int(datetime.now(timezone.utc).timestamp() * 1000)
    return int(parsed.timestamp() * 1000)


def _apply_orientation(frame: np.ndarray, orientation: Optional[int]) -> np.ndarray:
    if orientation in (90, -270):
        return cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
    if orientation in (180, -180):
        return cv2.rotate(frame, cv2.ROTATE_180)
    if orientation in (270, -90):
        return cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
    return frame


def _decode_frames(chunk_bytes: bytes) -> tuple[List[np.ndarray], float]:
    if not chunk_bytes:
        return [], 0.0

    # Write the WebM chunk to a temporary file
    with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as tmp_input:
        tmp_input.write(chunk_bytes)
        tmp_input.flush()
        input_path = tmp_input.name

    # Create a temporary output file for FFmpeg to write to
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp_output:
        output_path = tmp_output.name

    frames: List[np.ndarray] = []
    fps = 30.0

    try:
        # Use FFmpeg to convert the WebM chunk to a proper MP4 file
        # This handles incomplete/fragmented WebM streams better
        try:
            # Add fflags to be more tolerant of incomplete WebM data
                (
                    ffmpeg
                    .input(input_path, fflags='+genpts+igndts')
                    .output(output_path,
                           vcodec='libx264',  # Re-encode to H.264
                       preset='ultrafast',  # Fast encoding
                       loglevel='error',  # Suppress logs except errors
                       **{'movflags': 'frag_keyframe+empty_moov',
                          'avoid_negative_ts': 'make_zero'})  # Fragmented MP4
                .overwrite_output()
                .run(
                    capture_stdout=True,
                    capture_stderr=True,
                    cmd=_FFMPEG_BINARY or "ffmpeg",
                )
            )
        except ffmpeg.Error as e:
            # If FFmpeg fails, the chunk is likely incomplete/corrupted
            # This is normal for fragmented WebM streams - just skip it
            stderr = e.stderr.decode('utf-8') if e.stderr else ''
            if 'EBML header parsing failed' in stderr or 'Invalid data found' in stderr:
                logger.debug(f"Skipping incomplete WebM chunk (this is normal for streaming)")
                return [], 0.0

            logger.warning(f"FFmpeg conversion failed: {stderr[:200]}")
            # Try direct read as fallback for other errors
            capture = cv2.VideoCapture(input_path)
            fps = float(capture.get(cv2.CAP_PROP_FPS))
            if not fps or np.isnan(fps):
                fps = 30.0
            while True:
                success, frame = capture.read()
                if not success or frame is None:
                    break
                frames.append(frame)
            capture.release()
            return frames, fps if frames else 0.0

        # Now read the properly formatted MP4 with OpenCV
        capture = cv2.VideoCapture(output_path)
        fps = float(capture.get(cv2.CAP_PROP_FPS))
        if not fps or np.isnan(fps):
            fps = 30.0

        while True:
            success, frame = capture.read()
            if not success or frame is None:
                break
            frames.append(frame)
        capture.release()

    finally:
        # Clean up temporary files
        try:
            os.unlink(input_path)
        except FileNotFoundError:
            pass
        try:
            os.unlink(output_path)
        except FileNotFoundError:
            pass

    return frames, fps if frames else 0.0


class VideoChunkProcessor:
    """Processes media chunks for slide keyframe detection."""

    def __init__(
        self,
        lecture_id: str,
        storage: SlideStorage,
        broadcaster: KeyframeBroadcaster,
        detector_params: Optional[SlideDetectionParams] = None,
        session_id: Optional[str] = None,
    ) -> None:
        self.lecture_id = lecture_id
        self.storage = storage
        self.broadcaster = broadcaster
        self.detector = SlideKeyframeDetector(lecture_id, detector_params)
        self.accumulator = VideoAccumulator(max_chunks=3)
        self.processed_chunks = 0
        self.total_frames_extracted = 0
        self.last_frame_count = 0  # Track how many frames we processed last time
        self.session_id = session_id

    async def process_chunk(self, chunk_bytes: bytes, metadata: Dict[str, Any], websocket: WebSocket) -> None:
        sequence = metadata.get('sequence', '?')

        # Accumulate chunks into a growing WebM stream
        accumulated_bytes = self.accumulator.add_chunk(chunk_bytes)

        if not accumulated_bytes:
            logger.debug(f"Chunk {sequence}: waiting for init segment")
            return

        self.processed_chunks += 1

        # Extract all frames from accumulated data
        frames, fps = _decode_frames(accumulated_bytes)
        if not frames:
            logger.debug(f"No frames extracted from accumulated data (chunk {sequence})")
            return

        total_frames = len(frames)
        logger.info(f"Chunk {sequence}: Extracted {total_frames} total frames from accumulated stream (fps={fps:.1f})")

        # Only process NEW frames (frames we haven't seen before)
        # The accumulated stream contains old + new frames
        # We track how many we processed last time and skip those
        new_frames_start_idx = self.last_frame_count
        new_frames = frames[new_frames_start_idx:]

        if not new_frames:
            logger.debug(f"Chunk {sequence}: No new frames to process (last_count={self.last_frame_count}, total={total_frames})")
            self.last_frame_count = total_frames
            return

        logger.info(f"Chunk {sequence}: Processing {len(new_frames)} new frames (skipping {new_frames_start_idx} already processed)")

        # Calculate base timestamp from metadata
        base_ms = _parse_iso_to_epoch_ms(metadata.get("capturedAt"))
        orientation_raw = metadata.get("orientation")
        orientation: Optional[int]
        if isinstance(orientation_raw, str):
            try:
                orientation = int(orientation_raw)
            except ValueError:
                orientation = None
        else:
            orientation = orientation_raw

        frame_interval = 0.0
        if fps > 0:
            frame_interval = 1000.0 / fps

        # Process only the new frames
        for relative_idx, raw_frame in enumerate(new_frames):
            absolute_frame_idx = new_frames_start_idx + relative_idx
            oriented_frame = _apply_orientation(raw_frame, orientation)

            # Calculate timestamp for this frame based on its position in the stream
            timestamp_ms = base_ms + int(absolute_frame_idx * frame_interval)

            completed = self.detector.process_frame(oriented_frame, timestamp_ms, metadata)

            self.total_frames_extracted += 1

            if completed:
                logger.info(f"Detector returned {len(completed)} completed slides at frame {self.total_frames_extracted}")
            for slide in completed:
                logger.info(f"Emitting slide {slide.id} (start={slide.start_ms}, end={slide.end_ms})")
                await self._persist_and_emit(slide, websocket)
                logger.info(f"Successfully emitted slide {slide.id}")

        # Update count of processed frames
        self.last_frame_count = total_frames

    async def finalize(self, websocket: WebSocket) -> None:
        logger.info(f"Finalizing video processor: processed {self.processed_chunks} chunks, {self.total_frames_extracted} frames")
        completed = self.detector.flush()
        for slide in completed:
            await self._persist_and_emit(slide, websocket)

    async def _persist_and_emit(self, slide: SlideCandidate, websocket: WebSocket) -> None:
        try:
            slide.session_id = self.session_id
            result = self.storage.store_image(
                slide.image_bytes,
                key=f"{slide.id}.jpg",
                session_id=self.session_id,
            )
            slide.storage_url = result.url
            slide.storage_key = result.storage_key
        except Exception as e:
            logger.error(f"Failed to store slide image: {e}")
            # Don't emit this slide if storage fails
            return

        payload = {"type": "keyframe_detected", **slide.base_payload()}
        logger.info(
            "Detected slide keyframe",
            extra={
                "lecture_id": slide.lecture_id,
                "keyframe_id": slide.id,
                "t_start_ms": slide.start_ms,
                "t_end_ms": slide.end_ms,
                "storage_url": slide.storage_url,
            },
        )

        try:
            await self.broadcaster.broadcast(payload)
        except Exception as e:
            logger.warning(f"Failed to broadcast keyframe: {e}")

        # Try to send to websocket, but don't fail if it's already closed
        try:
            await websocket.send_json(payload)
        except RuntimeError as e:
            # WebSocket already closed - this is expected during shutdown
            logger.debug(f"Could not send keyframe to websocket (already closed): {e}")
        except Exception as e:
            logger.warning(f"Unexpected error sending keyframe to websocket: {e}")
