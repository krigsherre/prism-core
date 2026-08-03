"""LLM Provider Strategy and Factory Pattern module for dynamic model resolution."""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from enum import Enum
from typing import Dict, Type, TypeVar

from langchain_anthropic import ChatAnthropic
from langchain_community.chat_models import ChatOllama
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import SystemMessage
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.runnables import RunnableLambda
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class ModelTier(Enum):
    FRONTIER = "frontier"
    STANDARD = "standard"


class BaseLLMProvider(ABC):
    """Abstract Strategy interface for building provider-specific ChatModel instances."""

    @abstractmethod
    def build(self, model_name: str, temperature: float) -> BaseChatModel:
        """Instantiate and configure the LangChain ChatModel."""
        pass

    @property
    def supports_native_tool_calling(self) -> bool:
        return True


class OpenAIProviderStrategy(BaseLLMProvider):
    """Strategy for OpenAI models."""

    def build(self, model_name: str, temperature: float) -> BaseChatModel:
        base_url = os.environ.get("OPENAI_BASE_URL") or os.environ.get("OPENAI_API_BASE")
        api_key = os.environ.get("OPENAI_API_KEY", "sk-local-dummy-key")
        kwargs = {
            "model": model_name,
            "temperature": temperature,
            "api_key": api_key,
            "streaming": True,
            "stream_options": {"include_usage": True},
        }
        if base_url:
            kwargs["base_url"] = base_url
        return ChatOpenAI(**kwargs)


class AnthropicProviderStrategy(BaseLLMProvider):
    """Strategy for Anthropic Claude models."""

    def build(self, model_name: str, temperature: float) -> BaseChatModel:
        api_key = os.environ.get("ANTHROPIC_API_KEY") or ""
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY is not set")
        return ChatAnthropic(
            model=model_name,
            api_key=api_key,
            temperature=temperature,
            streaming=True,
        )


class GoogleProviderStrategy(BaseLLMProvider):
    """Strategy for Google Gemini models."""

    def build(self, model_name: str, temperature: float) -> BaseChatModel:
        return ChatGoogleGenerativeAI(
            model=model_name,
            temperature=temperature,
            streaming=True,
        )


class VLLMProviderStrategy(BaseLLMProvider):
    """Strategy for self-hosted vLLM model endpoint."""

    def build(self, model_name: str, temperature: float) -> BaseChatModel:
        vllm_url = os.environ.get("VLLM_API_BASE", "http://vllm-server:8002")
        return ChatOpenAI(
            model=model_name,
            temperature=temperature,
            api_key=os.environ.get("VLLM_API_KEY", "EMPTY"),
            base_url=vllm_url,
            streaming=True,
        )


class OllamaProviderStrategy(BaseLLMProvider):
    """Strategy for local Ollama models."""

    @property
    def supports_native_tool_calling(self) -> bool:
        return False

    def build(self, model_name: str, temperature: float) -> BaseChatModel:
        ollama_url = (
            os.environ.get("OLLAMA_BASE_URL", "http://host.docker.internal:11434")
            .rstrip("/")
            .rstrip("/v1")
        )
        num_ctx = int(os.environ.get("OLLAMA_NUM_CTX", "16384"))
        return ChatOllama(
            model=model_name,
            temperature=temperature,
            base_url=ollama_url,
            num_ctx=num_ctx,
            streaming=True,
        )


class LLMProviderRegistry:
    """Registry maintaining available LLM strategies."""

    _strategies: Dict[str, BaseLLMProvider] = {
        "openai": OpenAIProviderStrategy(),
        "anthropic": AnthropicProviderStrategy(),
        "google": GoogleProviderStrategy(),
        "vllm": VLLMProviderStrategy(),
        "ollama": OllamaProviderStrategy(),
    }

    @classmethod
    def get_strategy(cls, provider: str) -> BaseLLMProvider:
        strategy = cls._strategies.get(provider.lower())
        if not strategy:
            raise ValueError(f"Unsupported LLM provider: {provider}")
        return strategy


class LLMFactory:
    """
    Extensible Strategy/Factory Pattern for resolving LLM models dynamically at runtime based on Tier.
    - FRONTIER: Used for complex routing (Supervisor).
    - STANDARD: Used for extraction/generation (SQL, Cypher).
    """

    @staticmethod
    def _resolve(tier: ModelTier) -> tuple[str, str, float]:
        """Return (provider, model_name, temperature) from environment."""
        default_provider = os.environ.get("LLM_PROVIDER", "openai").lower()
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
        """Instantiate ChatModel via LLMProviderRegistry strategy."""
        strategy = LLMProviderRegistry.get_strategy(provider)
        return strategy.build(model_name, temperature)

    @staticmethod
    def get_llm(tier: ModelTier = ModelTier.STANDARD) -> BaseChatModel:
        """Return a plain chat model for text generation."""
        provider, model_name, temperature = LLMFactory._resolve(tier)
        return LLMFactory._build(provider, model_name, temperature)

    @staticmethod
    def get_structured_llm(schema: Type[T], tier: ModelTier = ModelTier.STANDARD):
        """
        Return a runnable producing a validated Pydantic `schema` instance.
        Uses native tool calling if supported by provider strategy, or output parsing fallback.
        """
        provider, model_name, temperature = LLMFactory._resolve(tier)
        strategy = LLMProviderRegistry.get_strategy(provider)
        llm = strategy.build(model_name, temperature)

        if strategy.supports_native_tool_calling:
            return llm.with_structured_output(schema)

        parser = PydanticOutputParser(pydantic_object=schema)
        format_instructions = parser.get_format_instructions()

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
