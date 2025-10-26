import json
import logging
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Deque, Dict, Optional

from fastapi import WebSocket, WebSocketDisconnect

from video_keyframes import VideoChunkProcessor


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
