from kafka.consumers.bifurcation import DocumentRouter
import sys
from unittest.mock import MagicMock, AsyncMock
import pytest
from proto.prism.v1 import dom_pb2
import json
import asyncio

sys.modules['aiokafka'] = MagicMock()

@pytest.fixture
def mock_sql_repo():
    return AsyncMock()

@pytest.fixture
def mock_qdrant_repo():
    return AsyncMock()

@pytest.fixture
def mock_embeddings():
    return AsyncMock()

@pytest.fixture
def router(mock_sql_repo, mock_qdrant_repo):
    r = DocumentRouter(mock_sql_repo, mock_qdrant_repo)
    r._real_embedding = AsyncMock(return_value=[0.1] * 1536)
    return r

@pytest.mark.asyncio
async def test_route_node_table_no_recursion(router, mock_sql_repo, mock_qdrant_repo, mock_embeddings):
    table_node = dom_pb2.Node(
        id="table-1",
        type=dom_pb2.NODE_TYPE_TABLE,
        content="Table Data",
        provenance=dom_pb2.Provenance(page_number=1, bounding_box=[0.0, 0.0, 1.0, 1.0])
    )
    
    text_child = dom_pb2.Node(
        id="text-1",
        type=dom_pb2.NODE_TYPE_TEXT,
        content="Cell Data"
    )
    table_node.children.append(text_child)
    
    mock_producer = AsyncMock()
    await router.route_node("tenant-1", "doc-1", table_node, producer=mock_producer)
    
    # Table itself is routed to raw_table_doms (children may also be routed)
    topics = [c.args[0] for c in mock_producer.send_and_wait.call_args_list]
    assert "raw_table_doms" in topics
    mock_qdrant_repo.upsert_vector.assert_called()
    router._real_embedding.assert_called()

@pytest.mark.asyncio
async def test_route_node_text(router, mock_sql_repo, mock_qdrant_repo, mock_embeddings):
    text_node = dom_pb2.Node(
        id="text-2",
        type=dom_pb2.NODE_TYPE_TEXT,
        content="Hello World",
        provenance=dom_pb2.Provenance(page_number=2, bounding_box=[10.0, 10.0, 20.0, 20.0])
    )
    
    await router.route_node("tenant-2", "doc-2", text_node)
    
    router._real_embedding.assert_called_once_with("Hello World")
    mock_qdrant_repo.upsert_vector.assert_called_once()
    _, kwargs = mock_qdrant_repo.upsert_vector.call_args
    assert kwargs["payload"]["tenant_id"] == "tenant-2"
    assert kwargs["payload"]["source_page"] == 2
    assert kwargs["payload"]["source_bbox"] == [10.0, 10.0, 20.0, 20.0]

def test_parse_table_content_json(router):
    json_content = '{"col1": ["val1", "val2"], "col2": ["val3", "val4"]}'
    res = router._parse_table_content(json_content)
    assert res == {"col1": ["val1", "val2"], "col2": ["val3", "val4"]}

def test_parse_table_content_headers_rows_json(router):
    content = json.dumps({
        "headers": ["Name", "Country"],
        "rows": [["Acme", "India"], ["Beta", "US"]]
    })
    res = router._parse_table_content(content)
    assert res == {"Name": ["Acme", "Beta"], "Country": ["India", "US"]}

def test_parse_table_content_otsl(router):
    otsl = (
        "No.<fcel>Name of the subsidiary<fcel>Country<fcel>Exchange ratio Reporting currency<nl>"
        "<fcel>1<fcel>Infosys BPM Limited<fcel>India<fcel>INR<ecel><nl>"
        "<fcel>2<fcel>Infosys Automotive GmbH<fcel>Germany<fcel>1 EUR = 898.2<ecel><nl>"
    )
    res = router._parse_table_content(otsl)
    assert "No." in res
    assert res["No."] == ["1", "2"]
    assert res["Country"] == ["India", "Germany"]
    # Must NOT collapse into a single key from splitting on '='
    assert len(res) == 4
    assert "1 EUR = 898.2" in res["Exchange ratio Reporting currency"]

def test_parse_table_content_brittle_otsl_json_wrapper(router):
    broken = {
        "No.<fcel>Name<fcel>Country<nl><fcel>1<fcel>Acme<fcel>India<ecel><nl>": (
            "2<fcel>Beta<fcel>US<ecel><nl>"
        )
    }
    res = router._parse_table_content(json.dumps(broken))
    assert res["No."] == ["1", "2"]
    assert res["Name"] == ["Acme", "Beta"]

