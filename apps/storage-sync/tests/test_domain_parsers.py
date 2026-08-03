import pytest
from core.parsers.table_parser import TableParser
from core.parsers.kv_parser import KeyValueParser
from core.parsers.table_stitcher import TableStitcher
from services.graph_signal import GraphSignalClassifier
from proto.prism.v1 import dom_pb2


def test_table_parser_otsl_detection_and_parsing():
    otsl = "<fcel>Col1<fcel>Col2<nl><fcel>Val1<fcel>Val2<ecel><nl>"
    assert TableParser.is_otsl(otsl) is True
    parsed = TableParser.parse_otsl(otsl)
    assert parsed == {"Col1": ["Val1"], "Col2": ["Val2"]}


def test_table_parser_markdown_and_json():
    md = "| A | B |\n|---|---|\n| 1 | 2 |\n"
    res = TableParser.parse_table_content(md)
    assert res == {"A": ["1"], "B": ["2"]}

    json_str = '{"headers": ["X", "Y"], "rows": [["10", "20"]]}'
    json_parsed = TableParser.parse_table_content(json_str)
    assert json_parsed == {"X": ["10"], "Y": ["20"]}

    formatted_md = TableParser.dict_to_markdown_table({"X": ["10"], "Y": ["20"]})
    assert "| X | Y |" in formatted_md
    assert "| 10 | 20 |" in formatted_md


def test_kv_parser():
    text = "Key1: Value1\nKey2: Value2"
    res = KeyValueParser.parse(text)
    assert res == {"Key1": "Value1", "Key2": "Value2"}


def test_graph_signal_classifier():
    text = "The company signed a facility agreement with its related party and subsidiary."
    assert GraphSignalClassifier.is_high_signal(text) is True

    unrelated = "This is a random plain paragraph about weather."
    assert GraphSignalClassifier.is_high_signal(unrelated) is False


def test_table_stitcher():
    node1 = dom_pb2.Node(
        id="t1",
        type=dom_pb2.NODE_TYPE_TABLE,
        content='{"col1": ["a"], "col2": ["b"]}',
        provenance=dom_pb2.Provenance(page_number=1),
    )
    node2 = dom_pb2.Node(
        id="t2",
        type=dom_pb2.NODE_TYPE_TABLE,
        content='{"col1": ["c"], "col2": ["d"]}',
        provenance=dom_pb2.Provenance(page_number=2),
    )

    stitched = TableStitcher.stitch_table_nodes([node1, node2])
    assert len(stitched) == 1
    assert "col1" in stitched[0].content
    assert "a" in stitched[0].content
    assert "c" in stitched[0].content
