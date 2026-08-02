import json
from core.dom.table_json import (
    TableJSON,
    parse_otsl,
    normalize_table_content,
    merge_table_json,
    parse_markdown_table,
)


SAMPLE_OTSL = (
    "No.<fcel>Name of the subsidiary<fcel>Country<fcel>Share capital<nl>"
    "<fcel>1<fcel>Infosys BPM Limited\\(^{32}\\)<fcel>India<fcel>34<ecel><nl>"
    "<fcel>2<fcel>Infosys Automotive GmbH<fcel>Germany<fcel>15<ecel><nl>"
)


def test_parse_otsl_basic():
    table = parse_otsl(SAMPLE_OTSL)
    assert table.headers == ["No.", "Name of the subsidiary", "Country", "Share capital"]
    assert len(table.rows) == 2
    assert table.rows[0][0] == "1"
    assert "Infosys BPM" in table.rows[0][1]
    assert table.rows[1][2] == "Germany"


def test_normalize_otsl():
    out = normalize_table_content(SAMPLE_OTSL)
    parsed = json.loads(out)
    assert "headers" in parsed
    assert "rows" in parsed
    assert len(parsed["headers"]) == 4
    assert len(parsed["rows"]) == 2


def test_normalize_malformed_json_otsl_wrapper():
    # Mimics the brittle single-key dict the user reported
    broken = {
        "No.<fcel>Name<fcel>Country<nl><fcel>1<fcel>Acme<fcel>India<ecel><nl>": "2<fcel>Beta<fcel>US<ecel><nl>"
    }
    out = normalize_table_content(json.dumps(broken))
    parsed = json.loads(out)
    assert parsed["headers"][0] == "No."
    assert len(parsed["rows"]) >= 1


def test_normalize_already_json():
    canonical = {"headers": ["A", "B"], "rows": [["1", "2"]]}
    out = normalize_table_content(json.dumps(canonical))
    assert json.loads(out) == canonical


def test_normalize_columnar_json():
    columnar = {"A": ["1", "3"], "B": ["2", "4"]}
    out = normalize_table_content(json.dumps(columnar))
    parsed = json.loads(out)
    assert parsed["headers"] == ["A", "B"]
    assert parsed["rows"] == [["1", "2"], ["3", "4"]]


def test_parse_markdown():
    md = "| H1 | H2 |\n| --- | --- |\n| a | b |\n| c | d |"
    table = parse_markdown_table(md)
    assert table is not None
    assert table.headers == ["H1", "H2"]
    assert table.rows == [["a", "b"], ["c", "d"]]


def test_merge_table_json():
    t1 = TableJSON(headers=["A", "B"], rows=[["1", "2"]]).model_dump_json()
    t2 = TableJSON(headers=["A", "B"], rows=[["3", "4"]]).model_dump_json()
    merged = json.loads(merge_table_json(t1, t2))
    assert merged["rows"] == [["1", "2"], ["3", "4"]]


def test_table_json_schema_for_guided():
    schema = TableJSON.model_json_schema()
    assert "headers" in schema["properties"]
    assert "rows" in schema["properties"]
