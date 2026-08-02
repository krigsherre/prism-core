import asyncio
import time
from typing import List, Tuple, Any
from PIL import Image
import structlog
from core.ml.adapters import AbstractMLExtractor, ExtractorFactory

logger = structlog.get_logger(__name__)

class DynamicBatcher:
    """
    Continuous Dynamic Batching Engine for GPU Inference.
    Buffers incoming image crops and executes them in massive batches 
    to maximize GPU utilization.
    """
    def __init__(self, extractor_factory: ExtractorFactory, max_batch_size: int = 32, max_wait_ms: int = 50):
        self.extractor_factory = extractor_factory
        self.max_batch_size = max_batch_size
        self.max_wait_ms = max_wait_ms
        self.queue: asyncio.Queue[Tuple[Image.Image, asyncio.Future, str, str]] = asyncio.Queue()
        self._task = None

    def start(self):
        if self._task is None:
            self._task = asyncio.create_task(self._process_loop())
            logger.info("Started DynamicBatcher background engine.")

    async def stop(self):
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            logger.info("Stopped DynamicBatcher background engine.")

    async def enqueue(self, image: Image.Image, box_type: str = "TABLE", target_schema: Any = None) -> asyncio.Future:
        """
        Puts an image on the batch queue and returns an asyncio.Future.
        The caller can `await` this future to get the result once the batch processes.
        """
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        await self.queue.put((image, future, box_type, target_schema))
        return future

    async def _process_loop(self):
        while True:
            try:
                batch, box_types, target_schemas = await self._collect_batch()
                if batch:
                    await self._execute_batch(batch, box_types, target_schemas)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in dynamic batcher loop: {e}")

    async def _collect_batch(self) -> Tuple[List[Tuple[Image.Image, asyncio.Future]], List[str], List[Any]]:
        batch = []
        box_types = []
        target_schemas = []
        
        item = await self.queue.get()
        batch.append((item[0], item[1]))
        box_types.append(item[2])
        target_schemas.append(item[3])
        
        start_time = time.time()
        
        while len(batch) < self.max_batch_size:
            elapsed_ms = (time.time() - start_time) * 1000
            if elapsed_ms >= self.max_wait_ms:
                break
                
            try:
                timeout = (self.max_wait_ms - elapsed_ms) / 1000.0
                item = await asyncio.wait_for(self.queue.get(), timeout=max(timeout, 0.001))
                batch.append((item[0], item[1]))
                box_types.append(item[2])
                target_schemas.append(item[3])
            except (asyncio.TimeoutError, asyncio.QueueEmpty):
                break
                
        return batch, box_types, target_schemas

    async def _execute_batch(self, batch: List[Tuple[Image.Image, asyncio.Future]], box_types: List[str], target_schemas: List[Any]):
        """Executes the batch inference in a separate thread to not block the asyncio event loop."""
        images = [b[0] for b in batch]
        futures = [b[1] for b in batch]
        
        try:
            extractor = self.extractor_factory.get_extractor(box_types[0])
            
            if hasattr(extractor, 'extract_batch'):
                schema = target_schemas[0] if target_schemas else None
                results = await asyncio.to_thread(extractor.extract_batch, images, target_schema=schema)
            else:
                results = [await asyncio.to_thread(extractor.extract, img, target_schema=target_schemas[i]) for i, img in enumerate(images)]
                
            for future, result in zip(futures, results):
                if not future.done():
                    future.set_result(result)
        except Exception as e:
            logger.error(f"Batch execution failed: {e}")
            for future in futures:
                if not future.done():
                    future.set_exception(e)