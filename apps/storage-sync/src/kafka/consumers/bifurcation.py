import asyncio
import json
import uuid
from typing import Any, Dict, List, Optional
import structlog
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from qdrant_client import models

from config.settings import settings
from core.parsers.kv_parser import KeyValueParser
from core.parsers.table_parser import TableParser
from core.parsers.table_stitcher import TableStitcher
from kafka.consumers.base import BaseKafkaConsumer
from kafka.consumers.chunk_assembler import ChunkDOMAssembler
from proto.prism.v1 import dom_pb2
from repositories.qdrant_repo import QdrantRepository
from repositories.sql_repo import SQLRepository
from services.embedding_service import EmbeddingService
from services.graph_signal import GraphSignalClassifier
from services.metadata_service import MetadataExtractionService

logger = structlog.get_logger(__name__)


class DocumentRouter:
    """
    Router managing structural bifurcation of parsed document nodes across backends.
    Routes tabular data to SQL alignment pipeline, unstructured text to Qdrant vector index,
    and high-signal corporate governance relationships to Graph RAG agent.
    """

    def __init__(
        self,
        sql_repo: SQLRepository,
        qdrant_repo: QdrantRepository,
        embeddings=None,
    ) -> None:
        self.sql_repo = sql_repo
        self.qdrant_repo = qdrant_repo
        self.embedding_service = EmbeddingService()

    @property
    def _http_client(self):
        """HTTP client property exposed for backwards compatibility with tests."""
        return self.embedding_service._http_client

    @_http_client.setter
    def _http_client(self, client):
        self.embedding_service._http_client = client

    async def precompute_embeddings(self, nodes: list) -> dict:
        """Precompute embeddings in batches to optimize throughput."""
        return await self.embedding_service.precompute_embeddings(nodes)

    def _get_embedding(self, node: dom_pb2.Node, precomputed: dict) -> list:
        """Look up embedding vector for node."""
        return self.embedding_service.get_embedding_for_node(node, precomputed)

    def _parse_table_content(self, content: str) -> dict:
        """Delegate table parsing to TableParser service."""
        return TableParser.parse_table_content(content)

    def _parse_kv_content(self, content: str) -> dict:
        """Delegate KV parsing to KeyValueParser service."""
        return KeyValueParser.parse(content)

    def _dict_to_markdown_table(self, data: dict) -> str:
        """Delegate markdown table formatting to TableParser service."""
        return TableParser.dict_to_markdown_table(data)

    def _stitch_table_nodes(self, nodes: list) -> list:
        """Delegate table stitching to TableStitcher service."""
        return TableStitcher.stitch_table_nodes(nodes)

    def _extract_provenance(self, node: dom_pb2.Node, fallback_page: int = 1) -> dict:
        if node.HasField("provenance") and getattr(node.provenance, "page_number", 0) > 0:
            return {
                "page_number": node.provenance.page_number,
                "bounding_box": list(node.provenance.bounding_box),
            }
        return {"page_number": fallback_page if fallback_page > 0 else 1, "bounding_box": [0, 0, 0, 0]}

    def _build_full_context(self, parent_text: str, siblings: list, node_index: int) -> str:
        parts = [parent_text] if parent_text else []
        if not siblings:
            return "\n".join(parts)

        if node_index > 0:
            prev_node = siblings[node_index - 1]
            if prev_node.type == dom_pb2.NODE_TYPE_TEXT and prev_node.content:
                parts.append(prev_node.content)

        for i in range(1, 3):
            if node_index + i < len(siblings):
                next_node = siblings[node_index + i]
                if next_node.type == dom_pb2.NODE_TYPE_TEXT and next_node.content:
                    parts.append(next_node.content)
                else:
                    break

        return "\n".join(parts)

    def merge_metrics(self, parent_metrics: dict, child_metrics: dict) -> None:
        if not isinstance(child_metrics, dict):
            return
        parent_metrics["sql_mapped"] |= child_metrics.get("sql_mapped", False)
        parent_metrics["vector_mapped"] |= child_metrics.get("vector_mapped", False)
        parent_metrics["graph_mapped"] |= child_metrics.get("graph_mapped", False)
        parent_metrics["sql_nodes_count"] += child_metrics.get("sql_nodes_count", 0)
        parent_metrics["graph_nodes_count"] += child_metrics.get("graph_nodes_count", 0)

    async def route_node(
        self,
        tenant_id: str,
        document_id: str,
        node: dom_pb2.Node,
        producer=None,
        parent_text: str = "",
        user_id: str = None,
        siblings: list = None,
        node_index: int = 0,
        precomputed_embeddings: dict = None,
        point_batch: list = None,
        parent_page: int = 1,
    ) -> dict:
        metrics = {
            "sql_mapped": False,
            "vector_mapped": False,
            "graph_mapped": False,
            "sql_nodes_count": 0,
            "graph_nodes_count": 0,
        }

        try:
            prov = self._extract_provenance(node, fallback_page=parent_page)
            current_page = prov.get("page_number", parent_page) or parent_page
            full_context = self._build_full_context(parent_text, siblings, node_index)

            if node.type == dom_pb2.NODE_TYPE_TABLE:
                await self._route_table(
                    tenant_id, document_id, node, producer, prov, full_context,
                    parent_text, user_id, metrics, precomputed_embeddings, point_batch
                )
            elif node.type in (dom_pb2.NODE_TYPE_KEY_VALUE, dom_pb2.NODE_TYPE_FORM):
                await self._route_kv(
                    tenant_id, document_id, node, producer, prov, full_context,
                    parent_text, user_id, metrics, precomputed_embeddings, point_batch
                )
            elif node.type in (
                dom_pb2.NODE_TYPE_TEXT, dom_pb2.NODE_TYPE_SECTION_HEADER,
                dom_pb2.NODE_TYPE_TITLE, dom_pb2.NODE_TYPE_CHECKBOX, dom_pb2.NODE_TYPE_CODE
            ):
                await self._route_unstructured(
                    tenant_id, document_id, node, producer, prov, full_context,
                    parent_text, user_id, metrics, precomputed_embeddings, point_batch
                )
            elif node.type == dom_pb2.NODE_TYPE_IMAGE:
                logger.info("Skipped IMAGE node routing (unsupported)", node_id=node.id)

            current_parent_text = (
                node.content if node.type in (dom_pb2.NODE_TYPE_SECTION_HEADER, dom_pb2.NODE_TYPE_TITLE) else parent_text
            )
            children = list(node.children)

            if children:
                async def process_child(i, child):
                    return await self.route_node(
                        tenant_id, document_id, child, producer,
                        parent_text=current_parent_text, siblings=children, node_index=i,
                        precomputed_embeddings=precomputed_embeddings,
                        point_batch=point_batch,
                        parent_page=current_page,
                    )

                child_tasks = [process_child(i, child) for i, child in enumerate(children)]
                child_results = await asyncio.gather(*child_tasks)
                for child_metrics in child_results:
                    self.merge_metrics(metrics, child_metrics)

        except Exception as e:
            logger.error("Failed to route node", error=str(e), node_id=node.id)

        return metrics

    async def _route_table(
        self, tenant_id, document_id, node, producer, prov, full_context,
        parent_text, user_id, metrics, precomputed_embeddings, point_batch=None
    ):
        extracted = TableParser.parse_table_content(node.content)
        markdown = TableParser.dict_to_markdown_table(extracted) if extracted else (node.content or "")
        payload = {
            "tenant_id": tenant_id,
            "document_id": document_id,
            "node_id": node.id,
            "target_table": "",
            "extracted_data": extracted,
            "markdown_content": markdown,
            "source_page": prov["page_number"],
            "source_bbox": prov["bounding_box"],
            "user_id": user_id,
            "parent_section_text": full_context,
        }

        if producer:
            try:
                send_fn = getattr(producer, "send_and_wait", None) or producer.send
                await send_fn("raw_table_doms", key=document_id.encode("utf-8"), value=json.dumps(payload).encode("utf-8"))
                logger.info("Routed table node to raw_table_doms topic", node_id=node.id)
                metrics["sql_mapped"] = True
                metrics["sql_nodes_count"] += 1
            except Exception as e:
                logger.error("Failed to send table to Kafka, skipping", error=str(e), node_id=node.id)

        async def _async_secondary_tasks():
            if producer:
                text_for_graph = f"{full_context}\n{markdown}"
                if GraphSignalClassifier.is_high_signal(text_for_graph):
                    graph_payload = {
                        "tenant_id": tenant_id,
                        "document_id": document_id,
                        "node_id": node.id,
                        "text_content": text_for_graph,
                        "parent_section_text": full_context,
                        "source_page": prov["page_number"],
                        "source_bbox": prov["bounding_box"],
                        "user_id": user_id,
                    }
                    try:
                        send_fn = getattr(producer, "send_and_wait", None) or producer.send
                        await send_fn("graph_extraction_tasks", key=document_id.encode("utf-8"), value=json.dumps(graph_payload).encode("utf-8"))
                        logger.info("Dual-routed corporate table node to graph_extraction_tasks", node_id=node.id)
                        metrics["graph_mapped"] = True
                        metrics["graph_nodes_count"] += 1
                    except Exception as e:
                        logger.error("Failed to route table to Graph Agent", error=str(e), node_id=node.id)

            if node.content and node.content.strip():
                try:
                    vector = self._get_embedding(node, precomputed_embeddings)
                    metadata = {
                        "tenant_id": tenant_id,
                        "document_id": document_id,
                        "node_id": node.id,
                        "node_type": "NODE_TYPE_TABLE",
                        "content": node.content,
                        "parent_section_text": parent_text,
                        "is_structured_table": True,
                        "source_page": prov["page_number"],
                        "source_bbox": prov["bounding_box"],
                        "user_id": user_id,
                    }
                    if point_batch is not None:
                        qdrant_id = str(uuid.uuid5(uuid.NAMESPACE_OID, node.id))
                        point_batch.append(models.PointStruct(id=qdrant_id, vector=vector, payload=metadata))
                    else:
                        await self.qdrant_repo.upsert_vector(node_id=node.id, document_id=document_id, vector=vector, payload=metadata)
                    logger.info("Dual-routed table node to Qdrant Vector DB", node_id=node.id)
                    metrics["vector_mapped"] = True
                except Exception as e:
                    logger.error("Failed to embed table to Qdrant", error=str(e), node_id=node.id)

        asyncio.create_task(_async_secondary_tasks())

    async def _route_kv(
        self, tenant_id, document_id, node, producer, prov, full_context,
        parent_text, user_id, metrics, precomputed_embeddings, point_batch=None
    ):
        payload = {
            "tenant_id": tenant_id,
            "document_id": document_id,
            "node_id": node.id,
            "target_table": "",
            "extracted_data": KeyValueParser.parse(node.content),
            "source_page": prov["page_number"],
            "source_bbox": prov["bounding_box"],
            "user_id": user_id,
            "parent_section_text": full_context,
        }

        if producer:
            try:
                await producer.send_and_wait("raw_table_doms", key=document_id.encode("utf-8"), value=json.dumps(payload).encode("utf-8"))
                logger.info("Routed key-value/form node to raw_table_doms topic", node_id=node.id)
                metrics["sql_mapped"] = True
                metrics["sql_nodes_count"] += 1
            except Exception as e:
                logger.error("Failed to send KV node to Kafka, skipping", error=str(e), node_id=node.id)

            text_for_graph = f"{full_context}\n{node.content or ''}"
            if GraphSignalClassifier.is_high_signal(text_for_graph):
                graph_payload = {
                    "tenant_id": tenant_id,
                    "document_id": document_id,
                    "node_id": node.id,
                    "text_content": text_for_graph,
                    "parent_section_text": full_context,
                    "source_page": prov["page_number"],
                    "source_bbox": prov["bounding_box"],
                    "user_id": user_id,
                }
                try:
                    await producer.send_and_wait("graph_extraction_tasks", key=document_id.encode("utf-8"), value=json.dumps(graph_payload).encode("utf-8"))
                    logger.info("Dual-routed corporate KV node to graph_extraction_tasks", node_id=node.id)
                    metrics["graph_mapped"] = True
                    metrics["graph_nodes_count"] += 1
                except Exception as e:
                    logger.error("Failed to route KV node to Graph Agent", error=str(e), node_id=node.id)

        if node.content and node.content.strip():
            try:
                vector = self._get_embedding(node, precomputed_embeddings)
                metadata = {
                    "tenant_id": tenant_id,
                    "document_id": document_id,
                    "node_id": node.id,
                    "node_type": dom_pb2.NodeType.Name(node.type),
                    "content": node.content,
                    "parent_section_text": parent_text,
                    "is_key_value": True,
                    "source_page": prov["page_number"],
                    "source_bbox": prov["bounding_box"],
                }
                if point_batch is not None:
                    qdrant_id = str(uuid.uuid5(uuid.NAMESPACE_OID, node.id))
                    point_batch.append(models.PointStruct(id=qdrant_id, vector=vector, payload=metadata))
                else:
                    await self.qdrant_repo.upsert_vector(node_id=node.id, document_id=document_id, vector=vector, payload=metadata)
                logger.info("Dual-routed key-value/form node to Qdrant Vector DB", node_id=node.id)
                metrics["vector_mapped"] = True
            except Exception as e:
                logger.error("Failed to embed KV node to Qdrant", error=str(e), node_id=node.id)

    async def _route_unstructured(
        self, tenant_id, document_id, node, producer, prov, full_context,
        parent_text, user_id, metrics, precomputed_embeddings, point_batch=None
    ):
        if not (node.content and node.content.strip()):
            return

        try:
            vector = self._get_embedding(node, precomputed_embeddings)
            type_name = dom_pb2.NodeType.Name(node.type)
            payload = {
                "tenant_id": tenant_id,
                "document_id": document_id,
                "text": node.content,
                "type": type_name,
                "parent_section_text": parent_text,
                "source_page": prov["page_number"],
                "source_bbox": prov["bounding_box"],
            }
            if point_batch is not None:
                qdrant_id = str(uuid.uuid5(uuid.NAMESPACE_OID, node.id))
                point_batch.append(models.PointStruct(id=qdrant_id, vector=vector, payload=payload))
            else:
                await self.qdrant_repo.upsert_vector(
                    node_id=node.id, document_id=document_id, vector=vector, payload=payload
                )
            logger.info("Routed node to Qdrant", node_id=node.id, node_type=type_name)
            metrics["vector_mapped"] = True

            if node.type == dom_pb2.NODE_TYPE_TEXT and producer:
                text = node.content or ""
                if GraphSignalClassifier.is_high_signal(text, min_length=50):
                    graph_payload = {
                        "tenant_id": tenant_id,
                        "document_id": document_id,
                        "node_id": node.id,
                        "text_content": node.content,
                        "parent_section_text": full_context,
                        "source_page": prov["page_number"],
                        "source_bbox": prov["bounding_box"],
                        "user_id": user_id,
                    }
                    try:
                        await producer.send_and_wait("graph_extraction_tasks", key=document_id.encode("utf-8"), value=json.dumps(graph_payload).encode("utf-8"))
                        logger.info("Routed text node to graph_extraction_tasks", node_id=node.id)
                        metrics["graph_mapped"] = True
                        metrics["graph_nodes_count"] += 1
                    except Exception as e:
                        logger.error("Failed to route node to Graph Agent", error=str(e), node_id=node.id)

        except Exception as e:
            logger.error("Failed to route node to Qdrant", error=repr(e), node_id=node.id)


