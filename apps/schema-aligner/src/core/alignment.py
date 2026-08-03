import json
import os
import asyncio
import structlog
from typing import Dict, Tuple, Any, List, Optional, Literal
from pydantic import BaseModel, Field, create_model
from opentelemetry import trace
from openai import AsyncOpenAI
import httpx
import instructor
from anthropic import AsyncAnthropic

from config.settings import settings
from core.verification import CriticAgent, FINANCIAL_SCHEMAS, Severity, merge_results, CriticResult
from core.financial_numerics import parse_financial_number, parse_scale_multiplier
from core.confidence import compute_confidence, band_to_status, PromotionBand
from core.doc_router import route_document
from core.rule_engine import load_packs
from core.reflexion import (
    FailureClass,
    ReflexionAttempt,
    ReflexionState,
    build_repair_instructions,
    classify_failure,
    merge_critic_error,
    tier_for_attempt,
)

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer(__name__)

LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "anthropic").lower()
MODEL_NAME = os.environ.get("LLM_MODEL", os.environ.get("VLLM_MODEL", "qwen2.5:14b-instruct-q8_0 "))

_FINANCIAL_HINTS = (
    "balance sheet", "income statement", "profit and loss", "p&l", "cash flow",
    "statement of financial", "bank statement", "invoice", "accounts payable",
    "accounts receivable", "ebitda", "shareholders", "retained earnings",
)

openai_base_url = (
    os.environ.get("OPENAI_BASE_URL")
    or os.environ.get("OPENAI_API_BASE")
    or os.environ.get("VLLM_API_BASE")
    or "http://vllm-server:8002"
)
openai_api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("VLLM_API_KEY") or "EMPTY"

if LLM_PROVIDER == "anthropic":
    llm_client = instructor.from_anthropic(
        AsyncAnthropic(
            api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
            http_client=httpx.AsyncClient(limits=httpx.Limits(max_connections=100, max_keepalive_connections=20))
        )
    )
else:
    llm_client = AsyncOpenAI(
        base_url=openai_base_url,
        api_key=openai_api_key,
        http_client=httpx.AsyncClient(limits=httpx.Limits(max_connections=100, max_keepalive_connections=20))
    )

