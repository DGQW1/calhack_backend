import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, Optional

from fastapi import WebSocket, WebSocketDisconnect

from claude_client import ClaudeConfig, TranscriptSummarizer
from deepgram_client import DeepgramConfig, DeepgramTranscriber

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
    deepgram_config = DeepgramConfig.from_env() if stream_type == "audio" else None
    deepgram: Optional[DeepgramTranscriber] = None
    last_client_metadata: Optional[Dict[str, Any]] = None
    summarizer: Optional[TranscriptSummarizer] = None

    if stream_type == "audio":
        claude_config = ClaudeConfig.from_env()
        if claude_config:
            summarizer = TranscriptSummarizer(claude_config)
            summarizer.start()

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
    finally:
        if deepgram:
            await deepgram.close()
        if summarizer:
            await summarizer.close()

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
