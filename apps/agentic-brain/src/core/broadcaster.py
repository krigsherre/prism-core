import asyncio
import structlog
from typing import Set

logger = structlog.get_logger(__name__)

class Broadcaster:
    def __init__(self):
        self.queues: Set[asyncio.Queue] = set()
    
    def subscribe(self) -> asyncio.Queue:
        q = asyncio.Queue()
        self.queues.add(q)
        return q
    
    def unsubscribe(self, q: asyncio.Queue):
        self.queues.discard(q)
        
    async def broadcast(self, message: str):
        for q in list(self.queues):
            try:
                q.put_nowait(message)
            except asyncio.QueueFull:
                pass

status_broadcaster = Broadcaster()