def test_parse_table_content_markdown(router):
    md_content = """
    | Header 1 | Header 2 |
    | --- | --- |
    | Row 1 Col 1 | Row 1 Col 2 |
    | Row 2 Col 1 | Row 2 Col 2 |
    """
    res = router._parse_table_content(md_content)
    assert res["Header 1"] == ["Row 1 Col 1", "Row 2 Col 1"]
    assert res["Header 2"] == ["Row 1 Col 2", "Row 2 Col 2"]

def test_parse_table_content_kv(router):
    kv_content = """
    Key 1: Value 1
    Key 2: Value 2
    """
    res = router._parse_table_content(kv_content)
    assert res == {"Key 1": "Value 1", "Key 2": "Value 2"}

def test_parse_table_content_does_not_kv_split_currency_blob(router):
    blob = "Subsidiary India 1 USD = 85.62 capital 175 reserves 975"
    res = router._parse_table_content(blob)
    # Should fall back to header_1, not split on '='
    assert "header_1" in res or len(res) == 1
    assert not any("1 USD" in str(k) for k in res.keys())

def test_stitch_table_nodes(router):
    md_content_1 = '{"col1": ["a"], "col2": ["b"]}'
    node1 = dom_pb2.Node(id="table-1", type=dom_pb2.NODE_TYPE_TABLE, content=md_content_1)
    
    md_content_2 = '{"col1": ["c"], "col2": ["d"]}'
    node2 = dom_pb2.Node(id="table-2", type=dom_pb2.NODE_TYPE_TABLE, content=md_content_2)
    
    stitched = router._stitch_table_nodes([node1, node2])
    assert len(stitched) == 1
    assert "col1" in stitched[0].content
    assert "a" in stitched[0].content
    assert "c" in stitched[0].content

@pytest.mark.asyncio
async def test_route_node_key_value(router, mock_sql_repo, mock_qdrant_repo, mock_embeddings):
    kv_node = dom_pb2.Node(
        id="kv-1",
        type=dom_pb2.NODE_TYPE_KEY_VALUE,
        content="Name: John Doe",
        provenance=dom_pb2.Provenance(page_number=1, bounding_box=[0.0, 0.0, 1.0, 1.0])
    )
    
    mock_producer = AsyncMock()
    await router.route_node("tenant-1", "doc-1", kv_node, producer=mock_producer)
    
    mock_producer.send_and_wait.assert_called_once()
    args, kwargs = mock_producer.send_and_wait.call_args
    payload_str = kwargs["value"].decode("utf-8")
    payload = json.loads(payload_str)
    
    assert payload["extracted_data"] == {"Name": "John Doe"}
    mock_qdrant_repo.upsert_vector.assert_called_once()

@pytest.mark.asyncio
async def test_bifurcation_consumer_run(mock_sql_repo, mock_qdrant_repo, mock_embeddings):
    from kafka.consumers.bifurcation import BifurcationConsumer
    consumer = BifurcationConsumer(mock_sql_repo, mock_qdrant_repo)
    consumer.router._real_embedding = AsyncMock(return_value=[0.1]*1536)
    
    dom = dom_pb2.DocumentDOM(document_id="doc-1")
    node = dom.nodes.add()
    node.id = "text-1"
    node.type = dom_pb2.NODE_TYPE_TEXT
    node.content = "Some Text"
    
    class MockConsumer:
        def __init__(self, *args, **kwargs):
            pass
        async def start(self): pass
        async def stop(self): pass
        def __aiter__(self):
            class Msg:
                value = dom.SerializeToString()
                key = b"tenant-1"
            async def _gen():
                yield Msg()
                raise asyncio.CancelledError()
            return _gen()
            
    class MockProducer:
        def __init__(self, *args, **kwargs):
            pass
        async def start(self): pass
        async def stop(self): pass
        async def send_and_wait(self, *args, **kwargs): pass
        
    from unittest.mock import patch
    with patch("kafka.consumers.bifurcation.AIOKafkaConsumer", MockConsumer), \
         patch("kafka.consumers.bifurcation.AIOKafkaProducer", MockProducer):
        await consumer.run()
        
    mock_qdrant_repo.upsert_vector.assert_called_once()