class WaterfallAlignmentStrategy:
    """
    Schema alignment with structured outputs, financial casting, and fail-closed critics.
    """
    def __init__(self):
        self.schema_registry: Dict[str, Any] = {}
        self._load_schema_registry()
        self.financial_aliases: Dict[str, str] = self._load_financial_aliases()
        for pack in load_packs():
            self.financial_aliases.update(pack.aliases)
        
        self.synonym_cache: Dict[Tuple[str, str, str], str] = {}
        self._load_tenant_synonyms()
        self.critic_agent = CriticAgent()

    def _load_financial_aliases(self) -> Dict[str, str]:
        path = os.path.join(os.path.dirname(__file__), "financial_aliases.json")
        try:
            with open(path, "r") as f:
                raw = json.load(f)
            return {str(k).strip().lower(): str(v) for k, v in raw.items()}
        except Exception as e:
            logger.warning("Failed to load financial aliases", error=str(e))
            return {}

    async def _call_llm(self, messages: List[Dict[str, str]], response_model: Any, max_tokens: int = 1024, temperature: float = 0.0) -> Any:
        try:
            if LLM_PROVIDER == "anthropic":
                response = await llm_client.messages.create(
                    model=MODEL_NAME,
                    messages=messages,
                    response_model=response_model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
                return response
            else:
                response = await llm_client.beta.chat.completions.parse(
                    model=MODEL_NAME,
                    messages=messages,
                    response_format=response_model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    seed=int(os.environ.get("VLLM_SEED", "42")),
                    extra_body={"seed": int(os.environ.get("VLLM_SEED", "42"))},
                )
                return response.choices[0].message.parsed if response.choices and response.choices[0].message.parsed else None
        except Exception as e:
            logger.error("LLM call failed", error=str(e))
            return None

    @staticmethod
    def _structure_preflight(extracted_data: Dict[str, Any]) -> List[CriticResult]:
        """Honor upstream gpu-extractor table structure critic embedded as _structure."""
        struct = (extracted_data or {}).get("_structure")
        if not isinstance(struct, dict):
            return []
        results: List[CriticResult] = []
        for issue in struct.get("issues") or []:
            if not isinstance(issue, dict):
                continue
            sev = str(issue.get("severity") or "soft").lower()
            severity = Severity.HARD if sev == "hard" else Severity.SOFT
            results.append(
                CriticResult.fail(
                    str(issue.get("rule_id") or "table.structure"),
                    str(issue.get("message") or "table structure issue"),
                    severity=severity,
                    actionable_hint="Re-OCR or fix table grid; ragged/empty tables should not be force-aligned.",
                )
            )
        if struct.get("ok") is False and not results:
            results.append(
                CriticResult.fail(
                    "table.structure",
                    "Upstream table structure critic failed",
                    severity=Severity.HARD,
                )
            )
        return results

    def _load_schema_registry(self):
        registry_path = os.path.join(os.path.dirname(__file__), "registry.json")
        try:
            with open(registry_path, "r") as f:
                self.schema_registry = json.load(f)
            logger.info("Loaded schema registry from file")
        except Exception as e:
            logger.error("Failed to load schema registry", error=str(e))
            self.schema_registry = {}

    def update_schema(self, target_table: str, columns: Dict[str, Any]):
        self.schema_registry[target_table] = columns
        logger.info("Updated schema registry", target_table=target_table)

    def update_synonym(self, tenant_id: str, target_table: str, raw_label: str, mapped_column: str):
        self.synonym_cache[(tenant_id, target_table, raw_label)] = mapped_column
        self.synonym_cache[(tenant_id, target_table, str(raw_label).strip().lower())] = mapped_column
        logger.info("Updated synonym cache", tenant_id=tenant_id, target_table=target_table, raw_label=raw_label)
        self._persist_tenant_synonym(tenant_id, target_table, raw_label, mapped_column)

    def _tenant_synonyms_file(self) -> str:
        if settings.tenant_synonyms_path:
            return settings.tenant_synonyms_path
        return os.path.join(os.path.dirname(__file__), "tenant_synonyms.json")

    def _load_tenant_synonyms(self) -> None:
        path = self._tenant_synonyms_file()
        if not os.path.exists(path):
            return
        try:
            with open(path, "r") as f:
                raw = json.load(f)
            for tenant_id, tables in (raw or {}).items():
                if not isinstance(tables, dict):
                    continue
                for table, mapping in tables.items():
                    if not isinstance(mapping, dict):
                        continue
                    for raw_label, mapped in mapping.items():
                        self.synonym_cache[(tenant_id, table, raw_label)] = mapped
                        self.synonym_cache[(tenant_id, table, str(raw_label).strip().lower())] = mapped
            logger.info("Loaded tenant synonyms", path=path, count=len(self.synonym_cache))
        except Exception as e:
            logger.warning("Failed to load tenant synonyms", error=str(e))

    def _persist_tenant_synonym(
        self, tenant_id: str, target_table: str, raw_label: str, mapped_column: str
    ) -> None:
        path = self._tenant_synonyms_file()
        try:
            data: Dict[str, Any] = {}
            if os.path.exists(path):
                with open(path, "r") as f:
                    data = json.load(f) or {}
            data.setdefault(tenant_id, {}).setdefault(target_table, {})[raw_label] = mapped_column
            with open(path, "w") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning("Failed to persist tenant synonym", error=str(e))

    def _has_numeric_matrix(self, markdown_content: str) -> bool:
        """Check if markdown text contains a true multi-row numeric table matrix."""
        if not markdown_content:
            return False
        import re
        lines = [line for line in markdown_content.split("\n") if line.strip()]
        numeric_rows = sum(1 for line in lines if len(re.findall(r"\b\d+[\d,]*\.?\d*\b", line)) >= 1)
        return numeric_rows >= 2

    def _looks_financial(self, markdown_content: str, parent_section_text: str = "") -> bool:
        blob = f"{markdown_content}\n{parent_section_text}".lower()
        return any(h in blob for h in _FINANCIAL_HINTS)

    async def _classify_table(
        self,
        extracted_data: Dict[str, Any],
        markdown_content: str,
        parent_section_text: str = "",
    ) -> str:
        """Route via deterministic doc router first; fall back to LLM structured classify only for true financial tables."""
        with tracer.start_as_current_span("vllm_classify_table"):
            registry_keys = list(self.schema_registry.keys())
            blob = f"{parent_section_text}\n{markdown_content}"
            routed, score, _ = route_document(
                blob,
                allowed_schemas=registry_keys,
                min_score=float(settings.doc_router_min_score),
            )
            if routed:
                logger.info("Doc router classified table", schema=routed, score=score)
                return routed

            if not self._looks_financial(markdown_content, parent_section_text) and not self._has_numeric_matrix(markdown_content):
                logger.debug("Skipping table alignment for non-financial narrative block")
                return ""

            financial_first = [k for k in registry_keys if k in FINANCIAL_SCHEMAS]
            other = [k for k in registry_keys if k not in FINANCIAL_SCHEMAS]
            registry_keys = financial_first + other

            choices = registry_keys + ["UNKNOWN_TABLE"]
            if not choices:
                return ""
                
            schema_catalog = []
            for t_name in registry_keys:
                t_schema = self.schema_registry.get(t_name)
                if isinstance(t_schema, dict):
                    cols = ", ".join(t_schema.keys())
                    schema_catalog.append(f"- {t_name}: {cols}")
            catalog_str = "\n".join(schema_catalog)
            
            from enum import Enum
            ChoiceEnum = Enum("ChoiceEnum", {c: c for c in choices})
            
            class ClassificationResponse(BaseModel):
                table_name: ChoiceEnum = Field(..., description="The exact table name chosen from the catalog.")
                
            data_preview = markdown_content[:1500] if markdown_content else json.dumps(extracted_data)[:1500]
            section_preview = (parent_section_text or "")[:500]
            
            sys_prompt = (
                "You are an expert financial schema classifier. "
                "Prefer standardized_balance_sheet / standardized_income_statement / "
                "standardized_cash_flow / bank_statement_* / vendor_invoice_* when the content matches.\n"
                f"Available Schemas and their exact columns:\n{catalog_str}"
            )
            
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": f"Parent Section:\n{section_preview}\n\nExtracted Data:\n{data_preview}"}
            ]
            result = await self._call_llm(messages, ClassificationResponse, max_tokens=1024)
            return result.table_name.value if result else ""
            
    async def _classify_orientation(self, extracted_data: Dict[str, Any], markdown_content: str) -> str:
        """Deterministically identify table orientation (Pivot vs Standard) using LLM reasoning."""
        with tracer.start_as_current_span("vllm_classify_orientation"):
            class OrientationResponse(BaseModel):
                orientation: Literal["horizontal", "vertical"] = Field(..., description="horizontal = headers on top (standard). vertical = headers on the left (pivot).")
            data_preview = markdown_content[:1000] if markdown_content else json.dumps(extracted_data)[:1000]
            
            messages=[
                {"role": "system", "content": "You are a financial layout classifier. Determine the orientation of the table."},
                {"role": "user", "content": f"Table Preview:\n{data_preview}"}
            ]
            res = await self._call_llm(messages, OrientationResponse, max_tokens=1024)
            return res.orientation if res else "horizontal"

    async def align(
        self,
        tenant_id: str,
        target_table: str,
        extracted_data: Dict[str, Any],
        markdown_content: str = "",
        parent_section_text: str = "",
        reflexion_error: str = "",
        previous_extraction: Optional[List[Dict[str, Any]]] = None,
        attempt_index: int = 0,
        few_shot_examples: Optional[List[Dict[str, Any]]] = None,
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], str, str, List[str]]:
        """
        Single-pass schema alignment. Prefer align_with_reflexion() for production.
        """
        headers = list(extracted_data.keys()) if isinstance(extracted_data, dict) else []
        headers = [h for h in headers if not str(h).startswith("_")]

        preflight = self._structure_preflight(extracted_data if isinstance(extracted_data, dict) else {})
        preflight_hard = merge_results(
            [r for r in preflight if not r.ok and r.severity == Severity.HARD]
        )
        if not preflight_hard.ok:
            meta = self.critic_agent.annotate_meta({}, preflight)
            return [], [meta], "FAILED_VERIFICATION", target_table or "", headers
        
        target_table_task = None
        if not target_table:
            target_table_task = asyncio.create_task(self._classify_table(
                extracted_data, markdown_content, parent_section_text
            ))
            
        orientation_task = asyncio.create_task(self._classify_orientation(extracted_data, markdown_content))
        
        if target_table_task:
            target_table = await target_table_task
            if not target_table or target_table == "UNKNOWN_TABLE":
                return [], [extracted_data], "NEEDS_REVIEW", "", headers
                
        orientation = await orientation_task
        
        columnar_schema, StructuredResponse = self._build_dynamic_schema_model(target_table, orientation)
        sys_prompt = self._build_system_prompt(
            orientation,
            parent_section_text,
            target_table,
            reflexion_error=reflexion_error,
            previous_extraction=previous_extraction,
            attempt_index=attempt_index,
            few_shot_examples=few_shot_examples,
        )
        
        with tracer.start_as_current_span("vllm_deterministic_align"):
            merged_rows = await self._extract_chunks_concurrently(
                markdown_content, extracted_data, sys_prompt, StructuredResponse, target_table
            )
            
        if not merged_rows:
            return [], [], "FAILED", target_table, headers

        return await asyncio.to_thread(
            self._cast_and_verify_rows,
            merged_rows,
            columnar_schema,
            target_table,
            tenant_id,
            source_text=markdown_content or "",
        )

    async def align_with_reflexion(
        self,
        tenant_id: str,
        target_table: str,
        extracted_data: Dict[str, Any],
        markdown_content: str = "",
        parent_section_text: str = "",
        reflexion_error: str = "",
        previous_extraction: Optional[List[Dict[str, Any]]] = None,
        starting_attempt: int = 0,
        few_shot_examples: Optional[List[Dict[str, Any]]] = None,
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], str, str, List[str], Dict[str, Any]]:
        """
        Critic-guided repair ladder (up to max_reflexion_attempts).
        Returns (strict, unmapped, status, table, drifted, reflexion_meta).
        """
        max_attempts = max(1, int(settings.max_reflexion_attempts))
        state = ReflexionState(last_error=reflexion_error or "")
        if reflexion_error:
            state.failure_class = classify_failure(reflexion_error, status="FAILED_VERIFICATION", target_table=target_table)

        prev_rows = previous_extraction
        err = reflexion_error or ""
        last: Tuple[List[Dict[str, Any]], List[Dict[str, Any]], str, str, List[str]] = (
            [],
            [],
            "FAILED",
            target_table or "",
            [],
        )

        for local_i in range(max_attempts):
            attempt_index = starting_attempt + local_i
            if local_i > 0 and state.failure_class == FailureClass.PERMANENT:
                break

            tier = tier_for_attempt(attempt_index)
            logger.info(
                "Reflexion align attempt",
                attempt=attempt_index + 1,
                tier=tier,
                has_critic_error=bool(err),
                target_table=target_table,
            )

            strict, unmapped, status, table, drifted = await self.align(
                tenant_id=tenant_id,
                target_table=target_table or "",
                extracted_data=extracted_data,
                markdown_content=markdown_content,
                parent_section_text=parent_section_text,
                reflexion_error=err if attempt_index > 0 or err else "",
                previous_extraction=prev_rows if (attempt_index > 0 or prev_rows) else None,
                attempt_index=attempt_index,
                few_shot_examples=few_shot_examples,
            )
            last = (strict, unmapped, status, table, drifted)
            target_table = table or target_table

            critic_err = merge_critic_error(unmapped) or (
                "alignment produced no rows" if status == "FAILED" else ""
            )
            state.attempts.append(
                ReflexionAttempt(
                    attempt=attempt_index + 1,
                    tier=tier,
                    critic_error=critic_err,
                    status=status,
                )
            )
            state.last_error = critic_err
            state.failure_class = classify_failure(
                critic_err, status=status, target_table=table or target_table
            )

            if status not in ("FAILED_VERIFICATION", "FAILED"):
                meta = {
                    "attempts": state.attempt_count,
                    "attempt_errors": [a.critic_error for a in state.attempts if a.critic_error],
                    "failure_class": state.failure_class.value,
                    "exhausted": False,
                    "repaired": state.attempt_count > 1,
                }
                return strict, unmapped, status, table, drifted, meta

            if state.failure_class == FailureClass.PERMANENT:
                logger.warning(
                    "Permanent alignment failure — skipping further Reflexion",
                    error=critic_err,
                    status=status,
                )
                break
            err = critic_err
            prev_rows = strict if strict else prev_rows

        meta = {
            "attempts": state.attempt_count,
            "attempt_errors": [a.critic_error for a in state.attempts if a.critic_error],
            "failure_class": state.failure_class.value,
            "exhausted": True,
            "repaired": False,
        }
        strict, unmapped, status, table, drifted = last
        if unmapped:
            if not isinstance(unmapped[0], dict):
                unmapped[0] = {"_raw": unmapped[0]}
            unmapped[0]["reflexion_meta"] = meta
            if state.last_error and not unmapped[0].get("critic_error"):
                unmapped[0]["critic_error"] = state.last_error
        elif state.last_error:
            unmapped = [{"critic_error": state.last_error, "reflexion_meta": meta}]
        return strict, unmapped, status, table, drifted, meta


    def _build_dynamic_schema_model(self, target_table: str, orientation: str) -> Tuple[Dict[str, str], Any]:
        schema_def = self.schema_registry.get(target_table, {})
        columnar_schema = {"period_name": "str"} if orientation == "vertical" else {}
        
        for k in ["context_entity_name", "context_reporting_period", "context_currency", "context_scale"]:
            columnar_schema[k] = "str"
        columnar_schema.update(schema_def)
        
        fields = {}
        for k, v_type in columnar_schema.items():
            fields[k] = (Optional[str], Field(None, description=f"Extract the '{k}' metric directly from the table. Leave null if not found."))
            
        fields["additional_metadata"] = (Optional[Dict[str, Any]], Field(default_factory=dict, description="Any data in the row that does not map to the explicit fields above must be placed here as key-value pairs."))
        
        DynamicRow = create_model("DynamicRow", **fields)
        
        class StructuredResponse(BaseModel):
            data: List[DynamicRow] = Field(..., description="A JSON array of row objects.")
            
        return columnar_schema, StructuredResponse

    def _build_system_prompt(
        self,
        orientation: str,
        parent_section_text: str,
        target_table: str = "",
        reflexion_error: str = "",
        previous_extraction: Optional[List[Dict[str, Any]]] = None,
        attempt_index: int = 0,
        few_shot_examples: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        from .reflexion import format_few_shot_block

        financial_rules = ""
        if target_table in FINANCIAL_SCHEMAS:
            financial_rules = (
                "- FINANCIAL RULES:\n"
                "- Preserve accounting negatives: (123) or trailing '-' means negative.\n"
                "- Do NOT invent totals; copy figures exactly from the source cells.\n"
                "- For balance sheets ensure Assets / Liabilities / Equity fields are populated when present.\n"
                "- For income statements map Revenue, COGS, Gross Profit, OpEx, Net Income when present.\n"
                "- For cash flow map Operating / Investing / Financing / Net change when present.\n"
                "- Capture scale footnotes (in thousands/millions) into context_scale.\n"
            )
        repair = ""
        if reflexion_error or (attempt_index > 0 and previous_extraction):
            repair = build_repair_instructions(
                critic_error=reflexion_error or "previous attempt failed verification",
                previous_rows=previous_extraction,
                attempt_index=attempt_index,
                target_table=target_table,
                few_shot_examples=few_shot_examples,
            )
        few_shot = ""
        if few_shot_examples and not repair:
            few_shot = format_few_shot_block(few_shot_examples)
        return (
            f"Extract the provided Target Chunk into a JSON array of row objects.\n"
            f"CRITICAL INSTRUCTIONS:\n"
            f"- Return ONE JSON row object per record.\n"
            f"- The table orientation is {orientation}.\n"
            f"- Map data STRICTLY to the defined keys. If a metric exists but doesn't match a key, place it in 'additional_metadata'.\n"
            f"- Extract contextual metadata and add it to every row object: 'context_entity_name', 'context_reporting_period', 'context_currency', 'context_scale' from the Parent Section Text.\n"
            f"- You may be given 'Previous Context'. DO NOT extract rows from Previous Context. ONLY extract rows from the Target Chunk.\n"
            f"{financial_rules}"
            f"{few_shot}"
            f"{repair}"
            f"- Parent Section Text: {parent_section_text}"
        )

    async def _extract_chunks_concurrently(self, markdown_content: str, extracted_data: Dict[str, Any], sys_prompt: str, StructuredResponse: Any, target_table: str) -> List[Any]:
        chunks = self._generate_context_chunks(markdown_content, extracted_data)
        merged_rows = []
        
        async def _fetch_chunk(chunk_obj):
            target_str = chunk_obj["target"]
            ctx_str = chunk_obj["context"]
            
            user_content = f"Target Chunk:\n{target_str}"
            if ctx_str:
                user_content = f"Previous Context (DO NOT EXTRACT):\n{ctx_str}\n\n{user_content}"
                
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": user_content}
            ]
            res = await self._call_llm(messages, StructuredResponse, max_tokens=8192)
            return res.data if res else []

        try:
            tasks = [_fetch_chunk(c) for c in chunks]
            chunk_results = await asyncio.gather(*tasks)
            for res in chunk_results:
                merged_rows.extend(res)
            return merged_rows
        except Exception as e:
            logger.error("Holistic vLLM extraction failed", error=str(e), target_table=target_table)
            return []

    def _columnar_to_row_objects(self, extracted_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Convert columnar {header: [cells]} (or headers/rows) into a list of row dicts."""
        if not extracted_data:
            return []

        if "headers" in extracted_data and "rows" in extracted_data:
            headers = [str(h) for h in extracted_data["headers"]]
            rows = []
            for row in extracted_data.get("rows") or []:
                rows.append({headers[i]: (row[i] if i < len(row) else "") for i in range(len(headers))})
            return rows

        list_cols = {k: v for k, v in extracted_data.items() if isinstance(v, list)}
        if list_cols:
            headers = list(list_cols.keys())
            max_len = max((len(v) for v in list_cols.values()), default=0)
            rows = []
            for i in range(max_len):
                rows.append({h: (list_cols[h][i] if i < len(list_cols[h]) else "") for h in headers})
            return rows

        if all(not isinstance(v, (list, dict)) for v in extracted_data.values()):
            return [dict(extracted_data)]
        return []

    def _generate_context_chunks(self, markdown_content: str, extracted_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        CHUNK_SIZE = settings.chunk_size_rows
        OVERLAP = 3
        chunks = []

        row_objects = self._columnar_to_row_objects(extracted_data)
        if row_objects:
            num_rows = len(row_objects)
            if num_rows <= CHUNK_SIZE:
                chunks.append({"target": json.dumps(row_objects, ensure_ascii=False), "context": None})
            else:
                for i in range(0, num_rows, CHUNK_SIZE):
                    target_rows = row_objects[i : i + CHUNK_SIZE]
                    prev_context = None
                    if i > 0:
                        start_idx = max(0, i - OVERLAP)
                        prev_context = json.dumps(row_objects[start_idx:i], ensure_ascii=False)
                    chunks.append({
                        "target": json.dumps(target_rows, ensure_ascii=False),
                        "context": prev_context,
                    })
            return chunks

        if not markdown_content:
            return [{"target": json.dumps(extracted_data), "context": None}]

        lines = [line.strip() for line in markdown_content.split('\n') if line.strip()]
        if len(lines) > 2 and "|" in lines[0]:
            header = lines[0]
            separator = lines[1] if ("|" in lines[1] and "-" in lines[1]) else ""
            data_lines = lines[2:] if separator else lines[1:]

            num_rows = len(data_lines)
            if num_rows <= CHUNK_SIZE:
                chunks.append({"target": markdown_content, "context": None})
            else:
                for i in range(0, num_rows, CHUNK_SIZE):
                    chunk_lines = [header]
                    if separator:
                        chunk_lines.append(separator)
                    chunk_lines.extend(data_lines[i:i+CHUNK_SIZE])

                    prev_context = None
                    if i > 0:
                        start_idx = max(0, i - OVERLAP)
                        ctx_lines = [header]
                        if separator:
                            ctx_lines.append(separator)
                        ctx_lines.extend(data_lines[start_idx:i])
                        prev_context = "\n".join(ctx_lines)

                    chunks.append({"target": "\n".join(chunk_lines), "context": prev_context})
        else:
            chunks.append({"target": markdown_content, "context": None})

        return chunks

    def _unpivot_multi_period_table(self, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Unpivot comparative multi-year columns (e.g. 2024, 2023, 2022) into temporal rows."""
        unpivoted = []
        import re
        year_pattern = re.compile(r"^(?:fy)?(20\d\d|19\d\d)$", re.IGNORECASE)

        for row in rows:
            period_cols = {}
            base_row = {}
            for k, v in row.items():
                m = year_pattern.match(str(k).strip())
                if m:
                    period_cols[m.group(1)] = v
                else:
                    base_row[k] = v

            if period_cols and len(period_cols) > 1:
                for period_yr, val in period_cols.items():
                    new_row = dict(base_row)
                    new_row["context_reporting_period"] = period_yr
                    new_row["amount"] = val
                    new_row["is_restatement"] = False
                    unpivoted.append(new_row)
            else:
                unpivoted.append(row)
        return unpivoted

    def _apply_synonym_remap(
        self, tenant_id: str, target_table: str, meta: Dict[str, Any], row_dict: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Promote drifted headers into schema columns via tenant synonyms + financial aliases."""
        remaining: Dict[str, Any] = {}
        for raw_key, raw_val in (meta or {}).items():
            key_norm = str(raw_key).strip().lower()
            mapped_col = self.synonym_cache.get((tenant_id, target_table, raw_key))
            if not mapped_col:
                mapped_col = self.synonym_cache.get((tenant_id, target_table, key_norm))
            if not mapped_col:
                mapped_col = self.financial_aliases.get(key_norm)

            current = row_dict.get(mapped_col) if mapped_col else None
            empty = current is None or str(current).strip() == ""
            if mapped_col and mapped_col in row_dict and empty:
                row_dict[mapped_col] = raw_val
                logger.info(
                    "Remapped drifted header via synonym/alias",
                    raw_key=raw_key,
                    mapped_col=mapped_col,
                    target_table=target_table,
                )
            else:
                remaining[raw_key] = raw_val
        return remaining

    def _cast_value(self, value: Any, expected_type: str, field_name: Optional[str] = None) -> Any:
        if value is None:
            return None
        expected_type = expected_type.lower()
        if expected_type in ("float", "int"):
            parsed = parse_financial_number(value, field_name=field_name)
            if parsed is None:
                return None
            return int(parsed) if expected_type == "int" else float(parsed)
        return value

    def _cast_and_verify_rows(
        self,
        merged_rows: List[Any],
        columnar_schema: Dict[str, str],
        target_table: str,
        tenant_id: str = "default-tenant",
        source_text: str = "",
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], str, str, List[str]]:
        final_strict: List[Dict[str, Any]] = []
        final_unmapped: List[Dict[str, Any]] = []
        drifted_columns: List[str] = []
        mapping_status = "MAPPED"
        critic_errors: List[str] = []
        _META_KEYS = {
            "row_status",
            "critic_error",
            "reflexion_meta",
            "critic_results",
            "critic_version",
            "hard_failures",
            "soft_failures",
            "confidence_score",
            "promotion_band",
            "confidence_reasons",
        }

        structure = None
        if isinstance(source_text, str) and source_text.strip().startswith("{"):
            try:
                maybe = json.loads(source_text)
                if isinstance(maybe, dict) and "_structure" in maybe:
                    structure = maybe.get("_structure")
            except Exception:
                structure = None

        for row in merged_rows:
            raw_dict = row.model_dump() if hasattr(row, "model_dump") else dict(row)
            mapped_dict: Dict[str, Any] = {}
            meta = raw_dict.pop("additional_metadata", {}) or {}
            if not isinstance(meta, dict):
                meta = {"_raw_additional_metadata": meta}

            meta = self._apply_synonym_remap(tenant_id, target_table, meta, raw_dict)

            for k in meta.keys():
                if k not in drifted_columns:
                    drifted_columns.append(k)

            for k, v in raw_dict.items():
                expected_type = columnar_schema.get(k, "str")
                if isinstance(expected_type, str):
                    mapped_dict[k] = self._cast_value(v, expected_type, field_name=k)
                else:
                    mapped_dict[k] = v
            row_structure = mapped_dict.pop("_structure", None) or meta.pop("_structure", None) or structure

            scale_mult = parse_scale_multiplier(mapped_dict.get("context_scale"))
            if scale_mult != 1.0:
                mapped_dict["_context_scale_multiplier"] = scale_mult

            results = self.critic_agent.verify_detailed(
                target_table, mapped_dict, source_text=source_text
            )
            meta = self.critic_agent.annotate_meta(meta, results)
            hard = merge_results([r for r in results if not r.ok and r.severity == Severity.HARD])
            soft = merge_results([r for r in results if not r.ok and r.severity == Severity.SOFT])
            drift_only = {k: v for k, v in meta.items() if k not in _META_KEYS}

            metric_keys = [
                k for k in mapped_dict.keys()
                if not k.startswith("context_") and not k.startswith("_")
            ]
            populated_strict = sum(
                1 for k in metric_keys
                if mapped_dict.get(k) is not None and str(mapped_dict.get(k)).strip() != ""
            )
            total_fields = populated_strict + len(drift_only)
            unmapped_ratio = (len(drift_only) / total_fields) if total_fields else 0.0

            grounding_misses = sum(
                1 for r in results if (not r.ok) and r.rule_id.startswith("grounding.")
            )
            grounding_checked = grounding_misses + sum(
                1
                for k in (self.critic_agent._pack_grounding.get(target_table) or ())
                if mapped_dict.get(k) is not None
            )

            conf = compute_confidence(
                critic_results=results,
                structure=row_structure if isinstance(row_structure, dict) else None,
                drift_ratio=unmapped_ratio,
                grounding_misses=grounding_misses,
                grounding_checked=grounding_checked,
                auto_promote_min=float(settings.confidence_auto_promote_min),
                review_min=float(settings.confidence_review_min),
            )
            meta.update(conf.to_dict())
            status_from_conf = band_to_status(conf.band)

            if conf.band == PromotionBand.REJECT or not hard.ok:
                error_msg = hard.as_error_string() if not hard.ok else "; ".join(conf.reasons)
                logger.warning(
                    "Critic/confidence rejected row",
                    error=error_msg,
                    target_table=target_table,
                    band=conf.band.value,
                    confidence=conf.score,
                )
                mapping_status = "FAILED_VERIFICATION"
                meta["row_status"] = "FAILED_VERIFICATION"
                if error_msg:
                    meta["critic_error"] = error_msg or meta.get("critic_error")
                    critic_errors.append(error_msg)
            elif conf.band == PromotionBand.REVIEW or not soft.ok or drift_only or unmapped_ratio > 0.3:
                if not soft.ok:
                    critic_errors.append(soft.as_error_string())
                meta["row_status"] = "NEEDS_REVIEW"
                if mapping_status != "FAILED_VERIFICATION":
                    mapping_status = "NEEDS_REVIEW"
            else:
                meta["row_status"] = status_from_conf
                if mapping_status == "MAPPED":
                    mapping_status = status_from_conf

            final_strict.append(mapped_dict)
            final_unmapped.append(meta)

        doc_results = self.critic_agent.verify_document_detailed(
            target_table, final_strict, source_text=source_text
        )
        doc_hard = merge_results(
            [r for r in doc_results if not r.ok and r.severity == Severity.HARD]
        )
        if not doc_hard.ok:
            doc_err = doc_hard.as_error_string()
            logger.warning(
                "Document-level critic failed",
                error=doc_err,
                target_table=target_table,
                rule_id=doc_hard.rule_id,
            )
            mapping_status = "FAILED_VERIFICATION"
            critic_errors.append(doc_err)
            if final_unmapped:
                final_unmapped[0] = self.critic_agent.annotate_meta(final_unmapped[0], doc_results)
                if critic_errors:
                    final_unmapped[0]["critic_error"] = "; ".join(dict.fromkeys(critic_errors))

        if not final_strict:
            mapping_status = "NEEDS_REVIEW"

        return final_strict, final_unmapped, mapping_status, target_table, drifted_columns
