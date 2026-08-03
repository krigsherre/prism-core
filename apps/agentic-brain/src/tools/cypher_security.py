"""Pure Cypher helpers (no Neo4j driver import)."""
from __future__ import annotations

import re


def inject_tenant_id_cypher(cypher: str, tenant_id: str) -> str:
    """
    Inject tenant_id only into node patterns inside MATCH / OPTIONAL MATCH / MERGE.
    Never rewrite function args like type(rel) or properties() — that breaks Cypher.
    """
    import json
    if isinstance(cypher, str) and cypher.strip().startswith("{"):
        try:
            parsed = json.loads(cypher)
            if isinstance(parsed, dict) and "cypher" in parsed:
                cypher = parsed["cypher"]
        except Exception:
            pass

    clause_re = re.compile(
        r"\b(OPTIONAL\s+MATCH|MATCH|MERGE)\b",
        re.IGNORECASE,
    )
    node_re = re.compile(
        r"\(("
        r"[a-zA-Z_][a-zA-Z0-9_]*"
        r"(?::[a-zA-Z_][a-zA-Z0-9_]*)?" 
        r"(?:\s*\{[^}]*\})?" 
        r")\)"
    )

    def inject_node(match: re.Match) -> str:
        node = match.group(1)
        if "tenant_id" in node:
            return f"({node})"
        if "{" in node:
            new_node = node.replace("{", f'{{tenant_id: "{tenant_id}", ', 1)
            return f"({new_node})"
        if ":" in node:
            var, rest = node.split(":", 1)
            return f'({var}:{rest} {{tenant_id: "{tenant_id}"}})'
        return f'({node} {{tenant_id: "{tenant_id}"}})'

    parts = clause_re.split(cypher)
    out = [parts[0]]
    i = 1
    while i < len(parts):
        keyword = parts[i]
        body = parts[i + 1] if i + 1 < len(parts) else ""
        stop = re.search(
            r"\b(WHERE|RETURN|WITH|UNWIND|SET|DELETE|CREATE|ORDER|LIMIT|SKIP)\b",
            body,
            re.IGNORECASE,
        )
        if stop:
            pattern_region = body[: stop.start()]
            rest_region = body[stop.start() :]
            pattern_region = node_re.sub(inject_node, pattern_region)
            out.append(keyword)
            out.append(pattern_region + rest_region)
        else:
            out.append(keyword)
            out.append(node_re.sub(inject_node, body))
        i += 2
    return "".join(out)
