import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger("backend.streams")


@dataclass
class StreamStats:
    stream_type: str
    chunks_received: int = 0
    bytes_received: int = 0


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
    Returns aggregate stats when the connection closes gracefully.
    """
    stats = StreamStats(stream_type=stream_type)

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
