from abc import ABC, abstractmethod
import asyncio
import inspect
from typing import List, Optional
import structlog
from config.settings import settings
from tenacity import retry, stop_after_attempt, wait_exponential
from opentelemetry import trace
from opentelemetry.propagate import extract

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer(__name__)


class BaseKafkaConsumer(ABC):
    """
    Abstract Base Class for Kafka consumers employing the Template Method Pattern.
    Encapsulates connection lifecycle, message polling loop, OpenTelemetry span tracing,
    error logging, and graceful resource teardown.
    """

    def __init__(
        self,
        topics: List[str],
        group_id: str,
        auto_offset_reset: str = "earliest",
        enable_auto_commit: bool = True,
        needs_producer: bool = False,
    ) -> None:
        self.topics = topics
        self.group_id = group_id
        self.auto_offset_reset = auto_offset_reset
        self.enable_auto_commit = enable_auto_commit
        self.needs_producer = needs_producer
        self._consumer = None
        self._producer = None

    @abstractmethod
    def _create_consumer(self):
        """Subclass creates Kafka consumer using module-level AIOKafkaConsumer."""
        pass

    def _create_producer(self):
        """Subclass creates Kafka producer if required using module-level AIOKafkaProducer."""
        return None

    @retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, min=2, max=10), reraise=True)
    async def _connect_kafka(self) -> None:
        """Establish connection to Kafka brokers with exponential backoff retry."""
        if self._consumer and hasattr(self._consumer, "start"):
            res = self._consumer.start()
            if inspect.isawaitable(res):
                await res
        if self._producer and self.needs_producer and hasattr(self._producer, "start"):
            res = self._producer.start()
            if inspect.isawaitable(res):
                await res

    async def start(self) -> None:
        """Initialize consumer and producer clients."""
        if self._consumer is None:
            self._consumer = self._create_consumer()
        if self.needs_producer and self._producer is None:
            self._producer = self._create_producer()

        await self._connect_kafka()

    async def stop(self) -> None:
        """Gracefully shut down consumer and producer connections."""
        if self._consumer and hasattr(self._consumer, "stop"):
            try:
                res = self._consumer.stop()
                if inspect.isawaitable(res):
                    await res
            except Exception as e:
                logger.error(f"Error stopping consumer for {self.__class__.__name__}", error=str(e))
        if self._producer and hasattr(self._producer, "stop"):
            try:
                res = self._producer.stop()
                if inspect.isawaitable(res):
                    await res
            except Exception as e:
                logger.error(f"Error stopping producer for {self.__class__.__name__}", error=str(e))

    async def run(self) -> None:
        """
        Template method executing the main consumer lifecycle.
        Initializes Kafka clients, loops over incoming messages, delegates to subclass `_process_message`,
        and ensures proper cleanup on termination or failure.
        """
        try:
            await self.start()
            logger.info(f"{self.__class__.__name__} started...", topics=self.topics, group_id=self.group_id)
            async for msg in self._consumer:
                await self._trace_and_process(msg)
        except asyncio.CancelledError:
            logger.info(f"{self.__class__.__name__} cancelled")
        except Exception as e:
            logger.error(f"{self.__class__.__name__} failed unexpectedly", error=str(e))
        finally:
            await self.stop()

    async def _trace_and_process(self, msg) -> None:
        """Extract OpenTelemetry trace context and delegate message to subclass."""
        raw_headers = getattr(msg, "headers", None) or []
        headers_dict = {k: v.decode("utf-8") if isinstance(v, bytes) else v for k, v in raw_headers}
        ctx = extract(headers_dict)
        span_name = f"process_{self.__class__.__name__.lower()}"

        with tracer.start_as_current_span(span_name, context=ctx):
            await self._process_message(msg)

    @abstractmethod
    async def _process_message(self, msg) -> None:
        """Subclasses must implement message handling logic."""
        pass
