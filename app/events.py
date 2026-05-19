import asyncio
from typing import AsyncIterator


class EventBroadcaster:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[str]] = set()

    async def publish(self, message: str) -> None:
        for queue in list(self._subscribers):
            await queue.put(message)

    async def subscribe(self) -> AsyncIterator[str]:
        queue: asyncio.Queue[str] = asyncio.Queue()
        self._subscribers.add(queue)
        try:
            while True:
                yield await queue.get()
        finally:
            self._subscribers.discard(queue)


broadcaster = EventBroadcaster()
