# pyright: reportAttributeAccessIssue=false
import json
from core.dom.post_processor import MultiPageTableMergeFilter
from core.dom.post_processor import DOMPostProcessor
from core.dom.post_processor import HeaderFooterFilter
import proto.prism.v1.dom_pb2 as dom_pb2


def test_header_footer_filter():
    filter_instance = HeaderFooterFilter()
    node1 = dom_pb2.Node(type=dom_pb2.NODE_TYPE_TEXT, content="Valid text")
    nodes = filter_instance.process([node1])

    assert len(nodes) == 1
    assert nodes[0].content == "Valid text"


def test_multi_page_table_merge_filter():
    filter_instance = MultiPageTableMergeFilter()

    node1 = dom_pb2.Node(type=dom_pb2.NODE_TYPE_TABLE, content="Header\n---\nData1")
    node1.provenance.page_number = 1

    node2 = dom_pb2.Node(type=dom_pb2.NODE_TYPE_TABLE, content="Header\n---\nData2")
    node2.provenance.page_number = 2
    nodes = filter_instance.process([node1, node2])

    assert len(nodes) == 1
    assert "Data1" in nodes[0].content
    assert "Data2" in nodes[0].content


def test_multi_page_table_merge_json():
    filter_instance = MultiPageTableMergeFilter()
    t1 = json.dumps({"headers": ["A", "B"], "rows": [["1", "2"]]})
    t2 = json.dumps({"headers": ["A", "B"], "rows": [["3", "4"]]})

    node1 = dom_pb2.Node(type=dom_pb2.NODE_TYPE_TABLE, content=t1)
    node1.provenance.page_number = 1
    node2 = dom_pb2.Node(type=dom_pb2.NODE_TYPE_TABLE, content=t2)
    node2.provenance.page_number = 2

    nodes = filter_instance.process([node1, node2])
    assert len(nodes) == 1
    parsed = json.loads(nodes[0].content)
    assert parsed["rows"] == [["1", "2"], ["3", "4"]]


def test_dom_post_processor_normalizes_otsl():
    processor = DOMPostProcessor()
    dom = dom_pb2.DocumentDOM()
    otsl = "ColA<fcel>ColB<nl><fcel>1<fcel>2<ecel><nl>"
    node = dom_pb2.Node(type=dom_pb2.NODE_TYPE_TABLE, content=otsl)
    node.provenance.page_number = 1
    dom.nodes.append(node)

    new_dom = processor.process(dom)
    parsed = json.loads(new_dom.nodes[0].content)
    assert parsed["headers"] == ["ColA", "ColB"]
    assert parsed["rows"] == [["1", "2"]]


def test_dom_post_processor_pipeline():
    processor = DOMPostProcessor()
    dom = dom_pb2.DocumentDOM()

    node1 = dom_pb2.Node(type=dom_pb2.NODE_TYPE_TABLE, content="Header\n---\nData1")
    node1.provenance.page_number = 1

    node2 = dom_pb2.Node(type=dom_pb2.NODE_TYPE_TABLE, content="Header\n---\nData2")
    node2.provenance.page_number = 2

    dom.nodes.extend([node1, node2])
    new_dom = processor.process(dom)

    assert len(new_dom.nodes) == 1
    assert "Data1" in new_dom.nodes[0].content
    assert "Data2" in new_dom.nodes[0].content
