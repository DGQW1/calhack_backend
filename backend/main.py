import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, status, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from websocket_handlers import StreamStats, handle_stream
from video_storage import video_storage


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
            summary = {
                "type": "connection_summary",
                "stream_type": stream_type,
                "chunks_received": stats.chunks_received,
                "bytes_received": stats.bytes_received,
                "started_at": start.isoformat(),
                "ended_at": datetime.now(timezone.utc).isoformat(),
            }
            
            # Add session ID for video compilation
            if stats.session_id:
                summary["session_id"] = stats.session_id
                
            await websocket.send_json(summary)
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


@app.post("/api/compile-video/{session_id}")
async def compile_video(session_id: str) -> dict[str, str]:
    """
    Compile a video from a recording session.
    """
    session = video_storage.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    if session.compiled_file and session.compiled_file.exists():
        return {
            "status": "success",
            "message": "Video already compiled",
            "download_url": f"/api/download/{session_id}"
        }
    
    try:
        compiled_file = await session.finalize()
        if compiled_file:
            return {
                "status": "success",
                "message": "Video compiled successfully",
                "download_url": f"/api/download/{session_id}"
            }
        else:
            raise HTTPException(status_code=500, detail="Failed to compile video")
    except Exception as e:
        logger.error(f"Error compiling video for session {session_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Compilation failed: {str(e)}")


@app.get("/api/download/{session_id}")
async def download_video(session_id: str):
    """
    Download a compiled video file.
    """
    session = video_storage.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    if not session.compiled_file or not session.compiled_file.exists():
        raise HTTPException(status_code=404, detail="Video not compiled yet")
    
    return FileResponse(
        path=session.compiled_file,
        filename=f"recording_{session_id}.mp4",
        media_type="video/mp4"
    )


@app.get("/api/sessions")
async def list_sessions() -> dict[str, list]:
    """
    List all recording sessions.
    """
    sessions = []
    for session_id, session in video_storage.sessions.items():
        sessions.append({
            "session_id": session_id,
            "created_at": session.created_at.isoformat(),
            "is_active": session.is_active,
            "has_compiled_file": session.compiled_file is not None and session.compiled_file.exists(),
            "video_chunks": len(session.video_chunks),
            "audio_chunks": len(session.audio_chunks)
        })
    
    return {"sessions": sessions}


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str) -> dict[str, str]:
    """
    Delete a recording session and its files.
    """
    session = video_storage.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    video_storage.remove_session(session_id)
    return {"status": "success", "message": "Session deleted"}


# Mount static files for serving recordings
app.mount("/recordings", StaticFiles(directory="recordings"), name="recordings")
