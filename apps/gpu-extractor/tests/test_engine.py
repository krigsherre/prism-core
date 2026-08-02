import pytest
import asyncio
from unittest.mock import MagicMock, patch
from PIL import Image
from core.engine import DynamicBatcher

@pytest.fixture
def anyio_backend():
    return 'asyncio'

@pytest.mark.anyio
async def test_dynamic_batcher_start_stop():
    factory_mock = MagicMock()
    batcher = DynamicBatcher(extractor_factory=factory_mock, max_batch_size=2, max_wait_ms=10)
    
    assert batcher._task is None
    batcher.start()
    assert batcher._task is not None
    assert not batcher._task.done()
    
    await batcher.stop()
    assert batcher._task.done()

@pytest.mark.anyio
async def test_dynamic_batcher_enqueue():
    factory_mock = MagicMock()
    batcher = DynamicBatcher(extractor_factory=factory_mock, max_batch_size=2, max_wait_ms=10)
    
    img = Image.new("RGB", (10, 10))
    future = await batcher.enqueue(img, box_type="TABLE", target_schema=None)
    
    assert not future.done()
    assert batcher.queue.qsize() == 1
    
    item = await batcher.queue.get()
    assert item[0] == img
    assert item[1] == future
    assert item[2] == "TABLE"
    assert item[3] is None

@pytest.mark.anyio
async def test_dynamic_batcher_execute_batch_success():
    factory_mock = MagicMock()
    extractor_mock = MagicMock()
    extractor_mock.extract_batch.return_value = ["Extracted 1", "Extracted 2"]
    factory_mock.get_extractor.return_value = extractor_mock
    
    batcher = DynamicBatcher(extractor_factory=factory_mock, max_batch_size=2, max_wait_ms=10)
    batcher.start()
    
    img1 = Image.new("RGB", (10, 10))
    img2 = Image.new("RGB", (10, 10))
    
    future1 = await batcher.enqueue(img1)
    future2 = await batcher.enqueue(img2)
    
    result1 = await asyncio.wait_for(future1, timeout=1.0)
    result2 = await asyncio.wait_for(future2, timeout=1.0)
    
    assert result1 == "Extracted 1"
    assert result2 == "Extracted 2"
    
    extractor_mock.extract_batch.assert_called_once()
    
    await batcher.stop()

@pytest.mark.anyio
async def test_dynamic_batcher_execute_batch_fallback():
    factory_mock = MagicMock()
    extractor_mock = MagicMock()
    del extractor_mock.extract_batch
    extractor_mock.extract.side_effect = ["Extracted 1", "Extracted 2"]
    factory_mock.get_extractor.return_value = extractor_mock
    
    batcher = DynamicBatcher(extractor_factory=factory_mock, max_batch_size=2, max_wait_ms=10)
    batcher.start()
    
    img1 = Image.new("RGB", (10, 10))
    img2 = Image.new("RGB", (10, 10))
    
    future1 = await batcher.enqueue(img1)
    future2 = await batcher.enqueue(img2)
    
    result1 = await asyncio.wait_for(future1, timeout=1.0)
    result2 = await asyncio.wait_for(future2, timeout=1.0)
    
    assert result1 == "Extracted 1"
    assert result2 == "Extracted 2"
    
    assert extractor_mock.extract.call_count == 2
    
    await batcher.stop()

@pytest.mark.anyio
async def test_dynamic_batcher_execute_batch_error():
    factory_mock = MagicMock()
    extractor_mock = MagicMock()
    extractor_mock.extract_batch.side_effect = Exception("Test Error")
    factory_mock.get_extractor.return_value = extractor_mock
    
    batcher = DynamicBatcher(extractor_factory=factory_mock, max_batch_size=2, max_wait_ms=10)
    batcher.start()
    
    img = Image.new("RGB", (10, 10))
    future = await batcher.enqueue(img)
    
    with pytest.raises(Exception, match="Test Error"):
        await asyncio.wait_for(future, timeout=1.0)
        
    await batcher.stop()
