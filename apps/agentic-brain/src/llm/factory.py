from langchain_community.chat_models import ChatOllama
from langchain_anthropic import ChatAnthropic
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI
from langchain_core.language_models.chat_models import BaseChatModel
import os
from enum import Enum

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
    def get_llm(tier: ModelTier = ModelTier.STANDARD) -> BaseChatModel:
        if tier == ModelTier.FRONTIER:
            provider = os.environ.get("FRONTIER_LLM_PROVIDER", "anthropic").lower()
            model_name = os.environ.get("FRONTIER_LLM_MODEL", "claude-haiku-4-5-20251001")
            temperature = float(os.environ.get("FRONTIER_LLM_TEMPERATURE", "0.0"))
        else:
            provider = os.environ.get("STANDARD_LLM_PROVIDER", "vllm").lower()
            model_name = os.environ.get("STANDARD_LLM_MODEL", "Qwen/Qwen2.5-7B-Instruct")
            temperature = float(os.environ.get("STANDARD_LLM_TEMPERATURE", "0.0"))
            
        if provider == "openai":
            return ChatOpenAI(model=model_name, temperature=temperature)
            
        elif provider == "anthropic":
            api_key = os.environ.get("ANTHROPIC_API_KEY") or ""
            if not api_key:
                raise ValueError("ANTHROPIC_API_KEY is not set")
            return ChatAnthropic(model=model_name, api_key=api_key)
            
        elif provider == "google":
            return ChatGoogleGenerativeAI(model=model_name, temperature=temperature)
            
        elif provider == "vllm":
            vllm_url = os.environ.get("VLLM_API_BASE", "http://vllm-server:8002")
            return ChatOpenAI(
                model=model_name, 
                temperature=temperature, 
                api_key=os.environ.get("VLLM_API_KEY", "EMPTY"), 
                base_url=vllm_url
            )
            
        elif provider == "ollama":
            return ChatOllama(model=model_name, temperature=temperature)
            
        else:
            raise ValueError(f"Unsupported LLM provider configured: {provider}")
