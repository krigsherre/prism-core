import os
from enum import Enum
from typing import Type, TypeVar
from pydantic import BaseModel
from langchain_community.chat_models import ChatOllama
from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.output_parsers import PydanticOutputParser

T = TypeVar("T", bound=BaseModel)

_TOOL_CALLING_PROVIDERS = {"openai", "anthropic", "google", "vllm"}


class ModelTier(Enum):
    FRONTIER = "frontier"
    STANDARD = "standard"


class LLMFactory:
    """
    Unified LLM Factory pattern for schema-aligner microservice.
    Supports Ollama, vLLM, OpenAI, and Anthropic seamlessly.
    """

    @staticmethod
    def _resolve(tier: ModelTier):
        default_provider = os.environ.get("LLM_PROVIDER", "ollama").lower()
        default_model = os.environ.get("LLM_MODEL", "qwen2.5:14b-instruct-q8_0 ")
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
        if provider == "openai":
            base_url = os.environ.get("OPENAI_BASE_URL") or os.environ.get("OPENAI_API_BASE")
            api_key = os.environ.get("OPENAI_API_KEY", "sk-local-dummy-key")
            kwargs = {"model": model_name, "temperature": temperature, "api_key": api_key}
            if base_url:
                kwargs["base_url"] = base_url
            return ChatOpenAI(**kwargs)
        elif provider == "anthropic":
            api_key = os.environ.get("ANTHROPIC_API_KEY") or ""
            return ChatAnthropic(model=model_name, api_key=api_key, temperature=temperature)
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
                .rstrip("/")
                .rstrip("/v1")
            )
            num_ctx = int(os.environ.get("OLLAMA_NUM_CTX", "16384"))
            return ChatOllama(
                model=model_name, temperature=temperature, base_url=ollama_url, num_ctx=num_ctx
            )
        else:
            base_url = (
                os.environ.get("OLLAMA_BASE_URL")
                or os.environ.get("OPENAI_BASE_URL")
                or "http://host.docker.internal:11434/v1"
            )
            return ChatOpenAI(model=model_name, temperature=temperature, base_url=base_url, api_key="ollama")

    @staticmethod
    def get_llm(tier: ModelTier = ModelTier.STANDARD) -> BaseChatModel:
        provider, model_name, temperature = LLMFactory._resolve(tier)
        return LLMFactory._build(provider, model_name, temperature)

    @staticmethod
    def get_structured_llm(schema: Type[T], tier: ModelTier = ModelTier.STANDARD):
        provider, model_name, temperature = LLMFactory._resolve(tier)
        llm = LLMFactory._build(provider, model_name, temperature)

        if provider in _TOOL_CALLING_PROVIDERS:
            return llm.with_structured_output(schema)

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
