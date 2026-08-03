"""Abstract Base Consumer Worker for background queue and stream processors."""
from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import Any, Optional
import structlog

logger = structlog.get_logger(__name__)


class BaseConsumerWorker(ABC):
    """Abstract Base Class establishing common async lifecycle and loop management."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.running: bool = False
        self._task: Optional[asyncio.Task] = None

    @abstractmethod
    async def start(self) -> None:
        """Initialize connections and begin background processing."""
        pass

    @abstractmethod
    async def stop(self) -> None:
        """Gracefully terminate processing loops and close client connections."""
        pass

    @abstractmethod
    async def process_message(self, message: Any) -> None:
        """Process a single unit of work or message payload."""
        pass
