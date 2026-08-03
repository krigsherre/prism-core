"""Assemble multi-chunk DocumentDOM messages before bifurcation routing."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import structlog
from proto.prism.v1 import dom_pb2

logger = structlog.get_logger(__name__)


def _node_sort_key(node: dom_pb2.Node) -> Tuple[int, float, str]:
    page = 0
    y0 = 0.0
    if node.HasField("provenance"):
        page = int(node.provenance.page_number or 0)
        if len(node.provenance.bounding_box) >= 2:
            y0 = float(node.provenance.bounding_box[1])
    return (page, y0, node.id or "")


@dataclass
class _Buffer:
    tenant_id: str
    document_id: str
    chunk_total: int
    chunks: Dict[int, dom_pb2.DocumentDOM] = field(default_factory=dict)
    first_seen_monotonic: float = field(default_factory=time.monotonic)
    filename: str = "unknown"


class ChunkDOMAssembler:
    """
    Buffers parsed_documents chunk DOMs until chunk_total arrive, then emits one
    page-ordered DocumentDOM for cross-chunk table stitching.

    Documents without chunk_total (or chunk_total <= 1) pass through immediately.
    Incomplete buffers are flushed after timeout_seconds so a lost chunk cannot stall forever.
    """

    def __init__(self, timeout_seconds: float = 900.0):
        self.timeout_seconds = timeout_seconds
        self._buffers: Dict[Tuple[str, str], _Buffer] = {}

    @staticmethod
    def _chunk_meta(dom: dom_pb2.DocumentDOM) -> Tuple[int, int]:
        meta = dict(dom.metadata) if dom.metadata else {}
        try:
            total = int(meta.get("chunk_total") or 0)
        except (TypeError, ValueError):
            total = 0
        try:
            index = int(meta.get("chunk_index") or 0)
        except (TypeError, ValueError):
            index = 0
        return index, total

    def add(
        self, tenant_id: str, dom: dom_pb2.DocumentDOM
    ) -> Optional[dom_pb2.DocumentDOM]:
        """
        Ingest one chunk DOM.
        Returns an assembled DOM when ready to route, else None (still buffering).
        """
        index, total = self._chunk_meta(dom)
        if total <= 1:
            return dom

        document_id = dom.document_id or f"doc_{tenant_id}"
        key = (tenant_id, document_id)
        buf = self._buffers.get(key)
        if buf is None:
            filename = "unknown"
            if dom.metadata:
                filename = dom.metadata.get("original_filename") or "unknown"
            buf = _Buffer(
                tenant_id=tenant_id,
                document_id=document_id,
                chunk_total=total,
                filename=filename,
            )
            self._buffers[key] = buf
        else:
            buf.chunk_total = max(buf.chunk_total, total)

        buf.chunks[index] = dom
        logger.info(
            "Buffered parsed chunk for cross-chunk stitch",
            document_id=document_id,
            chunk_index=index,
            received=len(buf.chunks),
            chunk_total=buf.chunk_total,
        )

        if len(buf.chunks) >= buf.chunk_total:
            return self._pop_assembled(key)
        return None

    def flush_expired(self) -> List[Tuple[str, dom_pb2.DocumentDOM]]:
        """Assemble and emit incomplete buffers that exceeded timeout."""
        now = time.monotonic()
        ready: List[Tuple[str, str]] = []
        for key, buf in self._buffers.items():
            if now - buf.first_seen_monotonic >= self.timeout_seconds:
                ready.append(key)

        out: List[Tuple[str, dom_pb2.DocumentDOM]] = []
        for key in ready:
            logger.warning(
                "Flushing incomplete chunk buffer after timeout",
                document_id=key[1],
                received=len(self._buffers[key].chunks),
                expected=self._buffers[key].chunk_total,
                timeout_seconds=self.timeout_seconds,
            )
            assembled = self._pop_assembled(key)
            if assembled is not None:
                out.append((key[0], assembled))
        return out

    def _pop_assembled(self, key: Tuple[str, str]) -> Optional[dom_pb2.DocumentDOM]:
        buf = self._buffers.pop(key, None)
        if buf is None or not buf.chunks:
            return None
        return assemble_chunk_doms(buf.document_id, buf.chunks)


def assemble_chunk_doms(
    document_id: str,
    chunks_by_index: Dict[int, dom_pb2.DocumentDOM],
) -> dom_pb2.DocumentDOM:
    """Merge chunk DOMs into one page-ordered DocumentDOM."""
    ordered_indices = sorted(chunks_by_index.keys())
    merged = dom_pb2.DocumentDOM(document_id=document_id)

    first = chunks_by_index[ordered_indices[0]]
    for k, v in first.metadata.items():
        merged.metadata[k] = v
    merged.metadata["chunk_assembled"] = "true"
    merged.metadata["chunks_received"] = str(len(ordered_indices))
    merged.metadata["chunk_total"] = first.metadata.get(
        "chunk_total", str(len(ordered_indices))
    )

    nodes: List[dom_pb2.Node] = []
    for idx in ordered_indices:
        for node in chunks_by_index[idx].nodes:
            nodes.append(node)

    nodes.sort(key=_node_sort_key)
    merged.nodes.extend(nodes)

    logger.info(
        "Assembled cross-chunk DocumentDOM",
        document_id=document_id,
        chunks=len(ordered_indices),
        nodes=len(nodes),
    )
    return merged
