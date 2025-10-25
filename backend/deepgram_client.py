import asyncio
import json
import logging
import os
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlencode

import websockets
from websockets.client import WebSocketClientProtocol
from websockets.exceptions import ConnectionClosedError, ConnectionClosedOK

logger = logging.getLogger("backend.deepgram")

_missing_key_warning_emitted = False


def _env_int(name: str) -> Optional[int]:
    raw = os.getenv(name)
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        logger.warning("Environment variable %s=%r is not a valid integer.", name, raw)
        return None


@dataclass(slots=True)
class DeepgramConfig:
    api_key: str
    url: str = "wss://api.deepgram.com/v1/listen"
    model: Optional[str] = None
    tier: Optional[str] = None
    language: Optional[str] = None
    punctuation: bool = True
    sample_rate: Optional[int] = None
    encoding: Optional[str] = None
    interim_results: bool = False

    @classmethod
    def from_env(cls) -> Optional["DeepgramConfig"]:
        api_key = os.getenv("DEEPGRAM_API_KEY")
        if not api_key:
            global _missing_key_warning_emitted
            if not _missing_key_warning_emitted:
                logger.warning("DEEPGRAM_API_KEY is not set; live transcription is disabled.")
                _missing_key_warning_emitted = True
            return None

        punctuation = os.getenv("DEEPGRAM_PUNCTUATE", "true").lower() != "false"

        return cls(
            api_key=api_key,
            url=os.getenv("DEEPGRAM_REALTIME_URL", "wss://api.deepgram.com/v1/listen"),
            model=os.getenv("DEEPGRAM_MODEL"),
            tier=os.getenv("DEEPGRAM_TIER"),
            language=os.getenv("DEEPGRAM_LANGUAGE"),
            punctuation=punctuation,
            sample_rate=_env_int("DEEPGRAM_SAMPLE_RATE"),
            encoding=os.getenv("DEEPGRAM_ENCODING"),
            interim_results=os.getenv("DEEPGRAM_INTERIM_RESULTS", "false").lower() == "true",
        )


class DeepgramTranscriber:
    def __init__(self, config: DeepgramConfig):
        self._config = config
        self._socket: Optional[WebSocketClientProtocol] = None
        self._receiver_task: Optional[asyncio.Task[None]] = None
        self._closed = False

    async def connect(self, mime_type: Optional[str]) -> None:
        params = self._build_query_params(mime_type)
        url = f"{self._config.url}?{urlencode(params)}"

        logger.info("Connecting to Deepgram at %s", url)
        self._socket = await websockets.connect(
            url,
            extra_headers={"Authorization": f"Token {self._config.api_key}"},
        )

        request_id = None
        try:
            request_id = self._socket.response_headers.get("dg-request-id")
        except AttributeError:
            request_id = None
        if request_id:
            logger.info("Deepgram connection established (request id=%s)", request_id)

        self._receiver_task = asyncio.create_task(self._receive_loop(), name="deepgram-receiver")

    async def send_audio(self, chunk: bytes) -> None:
        if not self._socket or self._socket.closed:
            raise RuntimeError("Deepgram socket is not connected.")
        await self._socket.send(chunk)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True

        if self._socket and not self._socket.closed:
            try:
                await self._socket.send(json.dumps({"type": "CloseStream"}))
            except Exception:  # noqa: BLE001
                logger.debug("Failed to send CloseStream to Deepgram.", exc_info=True)

            await self._socket.close()

        if self._receiver_task:
            await self._receiver_task

    def _build_query_params(self, mime_type: Optional[str]) -> dict[str, str]:
        params: dict[str, str] = {}
        if self._config.punctuation:
            params["punctuate"] = "true"
        else:
            params["punctuate"] = "false"

        if self._config.model:
            params["model"] = self._config.model

        if self._config.tier:
            params["tier"] = self._config.tier

        if self._config.language:
            params["language"] = self._config.language

        encoding = self._config.encoding or self._infer_encoding(mime_type)
        if encoding:
            params["encoding"] = encoding

        if self._config.sample_rate:
            params["sample_rate"] = str(self._config.sample_rate)

        if self._config.interim_results:
            params["interim_results"] = "true"

        return params

    def _infer_encoding(self, mime_type: Optional[str]) -> Optional[str]:
        if not mime_type:
            return None
        mime_lower = mime_type.lower()
        if "opus" in mime_lower:
            return "opus"
        if "pcm" in mime_lower or "wav" in mime_lower or "linear16" in mime_lower:
            return "linear16"
        if "mp3" in mime_lower or "mpeg" in mime_lower:
            return "mp3"
        return None

    async def _receive_loop(self) -> None:
        if not self._socket:
            return

        try:
            async for message in self._socket:
                transcript = self._extract_transcript(message)
                if not transcript:
                    continue
                logger.info("[Deepgram] %s", transcript)
        except ConnectionClosedOK:
            logger.info("Deepgram connection closed cleanly.")
        except ConnectionClosedError as exc:
            logger.warning("Deepgram connection closed unexpectedly (%s - %s).", exc.code, exc.reason)
        except Exception:  # noqa: BLE001
            logger.exception("Error while receiving Deepgram messages.")

    def _extract_transcript(self, message: str) -> Optional[str]:
        try:
            payload = json.loads(message)
        except json.JSONDecodeError:
            logger.debug("Non-JSON message received from Deepgram: %s", message)
            return None

        is_final = payload.get("is_final") or payload.get("speech_final")
        if not is_final:
            # Emit interim transcripts only when explicitly requested.
            if not self._config.interim_results:
                return None

        alternatives = payload.get("channel", {}).get("alternatives", [])
        if not alternatives:
            return None
        transcript = alternatives[0].get("transcript")
        if not transcript:
            return None
        return transcript.strip() or None
