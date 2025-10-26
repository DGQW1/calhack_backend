import asyncio
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Optional, Set


@dataclass(slots=True)
class SummaryUpdate:
    sequence: int
    summary: str
    created_at: datetime

    def to_message(self) -> dict[str, str | int]:
        data = asdict(self)
        data["created_at"] = self.created_at.isoformat()
        data["type"] = "summary"
        return data


class SummaryBroadcaster:
    def __init__(self) -> None:
        self._subscribers: Set[asyncio.Queue[SummaryUpdate]] = set()
        self._latest: Optional[SummaryUpdate] = None
        self._sequence = 0
        self._lock = asyncio.Lock()

    def register(self) -> asyncio.Queue[SummaryUpdate]:
        queue: asyncio.Queue[SummaryUpdate] = asyncio.Queue(maxsize=5)
        self._subscribers.add(queue)
        return queue

    def unregister(self, queue: asyncio.Queue[SummaryUpdate]) -> None:
        self._subscribers.discard(queue)

    @property
    def latest(self) -> Optional[SummaryUpdate]:
        return self._latest

    async def publish(self, summary: str) -> None:
        async with self._lock:
            self._sequence += 1
            update = SummaryUpdate(
                sequence=self._sequence,
                summary=summary,
                created_at=datetime.now(timezone.utc),
            )
            self._latest = update

            dead_subscribers: list[asyncio.Queue[SummaryUpdate]] = []
            for subscriber in self._subscribers:
                try:
                    subscriber.put_nowait(update)
                except asyncio.QueueFull:
                    dead_subscribers.append(subscriber)

            for subscriber in dead_subscribers:
                self._subscribers.discard(subscriber)


summary_broadcaster = SummaryBroadcaster()
