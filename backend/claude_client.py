import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Optional, Sequence

import httpx
from dotenv import load_dotenv

logger = logging.getLogger("backend.claude")

_missing_key_warning_emitted = False


DEFAULT_SYSTEM_PROMPT = (
    "You are a helpful assistant that produces concise rolling summaries of a live lecture. "
    "Blend the previous summary with the new transcript snippets to produce an updated, coherent summary that also includes contents from the previous summary. "
    "The summary should be organized and in details. "
    "You should not output anything irrelevant to the lecture itself. "
    "Do not address specific people, just summarize the content. "
    "Do not say something like the summary has been updated to reflect this new information. "
    "Do not add additional information that is not yet talked about by the lecturer "
)


load_dotenv()


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
class ClaudeConfig:
    api_key: str
    model: str = "claude-3-haiku-20240307"
    max_tokens: int = 400
    interval_seconds: int = 10
    temperature: float = 0.3
    system_prompt: str = DEFAULT_SYSTEM_PROMPT

    @classmethod
    def from_env(cls) -> Optional["ClaudeConfig"]:
        api_key = os.getenv("CLAUDE_API_KEY")
        if not api_key:
            global _missing_key_warning_emitted
            if not _missing_key_warning_emitted:
                logger.info("CLAUDE_API_KEY is not set; summarization is disabled.")
                _missing_key_warning_emitted = True
            return None

        interval = _env_int("CLAUDE_SUMMARY_INTERVAL_SECS") or 10
        max_tokens = _env_int("CLAUDE_MAX_TOKENS") or 400

        return cls(
            api_key=api_key,
            model=os.getenv("CLAUDE_MODEL", "claude-3-haiku-20240307"),
            max_tokens=max_tokens,
            interval_seconds=interval,
            temperature=float(os.getenv("CLAUDE_TEMPERATURE", "0.3")),
            system_prompt=os.getenv("CLAUDE_SYSTEM_PROMPT", DEFAULT_SYSTEM_PROMPT),
        )


class ClaudeClient:
    def __init__(self, config: ClaudeConfig) -> None:
        self._config = config
        self._client = httpx.AsyncClient(
            base_url="https://api.anthropic.com",
            timeout=httpx.Timeout(15.0, read=30.0),
        )

    async def summarize(self, transcripts: Sequence[str], previous_summary: Optional[str]) -> Optional[str]:
        if not transcripts:
            return None

        prompt_sections = [
            "You will be given new transcript excerpts from a live conversation.",
            "Update the running summary to reflect any new information.",
            "If nothing important happened, briefly confirm that the summary is unchanged.",
            "",
        ]

        if previous_summary:
            prompt_sections.append(f"Previous summary:\n{previous_summary}\n")
        else:
            prompt_sections.append("There is no previous summary. Create an initial summary.\n")

        joined_transcripts = "\n".join(transcripts)
        prompt_sections.append(f"New transcripts:\n{joined_transcripts}\n")
        prompt_sections.append("Return only the updated summary with no prefatory text.")

        payload = {
            "model": self._config.model,
            "max_tokens": self._config.max_tokens,
            "temperature": self._config.temperature,
            "system": self._config.system_prompt,
            "messages": [
                {
                    "role": "user",
                    "content": [{"type": "text", "text": "\n".join(prompt_sections)}],
                }
            ],
        }

        headers = {
            "x-api-key": self._config.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        try:
            response = await self._client.post("/v1/messages", json=payload, headers=headers)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("Claude API request failed: %s", exc)
            return None

        data = response.json()
        content = data.get("content")
        if not isinstance(content, list):
            logger.warning("Claude API response missing content: %s", data)
            return None

        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text")
                if isinstance(text, str) and text.strip():
                    return text.strip()

        logger.warning("Claude API response did not include text content: %s", data)
        return None

    async def close(self) -> None:
        await self._client.aclose()


class TranscriptSummarizer:
    def __init__(self, config: ClaudeConfig) -> None:
        self._config = config
        self._client = ClaudeClient(config)
        self._buffer: list[str] = []
        self._buffer_lock = asyncio.Lock()
        self._current_summary: Optional[str] = None
        self._task: Optional[asyncio.Task[None]] = None
        self._stop_event = asyncio.Event()

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="claude-summary-loop")

    async def handle_transcript(self, transcript: str) -> None:
        if not transcript:
            return
        async with self._buffer_lock:
            self._buffer.append(transcript)

    async def close(self) -> None:
        self._stop_event.set()
        if self._task:
            await self._task
            self._task = None
        await self._client.close()

    async def _run(self) -> None:
        try:
            while not self._stop_event.is_set():
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=self._config.interval_seconds)
                except asyncio.TimeoutError:
                    await self._emit_summary()
            # Flush any remaining transcripts on shutdown
            await self._emit_summary()
        except asyncio.CancelledError:
            await self._emit_summary()
            raise

    async def _emit_summary(self) -> None:
        async with self._buffer_lock:
            if not self._buffer:
                return
            transcripts = list(self._buffer)
            self._buffer.clear()

        summary = await self._client.summarize(transcripts, self._current_summary)
        if summary:
            self._current_summary = summary
            logger.info("[Claude Summary] %s", summary)
