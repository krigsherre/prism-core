import pytest
from unittest.mock import MagicMock
from kafka.consumers.system_dlq import SystemDlqConsumer


def test_system_dlq_consumer_instantiation():
    mock_session_factory = MagicMock()
    consumer = SystemDlqConsumer(mock_session_factory)
    assert consumer.session_factory == mock_session_factory
    assert consumer.topics == ["system_dlq"]

    kafka_consumer = consumer._create_consumer()
    assert kafka_consumer is not None
