"""Tests for cross-chunk DOM assembly and table stitching."""
import json
import time
from unittest.mock import AsyncMock, MagicMock
import sys

import pytest

sys.modules["aiokafka"] = MagicMock()

from kafka.consumers.bifurcation import DocumentRouter
from kafka.consumers.chunk_assembler import ChunkDOMAssembler, assemble_chunk_doms
from proto.prism.v1 import dom_pb2


@pytest.fixture
def router():
    r = DocumentRouter(AsyncMock(), AsyncMock())
    r._real_embedding = AsyncMock(return_value=[0.1] * 384)
    return r


def _table(page: int, headers, rows, node_id: str = "t"):
    node = dom_pb2.Node(
        id=node_id,
        type=dom_pb2.NODE_TYPE_TABLE,
        content=json.dumps({"headers": headers, "rows": rows}),
    )
    node.provenance.page_number = page
    node.provenance.bounding_box.extend([0.0, 10.0, 100.0, 200.0])
    return node


def test_assemble_orders_nodes_by_page():
    d0 = dom_pb2.DocumentDOM(document_id="doc-1")
    d0.metadata["chunk_index"] = "0"
    d0.metadata["chunk_total"] = "2"
    n0 = d0.nodes.add()
    n0.id = "late"
    n0.type = dom_pb2.NODE_TYPE_TEXT
    n0.content = "page 20 text"
    n0.provenance.page_number = 20

    d1 = dom_pb2.DocumentDOM(document_id="doc-1")
    d1.metadata["chunk_index"] = "1"
    d1.metadata["chunk_total"] = "2"
    n1 = d1.nodes.add()
    n1.id = "early"
    n1.type = dom_pb2.NODE_TYPE_TEXT
    n1.content = "page 2 text"
    n1.provenance.page_number = 2

    # Intentionally out of chunk order in the dict
    merged = assemble_chunk_doms("doc-1", {1: d1, 0: d0})
    assert merged.metadata["chunk_assembled"] == "true"
    assert [n.id for n in merged.nodes] == ["early", "late"]


def test_assembler_buffers_until_complete():
    asm = ChunkDOMAssembler(timeout_seconds=60)
    d0 = dom_pb2.DocumentDOM(document_id="doc-x")
    d0.metadata["chunk_index"] = "0"
    d0.metadata["chunk_total"] = "2"
    d0.metadata["original_filename"] = "a.pdf"
    assert asm.add("t1", d0) is None

    d1 = dom_pb2.DocumentDOM(document_id="doc-x")
    d1.metadata["chunk_index"] = "1"
    d1.metadata["chunk_total"] = "2"
    ready = asm.add("t1", d1)
    assert ready is not None
    assert ready.metadata["chunks_received"] == "2"


def test_assembler_passthrough_without_chunk_meta():
    asm = ChunkDOMAssembler()
    dom = dom_pb2.DocumentDOM(document_id="solo")
    node = dom.nodes.add()
    node.id = "n1"
    node.type = dom_pb2.NODE_TYPE_TEXT
    node.content = "hi"
    assert asm.add("t1", dom) is dom


def test_assembler_timeout_flush():
    asm = ChunkDOMAssembler(timeout_seconds=0.01)
    d0 = dom_pb2.DocumentDOM(document_id="doc-slow")
    d0.metadata["chunk_index"] = "0"
    d0.metadata["chunk_total"] = "3"
    assert asm.add("t1", d0) is None
    time.sleep(0.02)
    flushed = asm.flush_expired()
    assert len(flushed) == 1
    assert flushed[0][0] == "t1"
    assert flushed[0][1].metadata["chunks_received"] == "1"


def test_cross_chunk_stitch_skips_injected_context(router):
    headers = ["Total assets", "Cash"]
    t1 = _table(10, headers, [["100", "20"]], "t-a")
    injected = dom_pb2.Node(
        id="ctx",
        type=dom_pb2.NODE_TYPE_TEXT,
        content="Consolidated Balance Sheet",
    )
    injected.provenance.page_number = 11
    t2 = _table(11, headers, [["200", "40"]], "t-b")

    stitched = router._stitch_table_nodes([t1, injected, t2])
    assert len(stitched) == 1
    parsed = json.loads(stitched[0].content)
    assert parsed["headers"] == headers
    assert parsed["rows"] == [["100", "20"], ["200", "40"]]


def test_stitch_does_not_merge_non_adjacent_pages(router):
    headers = ["A", "B"]
    t1 = _table(1, headers, [["1", "2"]], "t1")
    t2 = _table(5, headers, [["3", "4"]], "t2")
    stitched = router._stitch_table_nodes([t1, t2])
    assert len(stitched) == 2


def test_stitch_table_nodes_compatible_headers(router):
    n1 = dom_pb2.Node(
        id="table-1",
        type=dom_pb2.NODE_TYPE_TABLE,
        content=json.dumps({"col1": ["a"], "col2": ["b"]}),
    )
    n1.provenance.page_number = 1
    n2 = dom_pb2.Node(
        id="table-2",
        type=dom_pb2.NODE_TYPE_TABLE,
        content=json.dumps({"col1": ["c"], "col2": ["d"]}),
    )
    n2.provenance.page_number = 2
    stitched = router._stitch_table_nodes([n1, n2])
    assert len(stitched) == 1
    body = stitched[0].content
    assert "a" in body and "c" in body
