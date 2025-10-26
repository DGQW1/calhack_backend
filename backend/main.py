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
    """Video endpoint - BOTH records chunks for compilation AND detects keyframes."""
    stream_type = "video"
    lecture_id = os.getenv("DEFAULT_LECTURE_ID", "default")
    try:
        await _require_token(websocket)
        await websocket.accept()
        start = datetime.now(timezone.utc)

        lecture_id = websocket.query_params.get("lecture_id") or websocket.headers.get("x-lecture-id") or lecture_id

        # Initialize keyframe detector
        processor = VideoChunkProcessor(
            lecture_id=lecture_id,
            storage=slide_storage,
            broadcaster=keyframe_broadcaster,
            detector_params=slide_detection_params,
        )

        await websocket.send_json(
            {
                "type": "connection_ack",
                "stream_type": stream_type,
                "received_at": start.isoformat(),
                "lecture_id": lecture_id,
            }
        )

        # Get or create a recording session for video compilation
        from websocket_handlers import session_manager
        session_id = await session_manager.get_or_create_session(stream_type)
        session = video_storage.get_session(session_id)
        logger.info(f"Using session {session_id} for {stream_type} stream with keyframe detection")

        stats = StreamStats(stream_type=stream_type, session_id=session_id)
        metadata_queue = []

        try:
            while True:
                try:
                    message = await websocket.receive()
                except Exception as e:
                    logger.error(f"[{stream_type}] Error receiving message: {e}", exc_info=True)
                    break

                message_type = message.get("type")
                if message_type == "websocket.disconnect":
                    logger.info(f"[{stream_type}] Received disconnect message")
                    break

                chunk_bytes = message.get("bytes")
                chunk_text = message.get("text")

                stats.chunks_received += 1

                # Handle metadata (text messages)
                if chunk_text is not None:
                    from websocket_handlers import _extract_client_metadata, _utc_timestamp
                    client_meta = _extract_client_metadata(chunk_text)
                    if client_meta:
                        metadata_queue.append(client_meta)
                    continue

                # Handle binary chunk
                if chunk_bytes is None:
                    continue

                stats.bytes_received += len(chunk_bytes)

                # Get metadata for this chunk
                metadata = metadata_queue.pop(0) if metadata_queue else {}
                sequence = metadata.get('sequence', 'unknown')

                # 1. Store chunk for video compilation
                if session:
                    chunk_metadata = {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "stream_type": stream_type,
                        "session_id": session_id,
                        "message_format": "binary",
                        "chunk_size_bytes": len(chunk_bytes),
                    }
                    if metadata:
                        chunk_metadata["client_metadata"] = metadata

                    await session.add_video_chunk(chunk_bytes, chunk_metadata)
                    logger.info(f"[{stream_type}] Stored chunk {sequence} for compilation (session {session_id})")

                # 2. Process chunk for keyframe detection
                try:
                    await processor.process_chunk(chunk_bytes, metadata, websocket)
                    logger.info(f"[{stream_type}] Processed chunk {sequence} for keyframe detection")
                except Exception as e:
                    logger.error(f"Keyframe detection failed for chunk {sequence}: {e}", exc_info=True)

        except WebSocketDisconnect:
            logger.info(f"[{stream_type}] WebSocket disconnected")
        finally:
            # Finalize keyframe detector
            logger.info(f"[{stream_type}] Finalizing keyframe processor")
            await processor.finalize(websocket)

            # Mark stream as disconnected for session manager
            await session_manager.mark_stream_disconnected(session_id, stream_type)

        # Send summary
        try:
            summary = {
                "type": "connection_summary",
                "stream_type": stream_type,
                "chunks_received": stats.chunks_received,
                "bytes_received": stats.bytes_received,
                "lecture_id": lecture_id,
                "session_id": session_id,
                "started_at": start.isoformat(),
                "ended_at": datetime.now(timezone.utc).isoformat(),
            }
            await websocket.send_json(summary)
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


@app.websocket("/ws/video-keyframes")
async def video_keyframe_stream_endpoint(websocket: WebSocket) -> None:
    """Video keyframe detection endpoint - detects slides using SSIM."""
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


@app.websocket("/ws/audio")
async def audio_stream(websocket: WebSocket) -> None:
    """Audio recording endpoint - stores chunks for compilation."""
    stream_type = "audio"
    try:
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
