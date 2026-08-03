from langchain_community.chat_models import ChatOllama
from langchain_anthropic import ChatAnthropic
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.output_parsers import PydanticOutputParser
from pydantic import BaseModel
from typing import Type, TypeVar
import os
from enum import Enum

T = TypeVar("T", bound=BaseModel)

# Providers that natively support tool/function calling via OpenAI-compatible schema.
# These can safely use .with_structured_output() directly.
_TOOL_CALLING_PROVIDERS = {"openai", "anthropic", "google", "vllm"}

class ModelTier(Enum):
    FRONTIER = "frontier"
    STANDARD = "standard"

class LLMFactory:
    """
    Extensible Strategy/Factory Pattern for resolving LLM models dynamically at runtime based on Tier.
    - FRONTIER: Used for complex routing (Supervisor).
    - STANDARD: Used for extraction/generation (SQL, Cypher).
    """
    
    @staticmethod
    def _resolve(tier: ModelTier):
        """Return (provider, model_name, temperature) from environment."""
        default_provider = os.environ.get("LLM_PROVIDER", "openai").lower()
        default_model = os.environ.get("LLM_MODEL", "qwen2.5:14b")
        if tier == ModelTier.FRONTIER:
            provider = os.environ.get("FRONTIER_LLM_PROVIDER", default_provider).lower()
            model_name = os.environ.get("FRONTIER_LLM_MODEL", default_model)
            temperature = float(os.environ.get("FRONTIER_LLM_TEMPERATURE", "0.0"))
        else:
            provider = os.environ.get("STANDARD_LLM_PROVIDER", default_provider).lower()
            model_name = os.environ.get("STANDARD_LLM_MODEL", default_model)
            temperature = float(os.environ.get("STANDARD_LLM_TEMPERATURE", "0.0"))
        return provider, model_name, temperature

    @staticmethod
    def _build(provider: str, model_name: str, temperature: float) -> BaseChatModel:
        """Instantiate the correct LangChain chat model."""
        if provider == "openai":
            base_url = os.environ.get("OPENAI_BASE_URL") or os.environ.get("OPENAI_API_BASE")
            api_key = os.environ.get("OPENAI_API_KEY", "sk-local-dummy-key")
            kwargs = {"model": model_name, "temperature": temperature, "api_key": api_key}
            if base_url:
                kwargs["base_url"] = base_url
            return ChatOpenAI(**kwargs)
        elif provider == "anthropic":
            api_key = os.environ.get("ANTHROPIC_API_KEY") or ""
            if not api_key:
                raise ValueError("ANTHROPIC_API_KEY is not set")
            return ChatAnthropic(model=model_name, api_key=api_key, temperature=temperature)
        elif provider == "google":
            return ChatGoogleGenerativeAI(model=model_name, temperature=temperature)
        elif provider == "vllm":
            vllm_url = os.environ.get("VLLM_API_BASE", "http://vllm-server:8002")
            return ChatOpenAI(
                model=model_name,
                temperature=temperature,
                api_key=os.environ.get("VLLM_API_KEY", "EMPTY"),
                base_url=vllm_url,
            )
        elif provider == "ollama":
            ollama_url = (
                os.environ.get("OLLAMA_BASE_URL", "http://host.docker.internal:11434")
                .rstrip("/").rstrip("/v1")
            )
            return ChatOllama(model=model_name, temperature=temperature, base_url=ollama_url)
        else:
            raise ValueError(f"Unsupported LLM provider: {provider}")

    @staticmethod
    def get_llm(tier: ModelTier = ModelTier.STANDARD) -> BaseChatModel:
        """Return a plain chat model for free-form text generation."""
        provider, model_name, temperature = LLMFactory._resolve(tier)
        return LLMFactory._build(provider, model_name, temperature)

    @staticmethod
    def get_structured_llm(schema: Type[T], tier: ModelTier = ModelTier.STANDARD):
        """
        Return a runnable producing a validated Pydantic `schema` instance.

        Cloud providers (openai, anthropic, google, vllm):
            Uses .with_structured_output(schema) — native tool/function calling.

        Local providers (ollama):
            Injects JSON format instructions into the system prompt and parses
            the model's text output via PydanticOutputParser. No function calling needed.
        """
        provider, model_name, temperature = LLMFactory._resolve(tier)
        llm = LLMFactory._build(provider, model_name, temperature)

        if provider in _TOOL_CALLING_PROVIDERS:
            return llm.with_structured_output(schema)

        # ── JSON + PydanticOutputParser fallback for local models ─────────────
        parser = PydanticOutputParser(pydantic_object=schema)
        format_instructions = parser.get_format_instructions()

        from langchain_core.runnables import RunnableLambda
        from langchain_core.messages import SystemMessage

        def _inject_format(messages):
            return [
                SystemMessage(content=f"{m.content}\n\n{format_instructions}")
                if isinstance(m, SystemMessage)
                else m
                for m in messages
            ]

        def _invoke(messages):
            raw = llm.invoke(_inject_format(messages))
            return parser.parse(raw.content if hasattr(raw, "content") else str(raw))

        async def _ainvoke(messages):
            raw = await llm.ainvoke(_inject_format(messages))
            return parser.parse(raw.content if hasattr(raw, "content") else str(raw))

        return RunnableLambda(_invoke, afunc=_ainvoke)

