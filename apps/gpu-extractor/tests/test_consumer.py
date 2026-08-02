import asyncio
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from broker.consumer import KafkaConsumerService
import proto.prism.v1.events_pb2 as events_pb2

@pytest.fixture
def anyio_backend():
    return 'asyncio'

@pytest.fixture
def mock_extraction_service():
    service = MagicMock()
    service.s3 = MagicMock()
    service.preprocessor = MagicMock()
    service.process_document = AsyncMock()
    return service

@pytest.mark.anyio
@patch("broker.consumer.AIOKafkaConsumer")
@patch("broker.consumer.AIOKafkaProducer")
async def test_kafka_consumer_start_stop(mock_producer_cls, mock_consumer_cls, mock_extraction_service):
    mock_consumer_instance = AsyncMock()
    mock_consumer_instance.start = AsyncMock()
    mock_consumer_instance.stop = AsyncMock()
    mock_consumer_cls.return_value = mock_consumer_instance
    
    mock_producer_instance = AsyncMock()
    mock_producer_instance.start = AsyncMock()
    mock_producer_instance.stop = AsyncMock()
    mock_producer_cls.return_value = mock_producer_instance
    
    service = KafkaConsumerService(extraction_service=mock_extraction_service)
    
    await service.start()
    
    assert service.consumer is mock_consumer_instance
    assert service.producer is mock_producer_instance
    mock_consumer_instance.start.assert_called_once()
    mock_producer_instance.start.assert_called_once()
    
    assert service._task is not None
    assert not service._task.done()
    
    await service.stop()
    try:
        await service._task
    except asyncio.CancelledError:
        pass
    mock_consumer_instance.stop.assert_called_once()
    mock_producer_instance.stop.assert_called_once()
    assert service._task.cancelled() or service._task.done()

@pytest.mark.anyio
@patch("broker.consumer.AIOKafkaConsumer")
@patch("broker.consumer.AIOKafkaProducer")
@patch("broker.consumer.tempfile")
@patch("broker.consumer.os")
async def test_kafka_consumer_orchestrator_mode(mock_os, mock_tempfile, mock_producer_cls, mock_consumer_cls, mock_extraction_service):
    mock_tempfile.mkstemp.return_value = (1, "/tmp/mock.tmp")
    mock_os.path.splitext.return_value = ("test", ".pdf")
    mock_os.path.basename.return_value = "test.pdf"
    
    mock_producer_instance = AsyncMock()
    mock_producer_instance.send_and_wait = AsyncMock()
    mock_producer_cls.return_value = mock_producer_instance
    
    mock_extraction_service.preprocessor.preprocess.return_value = ("/tmp/norm.pdf", "PDF_LAYOUT")
    
    service = KafkaConsumerService(extraction_service=mock_extraction_service)
    service.producer = mock_producer_instance
    
    event = events_pb2.IngestEvent()
    event.tenant_id = "tenant-123"
    event.s3_uri = "s3://bucket/path/test.pdf"
    
    with patch("broker.consumer.SmartChunker") as mock_chunker:
        mock_chunker.calculate_chunks.return_value = [
            {"start_page": 0, "end_page": 2, "injected_context": ""},
            {"start_page": 3, "end_page": 5, "injected_context": "Header"}
        ]
        
        await service._handle_orchestrator_mode(event, "test", {})
        
        mock_chunker.calculate_chunks.assert_called_once_with("/tmp/norm.pdf")
        assert mock_producer_instance.send_and_wait.call_count == 2
        
        call_args = mock_producer_instance.send_and_wait.call_args_list[0]
        assert call_args[0][0] == "gpu_processing_queue"
        assert call_args[1]["key"] == b"tenant-123"

        # Fan-out must stamp chunk_index / chunk_total for cross-chunk assembly
        sub = events_pb2.IngestEvent()
        sub.ParseFromString(call_args[0][1])
        assert sub.metadata["chunk_index"] == "0"
        assert sub.metadata["chunk_total"] == "2"
        assert sub.metadata["start_page"] == "0"
        assert sub.metadata["end_page"] == "2"

        sub2 = events_pb2.IngestEvent()
        sub2.ParseFromString(mock_producer_instance.send_and_wait.call_args_list[1][0][1])
        assert sub2.metadata["chunk_index"] == "1"
        assert sub2.metadata["chunk_total"] == "2"
        assert sub2.metadata.get("injected_context") == "Header"

@pytest.mark.anyio
@patch("broker.consumer.AIOKafkaProducer")
async def test_kafka_consumer_worker_mode(mock_producer_cls, mock_extraction_service):
    mock_producer_instance = AsyncMock()
    mock_producer_instance.send_and_wait = AsyncMock()
    
    mock_dom = MagicMock()
    mock_dom.SerializeToString.return_value = b"MOCK_DOM"
    mock_extraction_service.process_document.return_value = mock_dom
    
    service = KafkaConsumerService(extraction_service=mock_extraction_service)
    service.producer = mock_producer_instance
    
    event = events_pb2.IngestEvent()
    event.tenant_id = "tenant-123"
    event.s3_uri = "s3://bucket/test.pdf"
    
    metadata = {
        "start_page": "0",
        "end_page": "5",
        "injected_context": "test context"
    }
    
    await service._handle_worker_mode(event, "test", metadata)
    
    mock_extraction_service.process_document.assert_called_once_with(
        "s3://bucket/test.pdf",
        document_id="test",
        metadata=metadata,
        start_page=0,
        end_page=5,
        injected_context="test context"
    )
    
    mock_producer_instance.send_and_wait.assert_called_once_with(
        "parsed_documents",
        b"MOCK_DOM",
        key=b"tenant-123"
    )

@pytest.mark.anyio
@patch("broker.consumer.AIOKafkaProducer")
async def test_kafka_consumer_process_message_error(mock_producer_cls, mock_extraction_service):
    mock_producer_instance = AsyncMock()
    mock_producer_instance.send_and_wait = AsyncMock()
    
    service = KafkaConsumerService(extraction_service=mock_extraction_service)
    service.producer = mock_producer_instance
    
    with patch.object(service, "_handle_worker_mode", side_effect=Exception("Test error")):
        event = events_pb2.IngestEvent()
        event.tenant_id = "tenant-456"
        event.metadata["start_page"] = "0"
        
        class MockMsg:
            value = event.SerializeToString()
            
        await service._process_message(MockMsg())

        mock_producer_instance.send_and_wait.assert_any_call(
            "gpu_processing_dlq",
            MockMsg.value,
            key=b"tenant-456"
        )
