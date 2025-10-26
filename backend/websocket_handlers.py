import asyncio
import json
import logging
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Deque, Dict, Optional

from fastapi import WebSocket, WebSocketDisconnect

from video_storage import video_storage
from video_keyframes import VideoChunkProcessor
from claude_client import ClaudeConfig, TranscriptSummarizer
from deepgram_client import DeepgramConfig, DeepgramTranscriber
from summary_broadcaster import summary_broadcaster

logger = logging.getLogger("backend.streams")


# Global session manager for coordinating video and audio streams
class SessionManager:
    def __init__(self):
        self.active_sessions: Dict[str, Dict[str, bool]] = {}  # session_id -> {video: bool, audio: bool}
        self.session_lock = asyncio.Lock()

    async def get_or_create_session(self, stream_type: str) -> str:
        """Get existing session or create new one for the stream type."""
        async with self.session_lock:
            # Look for an existing session that doesn't have this stream type yet
            for session_id, streams in self.active_sessions.items():
                if not streams.get(stream_type, False):
                    streams[stream_type] = True
                    logger.info(f"Reusing session {session_id} for {stream_type} stream")
                    return session_id

            # Create new session if none found
            session_id = video_storage.create_session()
            self.active_sessions[session_id] = {stream_type: True}
            logger.info(f"Created new session {session_id} for {stream_type} stream")
            return session_id

    async def mark_stream_disconnected(self, session_id: str, stream_type: str):
        """Mark a stream as disconnected and finalize session if both streams are done."""
        async with self.session_lock:
            if session_id in self.active_sessions:
                self.active_sessions[session_id][stream_type] = False

                # Check if both streams are disconnected
                streams = self.active_sessions[session_id]
                if not streams.get('video', False) and not streams.get('audio', False):
                    # Both streams disconnected, finalize the session
                    session = video_storage.get_session(session_id)
                    if session:
                        try:
                            await session.finalize()
                            logger.info(f"Finalized session {session_id} (both streams disconnected)")
                        except Exception as e:
                            logger.error(f"Error finalizing session {session_id}: {e}")

                    # Remove from active sessions
                    del self.active_sessions[session_id]


# Global session manager instance
session_manager = SessionManager()


@dataclass
class StreamStats:
    stream_type: str
    chunks_received: int = 0
    bytes_received: int = 0
    session_id: Optional[str] = None


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _extract_client_metadata(raw: str) -> Optional[Dict[str, Any]]:
    """
    Attempt to parse JSON metadata sent as text control messages.
    Returns None if parsing fails or value is not a JSON object.
    """
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if isinstance(payload, dict):
        return payload
    return None


async def handle_stream(websocket: WebSocket, stream_type: str) -> StreamStats:
    """
    Consume messages from a WebSocket stream, logging metadata for each chunk.
    Stores video/audio chunks for later compilation.
    Returns aggregate stats when the connection closes gracefully.
    """
    stats = StreamStats(stream_type=stream_type)
    deepgram_config = DeepgramConfig.from_env() if stream_type == "audio" else None
    deepgram: Optional[DeepgramTranscriber] = None
    last_client_metadata: Optional[Dict[str, Any]] = None
    summarizer: Optional[TranscriptSummarizer] = None

    if stream_type == "audio":
        claude_config = ClaudeConfig.from_env()
        if claude_config:
            summarizer = TranscriptSummarizer(claude_config, on_summary=summary_broadcaster.publish)
            summarizer.start()

    # Get or create a shared recording session using the session manager
    session_id = await session_manager.get_or_create_session(stream_type)
    stats.session_id = session_id
    session = video_storage.get_session(session_id)

    logger.info(f"Using session {session_id} for {stream_type} stream")

    try:
        while True:
            message = await websocket.receive()
            message_type = message.get("type")

            if message_type == "websocket.disconnect":
                raise WebSocketDisconnect(code=message.get("code", 1000))

            chunk_bytes = message.get("bytes")
            chunk_text = message.get("text")

            metadata: Dict[str, Any] = {
                "timestamp": _utc_timestamp(),
                "stream_type": stream_type,
                "session_id": session_id,
            }

            if chunk_bytes is not None:
                chunk_size = len(chunk_bytes)
                metadata.update(
                    {
                        "message_format": "binary",
                        "chunk_size_bytes": chunk_size,
                    }
                )
                stats.bytes_received += chunk_size

                # Store chunks for video compilation
                if session:
                    if stream_type == "video":
                        await session.add_video_chunk(chunk_bytes, metadata)
                if stream_type == "audio":
                    if deepgram_config and deepgram is None:
                        transcript_handler = summarizer.handle_transcript if summarizer else None
                        deepgram = await _open_deepgram_transcriber(
                            deepgram_config, last_client_metadata, transcript_handler
                        )
                        if deepgram is None:
                            deepgram_config = None

                    if deepgram:
                        try:
                            await deepgram.send_audio(chunk_bytes)
                        except Exception:  # noqa: BLE001
                            logger.exception("Failed to forward audio chunk to Deepgram.")
                            try:
                                await deepgram.close()
                            finally:
                                deepgram = None

            elif chunk_text is not None:
                metadata["message_format"] = "text"
                metadata["chunk_size_bytes"] = len(chunk_text.encode("utf-8"))
                client_meta = _extract_client_metadata(chunk_text)
                if client_meta:
                    metadata["client_metadata"] = client_meta
                    if stream_type == "audio":
                        last_client_metadata = client_meta
            else:
                metadata["message_format"] = "unknown"

            stats.chunks_received += 1
            
            logger.debug("%s", json.dumps(metadata, ensure_ascii=False))
        logger.info("%s", json.dumps(metadata, ensure_ascii=False))
        return stats
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for {stream_type} stream, session {session_id}")
        raise
    except Exception as e:
        logger.error(f"Error in {stream_type} stream handling: {e}")
        raise
    finally:
        if deepgram:
            await deepgram.close()
        if summarizer:
          await summarizer.close()
        # Mark stream as disconnected and let session manager handle finalization
        await session_manager.mark_stream_disconnected(session_id, stream_type)
                  
