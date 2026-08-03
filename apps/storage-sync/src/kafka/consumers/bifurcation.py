import asyncio
import os
import json
import httpx
import structlog
from typing import List
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from proto.prism.v1 import dom_pb2
from repositories.sql_repo import SQLRepository
from repositories.qdrant_repo import QdrantRepository
from config.settings import settings
from tenacity import retry, stop_after_attempt, wait_exponential
from kafka.consumers.chunk_assembler import ChunkDOMAssembler

logger = structlog.get_logger(__name__)

class DocumentRouter:
    """
    Strategy pattern for routing parsed document nodes to storage backends.
    """
    def __init__(self, sql_repo: SQLRepository, qdrant_repo: QdrantRepository, embeddings=None):
        self.sql_repo = sql_repo
        self.qdrant_repo = qdrant_repo
        self.embeddings = None
        self._http_client = httpx.AsyncClient(timeout=30.0)
        self._embedding_semaphore = asyncio.Semaphore(10)

    async def precompute_embeddings(self, nodes: list) -> dict:
        """Precompute TEI embeddings in batches to drastically improve throughput."""
        texts_to_embed = []
        
        def _collect(n_list):
            for n in n_list:
                if n.content and n.content.strip() and n.type != dom_pb2.NODE_TYPE_IMAGE:
                    texts_to_embed.append((n.id, n.content[:2000]))
                if len(n.children) > 0:
                    _collect(n.children)
                    
        _collect(nodes)
        
        if not texts_to_embed:
            return {}
            
        embeddings_map = {}
        batch_size = 8
        
        for i in range(0, len(texts_to_embed), batch_size):
            batch = texts_to_embed[i:i+batch_size]
            batch_ids = [item[0] for item in batch]
            batch_texts = [item[1] for item in batch]
            
            try:
                response = await self._http_client.post(
                    "http://embeddings-server:80/embed",
                    json={"inputs": batch_texts}
                )
                if response.status_code == 200:
                    data = response.json()
                    if isinstance(data, list):
                        for idx, b_id in enumerate(batch_ids):
                            if idx < len(data):
                                embeddings_map[b_id] = data[idx]
                else:
                    logger.error("TEI batch embedding returned non-200", status=response.status_code)
            except Exception as e:
                logger.error("TEI batch embedding failed", error=repr(e))
                
        return embeddings_map

    def _get_embedding(self, node: dom_pb2.Node, precomputed: dict) -> list:
        if precomputed and node.id in precomputed:
            return precomputed[node.id]
        return [1e-5] * 384

    _OTSL_MARKERS = ("<fcel>", "<nl>", "<ecel>", "<lcel>", "<ucel>")

    def _is_otsl(self, content: str) -> bool:
        return any(m in content for m in self._OTSL_MARKERS)

    def _headers_rows_to_columnar(self, headers: list, rows: list) -> dict:
        result = {str(h): [] for h in headers}
        for row in rows:
            for i, h in enumerate(headers):
                cell = str(row[i]) if i < len(row) else ""
                result[str(h)].append(cell)
        return result

    def _parse_otsl(self, content: str) -> dict:
        """Parse PaddleOCR-VL OTSL into columnar dict-of-arrays."""
        import re
        cleaned = content.strip().replace("<ecel>", "")
        row_strs = [r for r in cleaned.split("<nl>") if r.strip()]
        cell_split = re.compile(r"<fcel>|<lcel>|<ucel>")

        parsed_rows = []
        for row_str in row_strs:
            cells = cell_split.split(row_str)
            if cells and cells[0] == "" and len(cells) > 1:
                cells = cells[1:]
            cells = [c.strip() for c in cells]
            if cells:
                parsed_rows.append(cells)

        if not parsed_rows:
            return {}

        headers = parsed_rows[0]
        data_rows = parsed_rows[1:] if len(parsed_rows) > 1 else []
        width = len(headers)
        normalized = []
        for row in data_rows:
            if len(row) < width:
                row = row + [""] * (width - len(row))
            elif len(row) > width:
                row = row[:width]
            normalized.append(row)
        return self._headers_rows_to_columnar(headers, normalized)

    def _looks_like_kv_lines(self, content: str) -> bool:
        """Only treat multi-line Key: Value content as KV — never OTSL or currency-rate blobs."""
        if self._is_otsl(content):
            return False
        lines = [l.strip() for l in content.strip().split("\n") if l.strip()]
        if len(lines) < 1:
            return False
        if len(lines) == 1 and ("=" in lines[0] or len(lines[0]) > 200):
            return False
        kvish = 0
        for line in lines:
            if ": " in line or (line.count(":") == 1 and "=" not in line):
                kvish += 1
        return kvish >= max(1, len(lines) // 2)

    def _parse_table_content(self, content: str) -> dict:
        if not content:
            return {}

        try:
            parsed = json.loads(content)
            if isinstance(parsed, dict):
                if "headers" in parsed and "rows" in parsed:
                    headers = [str(h) for h in parsed["headers"]]
                    rows = parsed.get("rows") or []
                    columnar = self._headers_rows_to_columnar(headers, rows)
                    if isinstance(parsed.get("_structure"), dict):
                        columnar["_structure"] = parsed["_structure"]
                    return columnar
                data_keys = {k: v for k, v in parsed.items() if not str(k).startswith("_")}
                if data_keys and all(isinstance(v, list) for v in data_keys.values()):
                    out = dict(data_keys)
                    if isinstance(parsed.get("_structure"), dict):
                        out["_structure"] = parsed["_structure"]
                    return out
                if self._is_otsl(content) or any(
                    self._is_otsl(str(k)) or self._is_otsl(str(v)) for k, v in parsed.items()
                ):
                    parts = []
                    for k, v in parsed.items():
                        parts.append(str(k))
                        if isinstance(v, str):
                            parts.append(v)
                    return self._parse_otsl("".join(parts))
                if parsed and all(not isinstance(v, (list, dict)) for v in parsed.values()):
                    return parsed
        except (json.JSONDecodeError, TypeError):
            pass

        if self._is_otsl(content):
            return self._parse_otsl(content)

        lines = [l.strip() for l in content.strip().split("\n") if l.strip()]
        if not lines:
            return {}

        result = {}
        header_idx = -1
        for i, line in enumerate(lines):
            if "|" in line and (i + 1 < len(lines) and "---" in lines[i + 1]):
                header_idx = i
                break

        if header_idx == -1:
            for i, line in enumerate(lines):
                if "|" in line and len(line.split("|")) > 1:
                    header_idx = i
                    break

        if header_idx != -1:
            raw_headers = lines[header_idx].split("|")
            if raw_headers and raw_headers[0].strip() == "":
                raw_headers = raw_headers[1:]
            if raw_headers and raw_headers[-1].strip() == "":
                raw_headers = raw_headers[:-1]

            headers = []
            for i, h in enumerate(raw_headers):
                clean_h = h.strip()
                if not clean_h:
                    clean_h = f"col_{i}"
                headers.append(clean_h)

            for h in headers:
                result[h] = []

            if header_idx + 1 < len(lines) and "---" in lines[header_idx + 1]:
                data_lines = lines[header_idx + 2 :]
            else:
                data_lines = lines[header_idx + 1 :]

            for line in data_lines:
                if "|" not in line:
                    continue
                parts = line.split("|")
                if parts and parts[0].strip() == "":
                    parts = parts[1:]
                if parts and parts[-1].strip() == "":
                    parts = parts[:-1]

                cells = [c.strip() for c in parts]
                for i, h in enumerate(headers):
                    if i < len(cells):
                        result[h].append(cells[i])
                    else:
                        result[h].append("")

            if result and any(any(str(v).strip() for v in arr) for arr in result.values()):
                return result

        if self._looks_like_kv_lines(content):
            kv_res = self._parse_kv_content(content)
            if kv_res and any(v != "" for v in kv_res.values()):
                return kv_res

        return {f"header_{i+1}": line for i, line in enumerate(lines)}

    def _parse_kv_content(self, content: str) -> dict:
        if not content:
            return {}
        if self._is_otsl(content):
            return {}
        result = {}
        lines = [l.strip() for l in content.strip().split("\n") if l.strip()]
        for line in lines:
            if ": " in line or (":" in line and "=" not in line.split(":", 1)[0]):
                k, v = line.split(":", 1)
                result[k.strip()] = v.strip()
            elif line.count("=") == 1 and len(line) < 200:
                k, v = line.split("=", 1)
                if k.strip() and not any(ch.isdigit() for ch in k.strip()[:3]):
                    result[k.strip()] = v.strip()
        return result

    def _dict_to_markdown_table(self, data: dict) -> str:
        """Converts a flat dictionary of arrays into a Markdown table for semantic RAG."""
        if not data:
            return ""
        keys = [k for k in data.keys() if not str(k).startswith("_")]
        if not keys:
            return ""

        if all(not isinstance(data[k], list) for k in keys):
            md = "| " + " | ".join(keys) + " |\n"
            md += "|" + "|".join(["---" for _ in keys]) + "|\n"
            row = [str(data[k]).replace("|", "\\|").replace("\n", " ") for k in keys]
            md += "| " + " | ".join(row) + " |\n"
            return md.strip()

        md = "| " + " | ".join(keys) + " |\n"
        md += "|" + "|".join(["---" for _ in keys]) + "|\n"
        max_len = max([len(data[k]) if isinstance(data[k], list) else 1 for k in keys])
        for i in range(max_len):
            row = []
            for k in keys:
                arr = data[k]
                if isinstance(arr, list):
                    val = arr[i] if i < len(arr) else ""
                else:
                    val = arr if i == 0 else ""
                row.append(str(val).replace("|", "\\|").replace("\n", " "))
            md += "| " + " | ".join(row) + " |\n"

        return md.strip()

    def _normalize_header_key(self, key: str) -> str:
        return " ".join(str(key).strip().lower().split())

    def _columnar_headers(self, parsed: dict) -> List[str]:
        return [str(k) for k in parsed.keys()] if parsed else []

    def _headers_compatible(self, a: dict, b: dict) -> bool:
        """True when column sets match (order-insensitive) after normalization."""
        if not a or not b:
            return False
        ha = {self._normalize_header_key(k) for k in a.keys()}
        hb = {self._normalize_header_key(k) for k in b.keys()}
        if not ha or not hb:
            return False
        if ha == hb:
            return True
        overlap = ha & hb
        return len(overlap) >= max(2, int(0.8 * min(len(ha), len(hb))))

    def _page_number(self, node: dom_pb2.Node) -> int:
        if node.HasField("provenance"):
            return int(node.provenance.page_number or 0)
        return 0

    def _pages_adjacent(self, prev: dom_pb2.Node, curr: dom_pb2.Node) -> bool:
        p1 = self._page_number(prev)
        p2 = self._page_number(curr)
        if p1 <= 0 or p2 <= 0:
            return True
        return p2 in (p1, p1 + 1)

    def _is_weak_interstitial(self, node: dom_pb2.Node) -> bool:
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

    def _merge_columnar_tables(self, buf: dict, curr: dict) -> dict:
        """Append curr rows onto buf; align columns to buf header order."""
        merged = {k: list(v) if isinstance(v, list) else [v] for k, v in buf.items()}
        buf_by_norm = {self._normalize_header_key(k): k for k in merged.keys()}
        curr_len = 0
        for v in curr.values():
            if isinstance(v, list):
                curr_len = max(curr_len, len(v))
            else:
                curr_len = max(curr_len, 1)

        for norm, buf_key in buf_by_norm.items():
            match_val = None
            for ck, cv in curr.items():
                if self._normalize_header_key(ck) == norm:
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

    def _columnar_to_headers_rows_json(self, data: dict) -> str:
        headers = list(data.keys())
        if not headers:
            return json.dumps({"headers": [], "rows": []})
        max_len = max((len(v) if isinstance(v, list) else 1) for v in data.values())
        rows = []
        for i in range(max_len):
            row = []
            for h in headers:
                arr = data[h]
                if isinstance(arr, list):
                    row.append(str(arr[i]) if i < len(arr) else "")
                else:
                    row.append(str(arr) if i == 0 else "")
            rows.append(row)
        return json.dumps({"headers": headers, "rows": rows}, ensure_ascii=False)

    def _can_merge_tables(self, prev: dom_pb2.Node, curr: dom_pb2.Node) -> bool:
        if not self._pages_adjacent(prev, curr):
            return False
        buf_parsed = self._parse_table_content(prev.content)
        curr_parsed = self._parse_table_content(curr.content)
        if not buf_parsed or not curr_parsed:
            return False
        if all(not isinstance(v, list) for v in buf_parsed.values()):
            return False
        if all(not isinstance(v, list) for v in curr_parsed.values()):
            return False
        return self._headers_compatible(buf_parsed, curr_parsed)

    def _stitch_table_nodes(self, nodes: list) -> list:
        """
        Merge continued TABLE nodes across pages/chunks.
        Skips weak interstitial text (injected chunk context) between halves.
        """
        stitched = []
        table_buffer = None
        pending_weak: list = []

        def flush_buffer():
            nonlocal table_buffer, pending_weak
            if table_buffer is not None:
                stitched.append(table_buffer)
                table_buffer = None
            stitched.extend(pending_weak)
            pending_weak = []

        for node in nodes:
            if len(node.children) > 0:
                stitched_children = self._stitch_table_nodes(list(node.children))
                del node.children[:]
                node.children.extend(stitched_children)

            if node.type == dom_pb2.NODE_TYPE_TABLE:
                if table_buffer is None:
                    table_buffer = node
                    pending_weak = []
                    continue

                if self._can_merge_tables(table_buffer, node):
                    buf_parsed = self._parse_table_content(table_buffer.content)
                    curr_parsed = self._parse_table_content(node.content)
                    merged = self._merge_columnar_tables(buf_parsed, curr_parsed)
                    table_buffer.content = self._columnar_to_headers_rows_json(merged)
                    pending_weak = []
                    logger.info(
                        "Cross-chunk/page table stitch",
                        prev_page=self._page_number(table_buffer),
                        curr_page=self._page_number(node),
                        columns=len(merged),
                    )
                else:
                    flush_buffer()
                    table_buffer = node
            elif table_buffer is not None and self._is_weak_interstitial(node):
                pending_weak.append(node)
            else:
                flush_buffer()
                stitched.append(node)

        flush_buffer()
        return stitched

    async def route_node(
        self, tenant_id: str, document_id: str, node: dom_pb2.Node, 
        producer=None, parent_text: str = "", user_id: str = None, 
        siblings: list = None, node_index: int = 0,
        precomputed_embeddings: dict = None,
        point_batch: list = None
    ) -> dict:
        
        metrics = {
            "sql_mapped": False, "vector_mapped": False, "graph_mapped": False,
            "sql_nodes_count": 0, "graph_nodes_count": 0
        }
        
        try:
            prov = self._extract_provenance(node)
            full_context = self._build_full_context(parent_text, siblings, node_index)

            if node.type == dom_pb2.NODE_TYPE_TABLE:
                await self._route_table(tenant_id, document_id, node, producer, prov, full_context, parent_text, user_id, metrics, precomputed_embeddings, point_batch)
                
            elif node.type in (dom_pb2.NODE_TYPE_KEY_VALUE, dom_pb2.NODE_TYPE_FORM):
                await self._route_kv(tenant_id, document_id, node, producer, prov, full_context, parent_text, user_id, metrics, precomputed_embeddings, point_batch)
                
            elif node.type in (dom_pb2.NODE_TYPE_TEXT, dom_pb2.NODE_TYPE_SECTION_HEADER, dom_pb2.NODE_TYPE_TITLE, dom_pb2.NODE_TYPE_CHECKBOX, dom_pb2.NODE_TYPE_CODE):
                await self._route_unstructured(tenant_id, document_id, node, producer, prov, full_context, parent_text, user_id, metrics, precomputed_embeddings, point_batch)
                
            elif node.type == dom_pb2.NODE_TYPE_IMAGE:
                logger.info("Skipped IMAGE node routing (unsupported)", node_id=node.id)

            current_parent_text = node.content if node.type in (dom_pb2.NODE_TYPE_SECTION_HEADER, dom_pb2.NODE_TYPE_TITLE) else parent_text
            children = list(node.children)
            
            if children:
                async def process_child(i, child):
                    return await self.route_node(
                        tenant_id, document_id, child, producer, 
                        parent_text=current_parent_text, siblings=children, node_index=i,
                        precomputed_embeddings=precomputed_embeddings,
                        point_batch=point_batch
                    )
                child_tasks = [process_child(i, child) for i, child in enumerate(children)]
                child_results = await asyncio.gather(*child_tasks)
                for child_metrics in child_results:
                    self.merge_metrics(metrics, child_metrics)

        except Exception as e:
            logger.error("Failed to route node", error=str(e), node_id=node.id)
            
        return metrics

    def _extract_provenance(self, node: dom_pb2.Node) -> dict:
        if node.HasField("provenance"):
            return {
                "page_number": node.provenance.page_number,
                "bounding_box": list(node.provenance.bounding_box)
            }
        return {"page_number": 1, "bounding_box": [0, 0, 0, 0]}

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

    async def _route_table(self, tenant_id, document_id, node, producer, prov, full_context, parent_text, user_id, metrics, precomputed_embeddings, point_batch=None):
        extracted = self._parse_table_content(node.content)
        markdown = self._dict_to_markdown_table(extracted) if extracted else (node.content or "")
        payload = {
            "tenant_id": tenant_id, "document_id": document_id, "node_id": node.id,
            "target_table": "", "extracted_data": extracted,
            "markdown_content": markdown, "source_page": prov["page_number"],
            "source_bbox": prov["bounding_box"], "user_id": user_id,
            "parent_section_text": full_context
        }
        
        if producer:
            try:
                await producer.send("raw_table_doms", key=document_id.encode("utf-8"), value=json.dumps(payload).encode("utf-8"))
                logger.info("Routed table node to raw_table_doms topic", node_id=node.id)
                metrics["sql_mapped"] = True
                metrics["sql_nodes_count"] += 1
            except Exception as e:
                logger.error("Failed to send table to Kafka, skipping", error=str(e), node_id=node.id)

        async def _async_secondary_tasks():
            if producer:
                text_for_graph = f"{full_context}\n{markdown}"
                high_signal_patterns = [
                    r"related\s+party", r"subsidiary", r"holding\s+company", r"joint\s+venture",
                    r"director", r"key\s+managerial", r"kmp", r"auditor", r"guarantee",
                    r"facility\s+agreement", r"borrowing", r"acquisition", r"merger", r"amalgamation",
                    r"jurisdiction", r"ownership", r"exhibit\s+21", r"consolidation"
                ]
                import re
                if any(re.search(pat, text_for_graph, re.IGNORECASE) for pat in high_signal_patterns):
                    graph_payload = {
                        "tenant_id": tenant_id, "document_id": document_id, "node_id": node.id,
                        "text_content": text_for_graph, "parent_section_text": full_context,
                        "source_page": prov["page_number"], "source_bbox": prov["bounding_box"],
                        "user_id": user_id
                    }
                    try:
                        await producer.send("graph_extraction_tasks", key=document_id.encode("utf-8"), value=json.dumps(graph_payload).encode("utf-8"))
                        logger.info("Dual-routed corporate table node to graph_extraction_tasks", node_id=node.id)
                        metrics["graph_mapped"] = True
                        metrics["graph_nodes_count"] += 1
                    except Exception as e:
                        logger.error("Failed to route table to Graph Agent", error=str(e), node_id=node.id)

            if node.content and node.content.strip():
                try:
                    vector = self._get_embedding(node, precomputed_embeddings)
                    metadata = {
                        "tenant_id": tenant_id, "document_id": document_id, "node_id": node.id,
                        "node_type": "NODE_TYPE_TABLE", "content": node.content,
                        "parent_section_text": parent_text, "is_structured_table": True,
                        "source_page": prov["page_number"], "source_bbox": prov["bounding_box"],
                        "user_id": user_id
                    }
                    if point_batch is not None:
                        import uuid
                        from qdrant_client import models
                        qdrant_id = str(uuid.uuid5(uuid.NAMESPACE_OID, node.id))
                        point_batch.append(models.PointStruct(id=qdrant_id, vector=vector, payload=metadata))
                    else:
                        await self.qdrant_repo.upsert_vector(node_id=node.id, document_id=document_id, vector=vector, payload=metadata)
                    logger.info("Dual-routed table node to Qdrant Vector DB", node_id=node.id)
                    metrics["vector_mapped"] = True
                except Exception as e:
                    logger.error("Failed to embed table to Qdrant", error=str(e), node_id=node.id)

        import asyncio
        asyncio.create_task(_async_secondary_tasks())

    async def _route_kv(self, tenant_id, document_id, node, producer, prov, full_context, parent_text, user_id, metrics, precomputed_embeddings, point_batch=None):
        payload = {
            "tenant_id": tenant_id, "document_id": document_id, "node_id": node.id,
            "target_table": "", "extracted_data": self._parse_kv_content(node.content),
            "source_page": prov["page_number"], "source_bbox": prov["bounding_box"],
            "user_id": user_id, "parent_section_text": full_context
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
            high_signal_patterns = [
                r"related\s+party", r"subsidiary", r"holding\s+company", r"joint\s+venture",
                r"director", r"key\s+managerial", r"kmp", r"auditor", r"guarantee",
                r"facility\s+agreement", r"borrowing", r"acquisition", r"merger", r"amalgamation",
                r"jurisdiction", r"ownership", r"exhibit\s+21", r"consolidation"
            ]
            import re
            if any(re.search(pat, text_for_graph, re.IGNORECASE) for pat in high_signal_patterns):
                graph_payload = {
                    "tenant_id": tenant_id, "document_id": document_id, "node_id": node.id,
                    "text_content": text_for_graph, "parent_section_text": full_context,
                    "source_page": prov["page_number"], "source_bbox": prov["bounding_box"],
                    "user_id": user_id
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
                    "tenant_id": tenant_id, "document_id": document_id, "node_id": node.id,
                    "node_type": dom_pb2.NodeType.Name(node.type), "content": node.content,
                    "parent_section_text": parent_text, "is_key_value": True,
                    "source_page": prov["page_number"], "source_bbox": prov["bounding_box"]
                }
                if point_batch is not None:
                    import uuid
                    from qdrant_client import models
                    qdrant_id = str(uuid.uuid5(uuid.NAMESPACE_OID, node.id))
                    point_batch.append(models.PointStruct(id=qdrant_id, vector=vector, payload=metadata))
                else:
                    await self.qdrant_repo.upsert_vector(node_id=node.id, document_id=document_id, vector=vector, payload=metadata)
                logger.info("Dual-routed key-value/form node to Qdrant Vector DB", node_id=node.id)
                metrics["vector_mapped"] = True
            except Exception as e:
                logger.error("Failed to embed KV node to Qdrant", error=str(e), node_id=node.id)

    async def _route_unstructured(self, tenant_id, document_id, node, producer, prov, full_context, parent_text, user_id, metrics, precomputed_embeddings, point_batch=None):
        if not (node.content and node.content.strip()):
            return
            
        try:
            vector = self._get_embedding(node, precomputed_embeddings)
            type_name = dom_pb2.NodeType.Name(node.type)
            payload={
                "tenant_id": tenant_id,
                "text": node.content, "type": type_name,
                "parent_section_text": parent_text, "source_page": prov["page_number"],
                "source_bbox": prov["bounding_box"]
            }
            if point_batch is not None:
                import uuid
                from qdrant_client import models
                qdrant_id = str(uuid.uuid5(uuid.NAMESPACE_OID, node.id))
                point_batch.append(models.PointStruct(id=qdrant_id, vector=vector, payload=payload))
            else:
                await self.qdrant_repo.upsert_vector(
                    node_id=node.id, document_id=document_id, vector=vector,
                    payload=payload
                )
            logger.info("Routed node to Qdrant", node_id=node.id, node_type=type_name)
            metrics["vector_mapped"] = True
            
            if node.type == dom_pb2.NODE_TYPE_TEXT and producer:
                text = node.content or ""
                high_signal_patterns = [
                    r"related\s+party", r"subsidiary", r"holding\s+company", r"joint\s+venture",
                    r"director", r"key\s+managerial", r"kmp", r"auditor", r"guarantee",
                    r"facility\s+agreement", r"borrowing", r"acquisition", r"merger", r"amalgamation"
                ]
                import re
                is_high_signal = len(text.strip()) >= 50 and any(re.search(pat, text, re.IGNORECASE) for pat in high_signal_patterns)

                if is_high_signal:
                    graph_payload = {
                        "tenant_id": tenant_id, "document_id": document_id, "node_id": node.id,
                        "text_content": node.content, "parent_section_text": full_context,
                        "source_page": prov["page_number"], "source_bbox": prov["bounding_box"],
                        "user_id": user_id
                    }
                    try:
                        await producer.send_and_wait("graph_extraction_tasks", key=document_id.encode("utf-8"), value=json.dumps(graph_payload).encode("utf-8"))
                        logger.info("Routed text node to graph_extraction_tasks", node_id=node.id)
                        metrics["graph_mapped"] = True
                        metrics["graph_nodes_count"] += 1
                        metrics["graph_nodes_count"] += 1
                    except Exception as e:
                        logger.error("Failed to route node to Graph Agent", error=str(e), node_id=node.id)
                    
        except Exception as e:
            logger.error("Failed to route node to Qdrant", error=repr(e), node_id=node.id)


class BifurcationConsumer:
    def __init__(self, sql_repo: SQLRepository, qdrant_repo: QdrantRepository, embeddings=None) -> None:
        self.router = DocumentRouter(sql_repo, qdrant_repo, embeddings=embeddings)
        self.assembler = ChunkDOMAssembler(
            timeout_seconds=float(getattr(settings, "chunk_assemble_timeout_seconds", 900))
        )
        self._consumer = None
        self._producer = None

    @retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, min=2, max=10), reraise=True)
    async def _connect_kafka(self) -> None:
        if self._consumer:
            await self._consumer.start()
        if self._producer:
            await self._producer.start()

    async def run(self) -> None:
        self._consumer = AIOKafkaConsumer(
            "parsed_documents",
            bootstrap_servers=settings.kafka_broker,
            group_id=settings.kafka_consumer_group_bifurcation,
            auto_offset_reset="earliest"
        )
        self._producer = AIOKafkaProducer(bootstrap_servers=settings.kafka_broker)
        
        try:
            await self._connect_kafka()
        except Exception as e:
            logger.error("Failed to connect Bifurcation to Kafka", error=str(e))
            return
            
        logger.info("Bifurcation Consumer started...")
        
        try:
            async for msg in self._consumer:
                for tenant_id, assembled in self.assembler.flush_expired():
                    await self._process_document(tenant_id, assembled)
                await self._process_message(msg)
        except asyncio.CancelledError:
            logger.info("Bifurcation Consumer cancelled")
        except Exception as e:
            logger.error("Bifurcation Consumer failed unexpectedly", error=str(e))
        finally:
            if self._consumer:
                await self._consumer.stop()
            if self._producer:
                await self._producer.stop()

    async def _process_message(self, msg) -> None:
        tenant_id = msg.key.decode("utf-8") if msg.key else "unknown"
        dom = dom_pb2.DocumentDOM()
        
        try:
            dom.ParseFromString(msg.value)
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
        if not self._producer:
            return
        document_id = dom.document_id if dom.document_id else f"doc_{tenant_id}"
        user_id = dom.metadata.get("user_id", None) if dom.metadata else None
        
        for node in dom.nodes:
            if node.node_type in (dom_pb2.NODE_TYPE_TABLE, dom_pb2.NODE_TYPE_KEY_VALUE):
                prov = self._extract_provenance(node)
                full_context = self._get_parent_section_text(dom, node)
                extracted = self._parse_table_content(node.content) if node.node_type == dom_pb2.NODE_TYPE_TABLE else self._parse_kv_content(node.content)
                markdown = self._dict_to_markdown_table(extracted) if extracted and node.node_type == dom_pb2.NODE_TYPE_TABLE else (node.content or "")
                
                payload = {
                    "tenant_id": tenant_id, "document_id": document_id, "node_id": node.id,
                    "target_table": "", "extracted_data": extracted,
                    "markdown_content": markdown, "source_page": prov["page_number"],
                    "source_bbox": prov["bounding_box"], "user_id": user_id,
                    "parent_section_text": full_context
                }
                try:
                    await self._producer.send("raw_table_doms", key=document_id.encode("utf-8"), value=json.dumps(payload).encode("utf-8"))
                    logger.info("Streamed page-level table node to raw_table_doms immediately", node_id=node.id, page=prov["page_number"])
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
            "sql_mapped": False, "vector_mapped": False, "graph_mapped": False,
            "sql_nodes_count": 0, "graph_nodes_count": 0,
            "company_name": None, "ticker": None, "fiscal_period": None
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
            try:
                import httpx
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.post(
                        "http://agentic-brain:8000/api/internal/extract-metadata",
                        json={"text": sample_text}
                    )
                    if resp.status_code == 200:
                        meta_data = resp.json()
                        overall_metrics["company_name"] = meta_data.get("company_name")
                        overall_metrics["ticker"] = meta_data.get("ticker")
                        overall_metrics["fiscal_period"] = meta_data.get("fiscal_period")
                        logger.info("Extracted metadata", metadata=meta_data, document_id=document_id)
            except Exception as e:
                logger.error("Failed to extract metadata via internal API", error=str(e), document_id=document_id)
        
        stitched_nodes = self.router._stitch_table_nodes(list(dom.nodes))
        
        precomputed = await self.router.precompute_embeddings(stitched_nodes)
        
        point_batch = []
        async def process_node(i, node):
            return await self.router.route_node(
                tenant_id, document_id, node, self._producer,
                user_id=user_id, siblings=stitched_nodes, node_index=i,
                precomputed_embeddings=precomputed,
                point_batch=point_batch
            )

        tasks = [process_node(i, node) for i, node in enumerate(stitched_nodes)]
        results = await asyncio.gather(*tasks)
        
        if point_batch:
            batch_size = 256
            for i in range(0, len(point_batch), batch_size):
                chunk = point_batch[i:i+batch_size]
                try:
                    await self.router.qdrant_repo.upsert_batch(chunk)
                    logger.info("Upserted batch to Qdrant", batch_size=len(chunk), document_id=document_id)
                except Exception as e:
                    logger.error("Failed to upsert batch to Qdrant", error=str(e), document_id=document_id)
        
        for flags in results:
            self.router.merge_metrics(overall_metrics, flags)
            
        await self._publish_completion_status(tenant_id, document_id, filename, overall_metrics)

    async def _publish_completion_status(self, tenant_id: str, document_id: str, filename: str, metrics: dict) -> None:
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
            await self._producer.send_and_wait(
                "document_status_events",
                key=tenant_id.encode("utf-8"),
                value=status_event.encode("utf-8")
            )
            logger.info("Published COMPLETED status event", document_id=document_id, **metrics)
        except Exception as e:
            logger.error("Failed to publish COMPLETED status event", error=str(e), document_id=document_id)