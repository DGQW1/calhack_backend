import logging
import os
from datetime import datetime, timezone

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware

from websocket_handlers import StreamStats, handle_stream


logger = logging.getLogger("backend")
logging.basicConfig(level=logging.INFO)


def _get_allowed_origins() -> list[str]:
    allowed = os.getenv("CORS_ALLOW_ORIGINS")
    if not allowed:
        return ["*"]
    return [origin.strip() for origin in allowed.split(",") if origin.strip()]


app = FastAPI(
    title="CalHack Streaming Backend",
    description="Receives independent audio and video WebSocket streams.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_get_allowed_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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


async def _websocket_entry(websocket: WebSocket, stream_type: str) -> None:
    await _require_token(websocket)
    await websocket.accept()
    start = datetime.now(timezone.utc)

    await websocket.send_json(
        {
            "type": "connection_ack",
            "stream_type": stream_type,
            "received_at": start.isoformat(),
        }
    )

    try:
        stats = await handle_stream(websocket, stream_type)
        if stats:
            await websocket.send_json(
                {
                    "type": "connection_summary",
                    "stream_type": stream_type,
                    "chunks_received": stats.chunks_received,
                    "bytes_received": stats.bytes_received,
                    "started_at": start.isoformat(),
                    "ended_at": datetime.now(timezone.utc).isoformat(),
                }
            )
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected for %s stream.", stream_type)
    except PermissionError:
        logger.warning("Rejected %s stream connection due to invalid token.", stream_type)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Unexpected error while handling %s stream: %s", stream_type, exc)
        await websocket.close(code=status.WS_1011_INTERNAL_ERROR, reason="Internal server error")


@app.websocket("/ws/video")
async def video_stream(websocket: WebSocket) -> None:
    await _websocket_entry(websocket, "video")


@app.websocket("/ws/audio")
async def audio_stream(websocket: WebSocket) -> None:
    await _websocket_entry(websocket, "audio")


@app.get("/health")
async def healthcheck() -> dict[str, str]:
    return {"status": "ok"}
