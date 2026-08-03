from typing import Any, Dict, List, Optional
import structlog
from proto.prism.v1 import dom_pb2
from core.parsers.table_parser import TableParser

logger = structlog.get_logger(__name__)


class TableStitcher:
    """
    Domain service for cross-page and cross-chunk table stitching.
    """

    @classmethod
    def normalize_header_key(cls, key: str) -> str:
        """Normalize header strings by lowercasing and stripping whitespace."""
        return " ".join(str(key).strip().lower().split())

    @classmethod
    def headers_compatible(cls, a: Dict[str, Any], b: Dict[str, Any]) -> bool:
        """True when column sets match (order-insensitive) after normalization."""
        if not a or not b:
            return False
        ha = {cls.normalize_header_key(k) for k in a.keys()}
        hb = {cls.normalize_header_key(k) for k in b.keys()}
        if not ha or not hb:
            return False
        if ha == hb:
            return True
        overlap = ha & hb
        return len(overlap) >= max(2, int(0.8 * min(len(ha), len(hb))))

    @classmethod
    def page_number(cls, node: dom_pb2.Node) -> int:
        """Safely extract 1-indexed page number from node provenance."""
        if node.HasField("provenance"):
            return int(node.provenance.page_number or 0)
        return 0

    @classmethod
    def pages_adjacent(cls, prev: dom_pb2.Node, curr: dom_pb2.Node) -> bool:
        """Check if two nodes are on adjacent or identical pages."""
        p1 = cls.page_number(prev)
        p2 = cls.page_number(curr)
        if p1 <= 0 or p2 <= 0:
            return True
        return p2 in (p1, p1 + 1)

    @classmethod
    def is_weak_interstitial(cls, node: dom_pb2.Node) -> bool:
        """
        Nodes that often sit between continued table halves across chunk boundaries
        (injected section context / short headers). Safe to skip when merging tables.
        """
        if node.type == dom_pb2.NODE_TYPE_TABLE:
            return False
        if node.type not in (
            dom_pb2.NODE_TYPE_TEXT,
            dom_pb2.NODE_TYPE_SECTION_HEADER,
            dom_pb2.NODE_TYPE_TITLE,
        ):
            return False
        text = (node.content or "").strip()
        return 0 < len(text) < 160

    @classmethod
    def merge_columnar_tables(cls, buf: Dict[str, Any], curr: Dict[str, Any]) -> Dict[str, List[str]]:
        """Append curr rows onto buf; align columns to buf header order."""
        merged = {k: list(v) if isinstance(v, list) else [v] for k, v in buf.items()}
        buf_by_norm = {cls.normalize_header_key(k): k for k in merged.keys()}
        curr_len = 0
        for v in curr.values():
            if isinstance(v, list):
                curr_len = max(curr_len, len(v))
            else:
                curr_len = max(curr_len, 1)

        for norm, buf_key in buf_by_norm.items():
            match_val = None
            for ck, cv in curr.items():
                if cls.normalize_header_key(ck) == norm:
                    match_val = cv
                    break
            if match_val is None:
                pad = [""] * curr_len
                merged[buf_key].extend(pad)
            elif isinstance(match_val, list):
                merged[buf_key].extend([str(x) for x in match_val])
            else:
                merged[buf_key].append(str(match_val))
        return merged

    @classmethod
    def can_merge_tables(cls, prev: dom_pb2.Node, curr: dom_pb2.Node) -> bool:
        """Check if two consecutive table nodes are eligible for merging."""
        if not cls.pages_adjacent(prev, curr):
            return False
        buf_parsed = TableParser.parse_table_content(prev.content)
        curr_parsed = TableParser.parse_table_content(curr.content)
        if not buf_parsed or not curr_parsed:
            return False
        if all(not isinstance(v, list) for v in buf_parsed.values()):
            return False
        if all(not isinstance(v, list) for v in curr_parsed.values()):
            return False
        return cls.headers_compatible(buf_parsed, curr_parsed)

    @classmethod
    def stitch_table_nodes(cls, nodes: List[dom_pb2.Node]) -> List[dom_pb2.Node]:
        """
        Merge continued TABLE nodes across pages/chunks.
        Skips weak interstitial text (injected chunk context) between halves.
        """
        stitched: List[dom_pb2.Node] = []
        table_buffer: Optional[dom_pb2.Node] = None
        pending_weak: List[dom_pb2.Node] = []

        def flush_buffer():
            nonlocal table_buffer, pending_weak
            if table_buffer is not None:
                stitched.append(table_buffer)
                table_buffer = None
            stitched.extend(pending_weak)
            pending_weak = []

        for node in nodes:
            if len(node.children) > 0:
                stitched_children = cls.stitch_table_nodes(list(node.children))
                del node.children[:]
                node.children.extend(stitched_children)

            if node.type == dom_pb2.NODE_TYPE_TABLE:
                if table_buffer is None:
                    table_buffer = node
                    pending_weak = []
                    continue

                if cls.can_merge_tables(table_buffer, node):
                    buf_parsed = TableParser.parse_table_content(table_buffer.content)
                    curr_parsed = TableParser.parse_table_content(node.content)
                    merged = cls.merge_columnar_tables(buf_parsed, curr_parsed)
                    table_buffer.content = TableParser.columnar_to_headers_rows_json(merged)
                    pending_weak = []
                    logger.info(
                        "Cross-chunk/page table stitch",
                        prev_page=cls.page_number(table_buffer),
                        curr_page=cls.page_number(node),
                        columns=len(merged),
                    )
                else:
                    flush_buffer()
                    table_buffer = node
            elif table_buffer is not None and cls.is_weak_interstitial(node):
                pending_weak.append(node)
            else:
                flush_buffer()
                stitched.append(node)

        flush_buffer()
        return stitched
