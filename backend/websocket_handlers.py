import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import WebSocket, WebSocketDisconnect

from video_storage import video_storage

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

logger = logging.getLogger("backend.streams")


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
                    elif stream_type == "audio":
                        await session.add_audio_chunk(chunk_bytes, metadata)
                        
            elif chunk_text is not None:
                metadata["message_format"] = "text"
                metadata["chunk_size_bytes"] = len(chunk_text.encode("utf-8"))
                client_meta = _extract_client_metadata(chunk_text)
                if client_meta:
                    metadata["client_metadata"] = client_meta
            else:
                metadata["message_format"] = "unknown"

            stats.chunks_received += 1

            logger.info("%s", json.dumps(metadata, ensure_ascii=False))
            
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for {stream_type} stream, session {session_id}")
        raise
    except Exception as e:
        logger.error(f"Error in {stream_type} stream handling: {e}")
        raise
    finally:
        # Mark stream as disconnected and let session manager handle finalization
        await session_manager.mark_stream_disconnected(session_id, stream_type)