async def handle_video_keyframe_stream(
    websocket: WebSocket,
    processor: VideoChunkProcessor,
    stream_type: str = "video",
) -> StreamStats:
    stats = StreamStats(stream_type=stream_type)
    metadata_queue: Deque[Dict[str, Any]] = deque()

    try:
        while True:
            try:
                message = await websocket.receive()
            except Exception as e:
                logger.error(f"[{stream_type}] Error receiving message from websocket: {e}", exc_info=True)
                break

            message_type = message.get("type")

            if message_type == "websocket.disconnect":
                logger.info(f"[{stream_type}] Received websocket.disconnect message")
                break

            chunk_bytes = message.get("bytes")
            chunk_text = message.get("text")

            stats.chunks_received += 1

            if chunk_text is not None:
                client_meta = _extract_client_metadata(chunk_text)
                metadata = {
                    "timestamp": _utc_timestamp(),
                    "stream_type": stream_type,
                    "message_format": "text",
                    "chunk_size_bytes": len(chunk_text.encode("utf-8")),
                }
                if client_meta:
                    metadata["client_metadata"] = client_meta
                    metadata_queue.append(client_meta)
                logger.info("%s", json.dumps(metadata, ensure_ascii=False))
                continue

            if chunk_bytes is None:
                logger.info(
                    "%s",
                    json.dumps(
                        {
                            "timestamp": _utc_timestamp(),
                            "stream_type": stream_type,
                            "message_format": "unknown",
                        },
                        ensure_ascii=False,
                    ),
                )
                continue

            stats.bytes_received += len(chunk_bytes)

            metadata = metadata_queue.popleft() if metadata_queue else {}
            sequence = metadata.get('sequence', 'unknown')

            logger.info(f"[{stream_type}] Processing chunk sequence={sequence}, bytes={len(chunk_bytes)}")

            # Process chunk with error handling to prevent stream interruption
            try:
                await processor.process_chunk(chunk_bytes, metadata, websocket)
                logger.info(f"[{stream_type}] Successfully processed chunk sequence={sequence}")
            except Exception as e:
                logger.error(f"Failed to process video chunk (sequence {sequence}): {e}", exc_info=True)
                # Continue processing other chunks even if this one fails
                continue
    except WebSocketDisconnect:
        logger.info(f"[{stream_type}] WebSocket disconnected normally")
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception(f"[{stream_type}] Unexpected error in video keyframe stream handler: %s", exc)
        raise
    finally:
        logger.info(f"[{stream_type}] Finalizing processor")
        await processor.finalize(websocket)

    return stats
async def _open_deepgram_transcriber(
    config: DeepgramConfig,
    client_metadata: Optional[Dict[str, Any]],
    transcript_callback: Optional[Callable[[str], Awaitable[None] | None]],
) -> Optional[DeepgramTranscriber]:
    transcriber = DeepgramTranscriber(config, on_transcript=transcript_callback)
    mime_type = None
    if client_metadata:
        mime_type = client_metadata.get("mimeType") or client_metadata.get("mime_type")
    try:
        await transcriber.connect(mime_type=mime_type)
        return transcriber
    except Exception:  # noqa: BLE001
        logger.exception("Unable to establish Deepgram connection.")
        await transcriber.close()
        return None
