from core.alignment import WaterfallAlignmentStrategy
import pytest
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch
from kafka.consumers import SchemaCDCConsumer, DictionaryCDCConsumer, RawTableDOMConsumer

@pytest.fixture
def mock_strategy():
    strategy = MagicMock(spec=WaterfallAlignmentStrategy)
    strategy.align = AsyncMock(return_value=([{"col1": "val1"}], [{}], "MAPPED", "target1", []))
    strategy.align_with_reflexion = AsyncMock(
        return_value=([{"col1": "val1"}], [{"row_status": "MAPPED"}], "MAPPED", "target1", [], {"attempts": 1, "exhausted": False})
    )
    return strategy

@pytest.fixture
def mock_consumer_class():
    with patch("kafka.consumers.AIOKafkaConsumer") as mock_cls:
        yield mock_cls

@pytest.fixture
def mock_producer_class():
    with patch("kafka.consumers.AIOKafkaProducer") as mock_cls:
        yield mock_cls

@pytest.mark.asyncio
async def test_schema_cdc_consumer_creates_updates(mock_strategy, mock_consumer_class):
    consumer_instance = mock_consumer_class.return_value
    consumer_instance.start = AsyncMock()
    consumer_instance.stop = AsyncMock()
    consumer_instance.commit = AsyncMock()
    
    payload = {
        "payload": {
            "op": "c",
            "after": {
                "target_table": "new_table",
                "columns": {"colA": "str"}
            }
        }
    }
    
    msg_mock = MagicMock()
    msg_mock.value = json.dumps(payload).encode("utf-8")
    
    consumer_instance.__aiter__.return_value = [msg_mock]
    
    consumer = SchemaCDCConsumer(mock_strategy)
    await consumer.run()
    
    mock_strategy.update_schema.assert_called_once_with("new_table", {"colA": "str"})

@pytest.mark.asyncio
async def test_dictionary_cdc_consumer(mock_strategy, mock_consumer_class):
    consumer_instance = mock_consumer_class.return_value
    consumer_instance.start = AsyncMock()
    consumer_instance.stop = AsyncMock()
    consumer_instance.commit = AsyncMock()
    
    payload = {
        "payload": {
            "op": "u",
            "after": {
                "tenant_id": "tenant1",
                "target_table": "table1",
                "raw_label": "raw1",
                "mapped_column": "map1"
            }
        }
    }
    
    msg_mock = MagicMock()
    msg_mock.value = json.dumps(payload).encode("utf-8")
    
    consumer_instance.__aiter__.return_value = [msg_mock]
    
    consumer = DictionaryCDCConsumer(mock_strategy)
    await consumer.run()
    
    mock_strategy.update_synonym.assert_called_once_with("tenant1", "table1", "raw1", "map1")

@pytest.mark.asyncio
async def test_raw_table_dom_consumer(mock_strategy, mock_consumer_class, mock_producer_class):
    consumer_instance = mock_consumer_class.return_value
    consumer_instance.start = AsyncMock()
    consumer_instance.stop = AsyncMock()
    consumer_instance.commit = AsyncMock()
    
    producer_instance = mock_producer_class.return_value
    producer_instance.start = AsyncMock()
    producer_instance.stop = AsyncMock()
    producer_instance.send_and_wait = AsyncMock()
    
    payload = {
        "document_id": "doc1",
        "tenant_id": "tenant1",
        "target_table": "",
        "extracted_data": {"raw1": "val1"}
    }
    
    msg_mock = MagicMock()
    msg_mock.value = json.dumps(payload).encode("utf-8")
    
    consumer_instance.__aiter__.return_value = [msg_mock]
    
    consumer = RawTableDOMConsumer(mock_strategy)
    await consumer.run()
    
    mock_strategy.align_with_reflexion.assert_called()
    topics = [c.args[0] for c in producer_instance.send_and_wait.call_args_list]
    assert "aligned_sql_payloads" in topics
    assert "schema_drift_anomalies" not in topics

@pytest.mark.asyncio
async def test_raw_table_dom_dlq_routing(mock_strategy, mock_consumer_class, mock_producer_class):
    consumer_instance = mock_consumer_class.return_value
    consumer_instance.start = AsyncMock()
    consumer_instance.stop = AsyncMock()
    consumer_instance.commit = AsyncMock()
    
    producer_instance = mock_producer_class.return_value
    producer_instance.start = AsyncMock()
    producer_instance.stop = AsyncMock()
    producer_instance.send_and_wait = AsyncMock()
    
    mock_strategy.align_with_reflexion = AsyncMock(side_effect=Exception("Critical LLM Failure"))
    
    payload = {
        "document_id": "doc1",
        "tenant_id": "tenant1",
        "target_table": "",
        "extracted_data": {"raw1": "val1"}
    }
    
    msg_mock = MagicMock()
    msg_mock.value = json.dumps(payload).encode("utf-8")
    
    consumer_instance.__aiter__.return_value = [msg_mock]
    
    consumer = RawTableDOMConsumer(mock_strategy)
    await consumer.run()

    topics = [c.args[0] for c in producer_instance.send_and_wait.call_args_list]
    assert "schema_aligner_dlq" in topics

@pytest.mark.asyncio
async def test_raw_table_dom_anomaly_publishing(mock_strategy, mock_consumer_class, mock_producer_class):
    consumer_instance = mock_consumer_class.return_value
    consumer_instance.start = AsyncMock()
    consumer_instance.stop = AsyncMock()
    consumer_instance.commit = AsyncMock()
    
    producer_instance = mock_producer_class.return_value
    producer_instance.start = AsyncMock()
    producer_instance.stop = AsyncMock()
    producer_instance.send_and_wait = AsyncMock()
    
    mock_strategy.align_with_reflexion = AsyncMock(
        return_value=([{"col1": "val1"}], [{"unknown": "val2", "row_status": "NEEDS_REVIEW"}], "NEEDS_REVIEW", "target1", ["unknown"], {"attempts": 1, "exhausted": False})
    )
    
    payload = {
        "document_id": "doc1",
        "tenant_id": "tenant1",
        "target_table": "",
        "extracted_data": {"unknown": "val2"}
    }
    
    msg_mock = MagicMock()
    msg_mock.value = json.dumps(payload).encode("utf-8")
    
    consumer_instance.__aiter__.return_value = [msg_mock]
    
    with patch("kafka.consumers.generate_hitl_review", new_callable=AsyncMock) as mock_hitl:
        mock_hitl.return_value = {
            "summary": "Review needed",
            "issues": [{"row_index": 0, "column": "unknown", "current_value": "val2", "expected_or_issue": "drift", "suggested_value": None, "question": "Map unknown?"}],
            "proposed_extracted_data": {"unknown": "val2"},
        }
        consumer = RawTableDOMConsumer(mock_strategy)
        await consumer.run()

    topics = [c.args[0] for c in producer_instance.send_and_wait.call_args_list]
    assert "aligned_sql_payloads" in topics
    assert "schema_drift_anomalies" in topics

    anomaly_payload = None
    for c in producer_instance.send_and_wait.call_args_list:
        if c.args[0] != "schema_drift_anomalies":
            continue
        raw = c.kwargs.get("value")
        if raw is None:
            # positional: send_and_wait(topic, value) unlikely; prefer kwargs
            for a in c.args[1:]:
                if isinstance(a, (bytes, str)):
                    raw = a
                    break
        anomaly_payload = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
        break
    assert anomaly_payload is not None
    assert "hitl_review" in anomaly_payload
    assert anomaly_payload["hitl_review"]["summary"] == "Review needed"
