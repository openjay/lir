"""
Local Inference Runtime (LIR)

A lightweight, OpenAI API-compatible local LLM inference optimization framework.
Provides scheduling, micro-batching, thermal management, and multi-provider support.

Usage:
    from lir import LIRClient
    
    client = LIRClient(policy="balanced")
    result = await client.generate("Hello, world!", system_prompt="You are helpful.")
    
    # Or sync wrapper for existing code
    from lir import SyncLIRClient
    
    client = SyncLIRClient(policy="balanced")
    result = client.generate("Hello, world!")

Policies:
    - "silent": Low concurrency, long batching window, conservative thermal limits
    - "balanced": Default, moderate concurrency, standard batching
    - "performance": High concurrency, short batching window, aggressive thermal limits

Architecture:
    Business Code → LIRClient → Scheduler → Batching → Governor → Providers → LLM
"""

from __future__ import annotations

__version__ = "0.1.0"
__author__ = "CodeWiki Team"

# Core exports
from .client import LIRClient, SyncLIRClient
from .scheduler import InferenceRequest, RequestQueue, ConcurrencyController
from .batching import BatchingEngine, Batch
from .governor import ThermalGovernor, ThermalState, ThermalMonitor
from .providers import BaseProvider, OllamaProvider, LMStudioProvider, ProviderRouter

__all__ = [
    # Version
    "__version__",
    # Client
    "LIRClient",
    "SyncLIRClient",
    # Scheduler
    "InferenceRequest",
    "RequestQueue",
    "ConcurrencyController",
    # Batching
    "BatchingEngine",
    "Batch",
    # Governor
    "ThermalGovernor",
    "ThermalState",
    "ThermalMonitor",
    # Providers
    "BaseProvider",
    "OllamaProvider",
    "LMStudioProvider",
    "ProviderRouter",
]

