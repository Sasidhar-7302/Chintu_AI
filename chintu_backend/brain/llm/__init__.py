"""LLM module - Ollama integration for local language model."""

from .airllm_client import AirLLMClient
from .ollama_client import OllamaClient

__all__ = ["OllamaClient", "AirLLMClient"]

