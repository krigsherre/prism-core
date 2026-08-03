import asyncio
import json
import structlog
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from tenacity import retry, stop_after_attempt, wait_exponential
from typing import Optional, List
from pydantic import BaseModel, Field

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage, HumanMessage
from core.config import settings
from core.neo4j_client import neo4j_client

logger = structlog.get_logger(__name__)

class Triple(BaseModel):
    subject: str = Field(description="The source node entity (e.g., Company name, Person, Document).")
    predicate: str = Field(description="The relationship between the subject and object (e.g., OWNS, SIGNED, CONTAINS). Must be UPPERCASE and use underscores.")
    object: str = Field(description="The target node entity (e.g., Another company, Date, Amount).")

class KnowledgeGraph(BaseModel):
    triples: List[Triple] = Field(default_factory=list, description="A list of extracted relationship triples.")

class GraphConsumer:
    def __init__(self) -> None:
        self._consumer: Optional[AIOKafkaConsumer] = None
        self._producer: Optional[AIOKafkaProducer] = None
        
        from llm.factory import LLMFactory, ModelTier
        self._llm = LLMFactory.get_structured_llm(KnowledgeGraph, ModelTier.STANDARD)

    @retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, min=2, max=10), reraise=True)
    async def _connect(self) -> None:
        if self._consumer:
            await self._consumer.start()
        if self._producer:
            await self._producer.start()

    async def run(self) -> None:
        broker = settings.kafka_broker if hasattr(settings, 'kafka_broker') else "kafka:9092"
        self._consumer = AIOKafkaConsumer(
            "graph_extraction_tasks",
            bootstrap_servers=broker,
            group_id="agentic-brain-graph",
            auto_offset_reset="earliest",
            enable_auto_commit=False
        )
        self._producer = AIOKafkaProducer(bootstrap_servers=broker)
        
        try:
            await self._connect()
            logger.info("GraphConsumer started listening to graph_extraction_tasks")
            
            async for msg in self._consumer:
                await self._process_message(msg)
                await self._consumer.commit()
                
        except asyncio.CancelledError:
            logger.info("GraphConsumer cancelled")
        except Exception as e:
            logger.error("GraphConsumer failed", error=str(e))
        finally:
            if self._consumer:
                await self._consumer.stop()
            if self._producer:
                await self._producer.stop()
                
    async def _process_message(self, msg) -> None:
        try:
            payload = json.loads(msg.value.decode("utf-8"))
            document_id = payload.get("document_id")
            tenant_id = payload.get("tenant_id")
            text_content = payload.get("text_content")
            source_page = payload.get("source_page", 1)
            
            if not text_content or not self._is_high_signal_text(text_content):
                logger.debug("Skipping low-signal text fragment for graph ingestion", page=source_page)
                return

            structlog.contextvars.bind_contextvars(
                tenant_id=tenant_id, document_id=document_id
            )
            
            logger.info("Extracting high-signal graph triples from text node", node_id=payload.get("node_id"))
            
            messages = [
                SystemMessage(content=(
                    "You are an expert Financial Knowledge Graph Extractor. "
                    "Extract ONLY high-precision, strategic corporate & financial relationships as Subject-Predicate-Object triples. "
                    "Focus on: Subsidiary/Ownership, Key Executives/Directors, Audit Firms, Related Party Transactions, Debt/Facility Commitments, and Segment Revenues. "
                    "Ignore generic prose, page numbers, or unspecific terms. Keep entity names concise, specific, and clean."
                )),
                HumanMessage(content=f"Extract high-precision triples from the following text:\n\n{text_content}")
            ]
            
            try:
                result = await self._llm.ainvoke(messages)
                if isinstance(result, list):
                    result = KnowledgeGraph(triples=[])
            except Exception as parse_e:
                logger.debug("No valid triples parsed from text block", error=str(parse_e))
                result = KnowledgeGraph(triples=[])
            
            if not result or not hasattr(result, "triples") or not result.triples:
                logger.info("No triples extracted from text")
                return

            capped_triples = result.triples[:5]
            await self._ingest_triples_batch(capped_triples, document_id, tenant_id, source_page)
            logger.info("Successfully extracted and batch ingested graph triples", count=len(capped_triples))
            
        except Exception as e:
            logger.error("Failed to process graph extraction task", error=str(e))
        finally:
            if 'document_id' in locals() and document_id and 'tenant_id' in locals() and tenant_id and self._producer:
                try:
                    import datetime
                    status_payload = {
                        "document_id": document_id,
                        "tenant_id": tenant_id,
                        "graph_node_completed": True,
                        "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
                    }
                    await self._producer.send_and_wait(
                        "document_status_events",
                        key=tenant_id.encode("utf-8"),
                        value=json.dumps(status_payload).encode("utf-8")
                    )
                except Exception as status_e:
                    logger.error(f"Failed to emit graph status: {status_e}")

    def _is_high_signal_text(self, text: str) -> bool:
        """Filter out generic narrative text to control Neo4j ingestion volume."""
        if not text or len(text.strip()) < 40:
            return False
        import re
        patterns = [
            r"related\s+party",
            r"subsidiary",
            r"holding\s+company",
            r"joint\s+venture",
            r"director",
            r"key\s+managerial",
            r"kmp",
            r"auditor",
            r"guarantee",
            r"facility\s+agreement",
            r"borrowing",
            r"acquisition",
            r"merger",
            r"amalgamation",
            r"pledged?",
            r"contingent\s+liabilit",
            r"jurisdiction",
            r"ownership",
            r"exhibit\s+21",
            r"consolidation",
        ]
        return any(re.search(pat, text, re.IGNORECASE) for pat in patterns)

    def _canonicalize_entity(self, name: str) -> str:
        """Normalize entity names and filter out generic noise words to prevent Neo4j node pollution."""
        if not name:
            return ""
        import re
        clean = name.strip()
        clean = re.sub(r"[\s\.,]+$", "", clean).strip().upper()

        stop_entities = {
            "COMPANY", "THE COMPANY", "THE GROUP", "DIRECTORS", "NOTE", "NOTES",
            "MANAGEMENT", "BOARD", "THIS SECTION", "UNAUDITED", "AUDITED", "PAGE",
            "YEAR", "TOTAL", "AMOUNT", "FINANCIAL STATEMENTS", "STATEMENT", "CURRENCY",
            "NET REVENUE", "BALANCE SHEET", "INCOME STATEMENT", "ASSETS", "LIABILITIES"
        }
        if clean in stop_entities or len(clean) < 3:
            return ""
        return clean

    async def _ingest_triples_batch(self, triples: List[Triple], document_id: str, tenant_id: str, source_page: int) -> None:
        """High-performance UNWIND batch insertion into Neo4j in a single database roundtrip."""
        batch_data = []
        for t in triples:
            subject = self._canonicalize_entity(t.subject)
            obj = self._canonicalize_entity(t.object)
            if not subject or not obj or subject == obj:
                continue
            predicate = t.predicate.replace(" ", "_").replace("-", "_").upper()
            batch_data.append({
                "subject": subject,
                "predicate": predicate,
                "object": obj,
                "source_page": source_page
            })

        if not batch_data:
            return

        cypher_batch = """
        UNWIND $batch AS item
        MERGE (s:Entity {name: item.subject, tenant_id: $tenant_id})
        MERGE (o:Entity {name: item.object, tenant_id: $tenant_id})
        MERGE (s)-[r:RELATION {type: item.predicate}]->(o)
        SET r.document_id = $document_id, r.source_page = item.source_page
        """
        params = {
            "batch": batch_data,
            "tenant_id": tenant_id,
            "document_id": document_id
        }
        await neo4j_client.execute_write(cypher_batch, params)