class BifurcationConsumer(BaseKafkaConsumer):
    """
    Consumer processing incoming DocumentDOM protobuf messages from `parsed_documents` topic,
    assembling multi-chunk DOMs via ChunkDOMAssembler, and executing DocumentRouter bifurcation.
    """

    def __init__(self, sql_repo: SQLRepository, qdrant_repo: QdrantRepository, embeddings=None) -> None:
        super().__init__(
            topics=["parsed_documents"],
            group_id=settings.kafka_consumer_group_bifurcation,
            needs_producer=True,
        )
        self.router = DocumentRouter(sql_repo, qdrant_repo, embeddings=embeddings)
        self.assembler = ChunkDOMAssembler(
            timeout_seconds=float(getattr(settings, "chunk_assemble_timeout_seconds", 900))
        )
        self.metadata_service = MetadataExtractionService()

    def _create_consumer(self):
        return AIOKafkaConsumer(
            *self.topics,
            bootstrap_servers=settings.kafka_broker,
            group_id=self.group_id,
            auto_offset_reset=self.auto_offset_reset,
        )

    def _create_producer(self):
        return AIOKafkaProducer(bootstrap_servers=settings.kafka_broker)

    async def _process_message(self, msg) -> None:
        tenant_id = msg.key.decode("utf-8") if msg.key else "unknown"
        dom = dom_pb2.DocumentDOM()

        try:
            dom.ParseFromString(msg.value)

            for tid, assembled in self.assembler.flush_expired():
                await self._process_document(tid, assembled)

            ready = self.assembler.add(tenant_id, dom)
            if ready is None:
                logger.info(
                    "Streaming page-level table nodes immediately while buffering remaining PDF chunks",
                    document_id=dom.document_id,
                    chunk_index=dom.metadata.get("chunk_index"),
                    chunk_total=dom.metadata.get("chunk_total"),
                )
                await self._stream_page_tables_immediately(tenant_id, dom)
                return
            await self._process_document(tenant_id, ready)
        except Exception as e:
            logger.error("Failed to process DocumentDOM", error=str(e), tenant_id=tenant_id)

    async def _stream_page_tables_immediately(self, tenant_id: str, dom: dom_pb2.DocumentDOM) -> None:
        """Stream page-level table nodes to raw_table_doms immediately without waiting for full document chunk assembly barrier."""
        producer = self._producer
        if not producer:
            return
        document_id = dom.document_id if dom.document_id else f"doc_{tenant_id}"
        user_id = dom.metadata.get("user_id", None) if dom.metadata else None

        for node in dom.nodes:
            if node.node_type in (dom_pb2.NODE_TYPE_TABLE, dom_pb2.NODE_TYPE_KEY_VALUE):
                prov = self.router._extract_provenance(node)
                full_context = self.router._build_full_context("", [], 0)
                extracted = (
                    TableParser.parse_table_content(node.content)
                    if node.node_type == dom_pb2.NODE_TYPE_TABLE
                    else KeyValueParser.parse(node.content)
                )
                markdown = (
                    TableParser.dict_to_markdown_table(extracted)
                    if extracted and node.node_type == dom_pb2.NODE_TYPE_TABLE
                    else (node.content or "")
                )

                payload = {
                    "tenant_id": tenant_id,
                    "document_id": document_id,
                    "node_id": node.id,
                    "target_table": "",
                    "extracted_data": extracted,
                    "markdown_content": markdown,
                    "source_page": prov["page_number"],
                    "source_bbox": prov["bounding_box"],
                    "user_id": user_id,
                    "parent_section_text": full_context,
                }
                try:
                    send_fn = getattr(producer, "send", None) or producer.send_and_wait
                    res = send_fn(
                        "raw_table_doms", key=document_id.encode("utf-8"), value=json.dumps(payload).encode("utf-8")
                    )
                    if asyncio.iscoroutine(res):
                        await res
                    logger.info(
                        "Streamed page-level table node to raw_table_doms immediately",
                        node_id=node.id,
                        page=prov["page_number"],
                    )
                except Exception as e:
                    logger.error("Failed streaming page table node to Kafka", error=str(e), node_id=node.id)

    async def _process_document(self, tenant_id: str, dom: dom_pb2.DocumentDOM) -> None:
        document_id = dom.document_id if dom.document_id else f"doc_{tenant_id}"
        user_id = dom.metadata.get("user_id", None) if dom.metadata else None
        filename = dom.metadata.get("original_filename", "unknown") if dom.metadata else "unknown"

        logger.info(
            "Processing DocumentDOM",
            tenant=tenant_id,
            document_id=document_id,
            user_id=user_id,
            chunk_assembled=dom.metadata.get("chunk_assembled"),
            chunks_received=dom.metadata.get("chunks_received"),
        )

        overall_metrics = {
            "sql_mapped": False,
            "vector_mapped": False,
            "graph_mapped": False,
            "sql_nodes_count": 0,
            "graph_nodes_count": 0,
            "company_name": None,
            "ticker": None,
            "fiscal_period": None,
        }

        extracted_text_chunks = []
        char_count = 0
        for n in dom.nodes:
            if n.content and n.type == dom_pb2.NODE_TYPE_TEXT:
                extracted_text_chunks.append(n.content)
                char_count += len(n.content)
                if char_count > 10000:
                    break

        if extracted_text_chunks:
            sample_text = "\n".join(extracted_text_chunks)[:10000]
            meta = await self.metadata_service.extract_metadata(sample_text, document_id)
            overall_metrics["company_name"] = meta["company_name"]
            overall_metrics["ticker"] = meta["ticker"]
            overall_metrics["fiscal_period"] = meta["fiscal_period"]

        stitched_nodes = self.router._stitch_table_nodes(list(dom.nodes))
        precomputed = await self.router.precompute_embeddings(stitched_nodes)

        point_batch = []

        async def process_node(i, node):
            return await self.router.route_node(
                tenant_id,
                document_id,
                node,
                self._producer,
                user_id=user_id,
                siblings=stitched_nodes,
                node_index=i,
                precomputed_embeddings=precomputed,
                point_batch=point_batch,
            )

        tasks = [process_node(i, node) for i, node in enumerate(stitched_nodes)]
        results = await asyncio.gather(*tasks)

        if point_batch:
            batch_size = 256
            for i in range(0, len(point_batch), batch_size):
                chunk = point_batch[i : i + batch_size]
                try:
                    await self.router.qdrant_repo.upsert_batch(chunk)
                    logger.info("Upserted batch to Qdrant", batch_size=len(chunk), document_id=document_id)
                except Exception as e:
                    logger.error("Failed to upsert batch to Qdrant", error=str(e), document_id=document_id)

        for flags in results:
            self.router.merge_metrics(overall_metrics, flags)

        await self._publish_completion_status(tenant_id, document_id, filename, overall_metrics)

    async def _publish_completion_status(
        self, tenant_id: str, document_id: str, filename: str, metrics: dict
    ) -> None:
        producer = self._producer
        if not producer:
            return

        any_mapped = metrics["sql_mapped"] or metrics["vector_mapped"] or metrics["graph_mapped"]
        final_status = "IN_PROGRESS" if any_mapped else "COMPLETED"

        status_event = json.dumps({
            "document_id": document_id,
            "tenant_id": tenant_id,
            "filename": filename,
            "current_stage": "bifurcation",
            "status": final_status,
            "error_message": "",
            "sql_mapped": metrics["sql_mapped"],
            "vector_mapped": metrics["vector_mapped"],
            "graph_mapped": metrics["graph_mapped"],
            "sql_nodes_total": metrics["sql_nodes_count"],
            "graph_nodes_total": metrics["graph_nodes_count"],
            "company_name": metrics.get("company_name"),
            "ticker": metrics.get("ticker"),
            "fiscal_period": metrics.get("fiscal_period"),
        })

        try:
            send_fn = getattr(producer, "send_and_wait", None) or producer.send
            res = send_fn(
                "document_status_events",
                key=tenant_id.encode("utf-8"),
                value=status_event.encode("utf-8"),
            )
            if asyncio.iscoroutine(res):
                await res
            logger.info("Published COMPLETED status event", document_id=document_id, **metrics)
        except Exception as e:
            logger.error("Failed to publish COMPLETED status event", error=str(e), document_id=document_id)