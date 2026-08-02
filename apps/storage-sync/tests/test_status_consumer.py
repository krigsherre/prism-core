import pytest
from kafka.consumers.status_consumer import StatusConsumer


def test_resolve_tenant_id_prefers_payload():
    payload = {"document_id": "doc-1", "tenant_id": "default-tenant"}
    assert StatusConsumer._resolve_tenant_id(payload, b"doc-1") == "default-tenant"


def test_resolve_tenant_id_ignores_document_id_key():
    payload = {"document_id": "doc-abc"}
    assert StatusConsumer._resolve_tenant_id(payload, b"doc-abc") == "default-tenant"


def test_resolve_tenant_id_uses_kafka_key_when_valid():
    payload = {"document_id": "doc-1"}
    assert StatusConsumer._resolve_tenant_id(payload, b"default-tenant") == "default-tenant"


def test_resolve_tenant_id_defaults_when_missing():
    payload = {"document_id": "doc-1"}
    assert StatusConsumer._resolve_tenant_id(payload, None) == "default-tenant"
