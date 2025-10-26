import logging
import os
from datetime import datetime, timezone

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware

from keyframes_models import SlideDetectionParams
from storage import SlideStorage
from video_keyframes import KeyframeBroadcaster, VideoChunkProcessor
from websocket_handlers import handle_video_keyframe_stream


logger = logging.getLogger("backend")
logging.basicConfig(level=logging.INFO)


def _get_allowed_origins() -> list[str]:
    allowed = os.getenv("CORS_ALLOW_ORIGINS")
    if not allowed:
        return ["*"]
    return [origin.strip() for origin in allowed.split(",") if origin.strip()]


app = FastAPI(
    title="Video Keyframe Detection Backend",
    description="Receives video WebSocket streams and detects slide keyframes.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_get_allowed_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _get_env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _get_env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


slide_storage = SlideStorage.from_env()
keyframe_broadcaster = KeyframeBroadcaster()

slide_detection_params = SlideDetectionParams(
    tau_stable=_get_env_float("SLIDE_TAU_STABLE", 0.90),
    tau_change=_get_env_float("SLIDE_TAU_CHANGE", 0.75),
    min_stable_duration_ms=_get_env_int("SLIDE_MIN_STABLE_MS", 1000),
    transition_confirm_frames=_get_env_int("SLIDE_TRANSITION_FRAMES", 8),
    cooldown_ms=_get_env_int("SLIDE_COOLDOWN_MS", 1500),
    ema_alpha=_get_env_float("SLIDE_EMA_ALPHA", 0.15),
    downscale_width=_get_env_int("SLIDE_DOWNSCALE_WIDTH", 320),
    downscale_height=_get_env_int("SLIDE_DOWNSCALE_HEIGHT", 180),
    slide_change_ssim=_get_env_float("SLIDE_CHANGE_SSIM", 0.70),
    min_slide_duration_ms=_get_env_int("SLIDE_MIN_SLIDE_DURATION_MS", 1500),
)


async def _require_token(websocket: WebSocket) -> None:
    """
    Optional connection validation via STREAMING_ACCESS_TOKEN environment variable.
    Allows token to be provided via `?token=...` query parameter or `x-stream-token` header.
    """
    expected = os.getenv("STREAMING_ACCESS_TOKEN")
    if not expected:
        return

    provided = websocket.query_params.get("token") or websocket.headers.get("x-stream-token")
    if provided != expected:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid connection token")
        raise PermissionError("Invalid connection token provided for WebSocket connection.")


@app.websocket("/ws/video")
async def video_stream(websocket: WebSocket) -> None:
    stream_type = "video"
    lecture_id = os.getenv("DEFAULT_LECTURE_ID", "default")
    try:
        await _require_token(websocket)
        await websocket.accept()
        start = datetime.now(timezone.utc)

        lecture_id = websocket.query_params.get("lecture_id") or websocket.headers.get("x-lecture-id") or lecture_id

        await websocket.send_json(
            {
                "type": "connection_ack",
                "stream_type": stream_type,
                "received_at": start.isoformat(),
                "lecture_id": lecture_id,
            }
        )

        processor = VideoChunkProcessor(
            lecture_id=lecture_id,
            storage=slide_storage,
            broadcaster=keyframe_broadcaster,
            detector_params=slide_detection_params,
        )

        stats = await handle_video_keyframe_stream(
            websocket,
            processor,
            stream_type=stream_type,
        )

        try:
            await websocket.send_json(
                {
                    "type": "connection_summary",
                    "stream_type": stream_type,
                    "chunks_received": stats.chunks_received,
                    "bytes_received": stats.bytes_received,
                    "lecture_id": lecture_id,
                    "started_at": start.isoformat(),
                    "ended_at": datetime.now(timezone.utc).isoformat(),
                }
            )
        except RuntimeError:
            logger.debug("Unable to send connection summary; websocket already closed.")
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected for %s stream.", stream_type)
    except PermissionError:
        logger.warning("Rejected %s stream connection due to invalid token.", stream_type)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Unexpected error while handling %s stream: %s", stream_type, exc)
        try:
            await websocket.close(code=status.WS_1011_INTERNAL_ERROR, reason="Internal server error")
        except Exception:
            pass  # Connection may already be closed


@app.websocket("/ws/keyframes")
async def keyframe_stream(websocket: WebSocket) -> None:
    stream_type = "keyframes"
    try:
        await _require_token(websocket)
        await websocket.accept()
        await keyframe_broadcaster.register(websocket)

        await websocket.send_json(
            {
                "type": "connection_ack",
                "stream_type": stream_type,
                "received_at": datetime.now(timezone.utc).isoformat(),
            }
        )

        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                break
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected for %s stream.", stream_type)
    except PermissionError:
        logger.warning("Rejected %s stream connection due to invalid token.", stream_type)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Unexpected error while handling %s stream: %s", stream_type, exc)
    finally:
        await keyframe_broadcaster.unregister(websocket)


@app.get("/health")
async def healthcheck() -> dict[str, str]:
    return {"status": "ok"}
