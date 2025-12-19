"""
LIR Provider Adapters

Multi-provider support for local LLM inference.
Supports Ollama, LM Studio, and extensible for other providers.

Usage:
    from lir.providers import ProviderRouter, OllamaProvider, LMStudioProvider
    
    router = ProviderRouter([
        OllamaProvider(base_url="http://localhost:11434"),
        LMStudioProvider(base_url="http://localhost:1234"),
    ])
    
    result = await router.generate(prompt="Hello", system_prompt="Be helpful")
"""

from .base import BaseProvider, ProviderCapabilities, ProviderStatus
from .ollama import OllamaProvider
from .lmstudio import LMStudioProvider
from .router import ProviderRouter

__all__ = [
    "BaseProvider",
    "ProviderCapabilities",
    "ProviderStatus",
    "OllamaProvider",
    "LMStudioProvider",
    "ProviderRouter",
]

