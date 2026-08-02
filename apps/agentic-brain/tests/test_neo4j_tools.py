"""Tests for Neo4j tenant injection (must not break type(rel))."""
from tools.cypher_security import inject_tenant_id_cypher


def test_inject_match_node_without_props():
    q = "MATCH (n:Entity) RETURN n LIMIT 5"
    out = inject_tenant_id_cypher(q, "t1")
    assert 'tenant_id: "t1"' in out
    assert "MATCH (n:Entity {tenant_id: \"t1\"})" in out


def test_inject_does_not_rewrite_type_rel():
    q = (
        'MATCH (apple:Entity)\n'
        "WHERE apple.name = 'Apple'\n"
        "OPTIONAL MATCH (apple)-[rel]->(related:Entity)\n"
        "RETURN apple, type(rel) as relationshipType, related\n"
        "LIMIT 100"
    )
    out = inject_tenant_id_cypher(q, "default-tenant")
    assert "type(rel)" in out
    assert "type(rel {" not in out
    assert 'MATCH (apple:Entity {tenant_id: "default-tenant"})' in out
    assert 'related:Entity {tenant_id: "default-tenant"}' in out


def test_inject_skips_already_tenanted():
    q = 'MATCH (n:Entity {tenant_id: "t1", name: "x"}) RETURN n'
    out = inject_tenant_id_cypher(q, "t1")
    assert out.count("tenant_id") == 1
