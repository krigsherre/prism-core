"""Tests for table structure critic."""
import json

from core.dom.table_structure import critique_table_json
from core.dom.post_processor import DOMPostProcessor
import proto.prism.v1.dom_pb2 as dom_pb2


def test_critique_healthy_table():
    raw = json.dumps({"headers": ["A", "B"], "rows": [["1", "2"], ["3", "4"]]})
    report = critique_table_json(raw)
    assert report.ok
    assert report.stats["row_count"] == 2
    assert report.stats["col_count"] == 2


def test_critique_ragged_hard():
    raw = json.dumps(
        {
            "headers": ["A", "B", "C"],
            "rows": [["1", "2"], ["3"], ["4", "5", "6", "7"], ["x"], ["y"]],
        }
    )
    report = critique_table_json(raw)
    assert not report.ok
    assert any(i.rule_id == "table.ragged_rows" for i in report.issues)


def test_critique_empty():
    report = critique_table_json("")
    assert not report.ok
    assert any(i.rule_id == "table.empty" for i in report.issues)


def test_structure_filter_embeds_in_content():
    processor = DOMPostProcessor()
    dom = dom_pb2.DocumentDOM()
    content = json.dumps({"headers": ["A", "B"], "rows": [["1", "2"]]})
    node = dom_pb2.Node(type=dom_pb2.NODE_TYPE_TABLE, content=content)
    node.provenance.page_number = 1
    dom.nodes.append(node)

    out = processor.process(dom)
    parsed = json.loads(out.nodes[0].content)
    assert parsed["headers"] == ["A", "B"]
    assert "_structure" in parsed
    assert parsed["_structure"]["ok"] is True
    assert parsed["_structure"]["stats"]["row_count"] == 1
