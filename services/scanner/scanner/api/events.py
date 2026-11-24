"""Tiny in-process pub/sub for per-batch Server-Sent Events."""
from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from typing import Any, AsyncIterator


class EventBus:
    def __init__(self) -> None:
        self._subs: dict[str, set[asyncio.Queue]] = defaultdict(set)

    def publish(self, batch_id: str, event: str, data: Any) -> None:
        payload = data.model_dump(mode="json") if hasattr(data, "model_dump") else data
        msg = f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
        for q in list(self._subs.get(batch_id, ())):
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                pass

    async def stream(self, batch_id: str) -> AsyncIterator[str]:
        q: asyncio.Queue = asyncio.Queue(maxsize=2000)
        self._subs[batch_id].add(q)
        try:
            yield "event: hello\ndata: {}\n\n"
            while True:
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=15)
                    yield msg
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            self._subs[batch_id].discard(q)
