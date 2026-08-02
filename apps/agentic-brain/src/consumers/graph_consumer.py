import asyncio
import json
import structlog
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from tenacity import retry, stop_after_attempt, wait_exponential
from typing import Optional, List
from pydantic import BaseModel, Field

from langchain_anthropic import ChatAnthropic
from langchain_core.prompts import ChatPromptTemplate
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
        
        model_name = settings.frontier_llm_model if settings.frontier_llm_model else "claude-haiku-4-5-20251001"
        self._llm = ChatAnthropic(
            model=model_name,
            api_key=settings.anthropic_api_key,
            temperature=0,
            max_tokens=2048,
        ).with_structured_output(KnowledgeGraph)

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
            
            if not text_content:
                return

            structlog.contextvars.bind_contextvars(
                tenant_id=tenant_id, document_id=document_id
            )
            
            logger.info("Extracting graph triples from text node", node_id=payload.get("node_id"))
            
            prompt = ChatPromptTemplate.from_messages([
                ("system", "You are an expert Graph Data Extractor. Extract all meaningful relationships from the provided text as Subject-Predicate-Object triples. Keep entities concise and clean."),
                ("user", "Extract triples from the following text:\n\n{text}")
            ])
            
            chain = prompt | self._llm
            result: KnowledgeGraph = await chain.ainvoke({"text": text_content})
            
            if not result or not result.triples:
                logger.info("No triples extracted from text")
                return
                
            for triple in result.triples:
                await self._ingest_triple(triple, document_id, tenant_id, source_page)
                
            logger.info("Successfully extracted and ingested graph triples", count=len(result.triples))
            
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

    async def _ingest_triple(self, triple: Triple, document_id: str, tenant_id: str, source_page: int) -> None:
        predicate = triple.predicate.replace(" ", "_").replace("-", "_").upper()

        query = f"""
        MERGE (s:Entity {{name: $subject, tenant_id: $tenant_id}})
        MERGE (o:Entity {{name: $object, tenant_id: $tenant_id}})
        MERGE (s)-[r:{predicate}]->(o)
        SET r.document_id = $document_id, r.source_page = $source_page
        """
        params = {
            "subject": triple.subject,
            "object": triple.object,
            "tenant_id": tenant_id,
            "document_id": document_id,
            "source_page": source_page
        }
        await neo4j_client.execute_write(query, params)
