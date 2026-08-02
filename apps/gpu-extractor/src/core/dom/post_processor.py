# pyright: reportAttributeAccessIssue=false
from abc import ABC, abstractmethod
from typing import List
import json
import proto.prism.v1.dom_pb2 as dom_pb2
from core.dom.table_json import normalize_table_content, merge_table_json, is_otsl
from core.dom.table_structure import critique_table_json_safe


class DOMFilter(ABC):
    @abstractmethod
    def process(self, nodes: List[dom_pb2.Node]) -> List[dom_pb2.Node]:
        pass


class HeaderFooterFilter(DOMFilter):
    def process(self, nodes: List[dom_pb2.Node]) -> List[dom_pb2.Node]:
        valid_nodes = []
        for node in nodes:
            if not node.provenance or len(node.provenance.bounding_box) < 4:
                valid_nodes.append(node)
                continue

            y0 = node.provenance.bounding_box[1]
            y1 = node.provenance.bounding_box[3]

            if y1 < 50.0 or y0 > 742.0:
                continue

            valid_nodes.append(node)
        return valid_nodes


class MultiPageTableMergeFilter(DOMFilter):
    def process(self, nodes: List[dom_pb2.Node]) -> List[dom_pb2.Node]:
        if not nodes:
            return []

        merged = [nodes[0]]

        for current_node in nodes[1:]:
            prev_node = merged[-1]
            if (
                prev_node.type == dom_pb2.NODE_TYPE_TABLE
                and current_node.type == dom_pb2.NODE_TYPE_TABLE
            ):
                if (
                    prev_node.provenance.page_number
                    == current_node.provenance.page_number - 1
                ):
                    prev_node.content = self._merge_table_content(
                        prev_node.content, current_node.content
                    )
                    continue
            merged.append(current_node)

        return merged

    def _merge_table_content(self, table1: str, table2: str) -> str:
        if (
            table1.strip().startswith("{")
            or table2.strip().startswith("{")
            or is_otsl(table1)
            or is_otsl(table2)
        ):
            return merge_table_json(table1, table2)

        lines2 = table2.strip().split("\n")
        if len(lines2) > 2 and "---" in lines2[1]:
            data_rows = lines2[2:]
        else:
            data_rows = lines2
        return table1.strip() + "\n" + "\n".join(data_rows)


class TableNormalizeFilter(DOMFilter):
    """Ensure every TABLE node stores canonical TableJSON."""

    def process(self, nodes: List[dom_pb2.Node]) -> List[dom_pb2.Node]:
        for node in nodes:
            if node.type == dom_pb2.NODE_TYPE_TABLE and node.content:
                node.content = normalize_table_content(node.content)
        return nodes


class TableStructureCriticFilter(DOMFilter):
    """Embed structural quality into table JSON (Node has no metadata map)."""

    def process(self, nodes: List[dom_pb2.Node]) -> List[dom_pb2.Node]:
        for node in nodes:
            if node.type != dom_pb2.NODE_TYPE_TABLE or not node.content:
                continue
            report = critique_table_json_safe(node.content)
            try:
                obj = json.loads(node.content)
                if not isinstance(obj, dict):
                    continue
                obj["_structure"] = {
                    "ok": report.ok,
                    "issues": [
                        {"rule_id": i.rule_id, "severity": i.severity, "message": i.message}
                        for i in report.issues
                    ],
                    "stats": report.stats,
                }
                node.content = json.dumps(obj, ensure_ascii=False)
            except (json.JSONDecodeError, TypeError):
                continue
        return nodes


class DOMPostProcessor:
    """
    Pipeline pattern to run heuristic sweeps over the DocumentDOM.
    """

    def __init__(self, filters: List[DOMFilter] | None = None):
        if filters is None:
            self.filters: List[DOMFilter] = [
                HeaderFooterFilter(),
                TableNormalizeFilter(),
                MultiPageTableMergeFilter(),
                TableStructureCriticFilter(),
            ]
        else:
            self.filters = filters

    def process(self, dom: dom_pb2.DocumentDOM) -> dom_pb2.DocumentDOM:
        nodes = list(dom.nodes)
        for f in self.filters:
            nodes = f.process(nodes)

        new_dom = dom_pb2.DocumentDOM()
        new_dom.nodes.extend(nodes)
        if dom.document_id:
            new_dom.document_id = dom.document_id
        for k, v in dom.metadata.items():
            new_dom.metadata[k] = v
        return new_dom
