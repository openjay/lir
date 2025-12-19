"""
LIR Base Provider - Abstract interface for LLM providers

Defines the common interface that all providers must implement.
Supports async operations, health checks, and capability reporting.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ProviderStatus(Enum):
    """Provider health status"""
    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


@dataclass
class ProviderCapabilities:
    """
    Provider capability description.
    
    Attributes:
        name: Provider name
        supports_streaming: Whether provider supports streaming responses
        supports_batch: Whether provider supports batch requests
        supports_tool_calls: Whether provider supports function/tool calls
        max_context_length: Maximum context length in tokens
        default_model: Default model to use
        available_models: List of available models
    """
    name: str
    supports_streaming: bool = False
    supports_batch: bool = False
    supports_tool_calls: bool = False
    max_context_length: int = 4096
    default_model: Optional[str] = None
    available_models: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "name": self.name,
            "supports_streaming": self.supports_streaming,
            "supports_batch": self.supports_batch,
            "supports_tool_calls": self.supports_tool_calls,
            "max_context_length": self.max_context_length,
            "default_model": self.default_model,
            "available_models": self.available_models,
        }


@dataclass
class GenerationResult:
    """
    Result from a generation request.
    
    Attributes:
        text: Generated text
        model: Model used for generation
        provider: Provider name
        prompt_tokens: Number of prompt tokens (if available)
        completion_tokens: Number of completion tokens (if available)
        total_tokens: Total tokens used
        latency_ms: Generation latency in milliseconds
        metadata: Additional provider-specific metadata
    """
    text: str
    model: Optional[str] = None
    provider: Optional[str] = None
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    latency_ms: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "text": self.text,
            "model": self.model,
            "provider": self.provider,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "latency_ms": self.latency_ms,
            "metadata": self.metadata,
        }


class BaseProvider(ABC):
    """
    Abstract base class for LLM providers.
    
    All providers must implement:
    - generate(): Generate text from prompt
    - health_check(): Check provider health
    - get_capabilities(): Report provider capabilities
    
    Providers should also implement:
    - generate_batch(): Batch generation (if supported)
    - close(): Cleanup resources
    """
    
    def __init__(
        self,
        base_url: str,
        model: Optional[str] = None,
        timeout: float = 60.0,
        max_retries: int = 3,
        priority: int = 1,
    ):
        """
        Initialize provider.
        
        Args:
            base_url: Provider API base URL
            model: Model to use (None = use default)
            timeout: Request timeout in seconds
            max_retries: Max retry attempts on failure
            priority: Provider priority (lower = higher priority)
        """
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries
        self.priority = priority
        
        self._status = ProviderStatus.UNKNOWN
        self._last_error: Optional[str] = None
        self._request_count = 0
        self._error_count = 0
        self._total_tokens = 0
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Provider name"""
        pass
    
    @abstractmethod
    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.1,
        max_tokens: int = 500,
        **kwargs,
    ) -> GenerationResult:
        """
        Generate text from prompt.
        
        Args:
            prompt: User prompt
            system_prompt: Optional system context
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            **kwargs: Additional provider-specific options
            
        Returns:
            GenerationResult with generated text
            
        Raises:
            ProviderError: If generation fails
        """
        pass
    
    @abstractmethod
    async def health_check(self) -> bool:
        """
        Check if provider is healthy and accessible.
        
        Returns:
            True if healthy, False otherwise
        """
        pass
    
    @abstractmethod
    def get_capabilities(self) -> ProviderCapabilities:
        """
        Get provider capabilities.
        
        Returns:
            ProviderCapabilities describing provider features
        """
        pass
    
    async def generate_batch(
        self,
        prompts: List[str],
        system_prompts: Optional[List[Optional[str]]] = None,
        temperature: float = 0.1,
        max_tokens: int = 500,
        **kwargs,
    ) -> List[GenerationResult]:
        """
        Generate text for multiple prompts.
        
        Default implementation calls generate() sequentially.
        Providers can override for more efficient batch processing.
        
        Args:
            prompts: List of user prompts
            system_prompts: Optional list of system prompts (same length as prompts)
            temperature: Sampling temperature
            max_tokens: Maximum tokens per generation
            **kwargs: Additional provider-specific options
            
        Returns:
            List of GenerationResult for each prompt
        """
        if system_prompts is None:
            system_prompts = [None] * len(prompts)
        
        results = []
        for prompt, sys_prompt in zip(prompts, system_prompts):
            try:
                result = await self.generate(
                    prompt=prompt,
                    system_prompt=sys_prompt,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    **kwargs,
                )
                results.append(result)
            except Exception as e:
                logger.error("Batch generation failed for prompt: %s", e)
                results.append(GenerationResult(
                    text="",
                    provider=self.name,
                    metadata={"error": str(e)},
                ))
        
        return results
    
    async def close(self) -> None:
        """
        Cleanup provider resources.
        
        Override in subclasses that need cleanup (e.g., close HTTP sessions).
        """
        pass
    
    @property
    def status(self) -> ProviderStatus:
        """Current provider status"""
        return self._status
    
    @property
    def is_healthy(self) -> bool:
        """Check if provider is healthy"""
        return self._status == ProviderStatus.HEALTHY
    
    @property
    def last_error(self) -> Optional[str]:
        """Last error message"""
        return self._last_error
    
    def _record_success(self, tokens: int = 0) -> None:
        """Record successful request"""
        self._request_count += 1
        self._total_tokens += tokens
        self._status = ProviderStatus.HEALTHY
    
    def _record_error(self, error: str) -> None:
        """Record failed request"""
        self._request_count += 1
        self._error_count += 1
        self._last_error = error
        
        # Degrade status based on error rate
        error_rate = self._error_count / self._request_count if self._request_count > 0 else 0
        if error_rate > 0.5:
            self._status = ProviderStatus.UNHEALTHY
        elif error_rate > 0.2:
            self._status = ProviderStatus.DEGRADED
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get provider metrics"""
        return {
            "name": self.name,
            "base_url": self.base_url,
            "model": self.model,
            "priority": self.priority,
            "status": self._status.value,
            "request_count": self._request_count,
            "error_count": self._error_count,
            "error_rate": self._error_count / self._request_count if self._request_count > 0 else 0,
            "total_tokens": self._total_tokens,
            "last_error": self._last_error,
        }


class ProviderError(Exception):
    """Exception raised by providers"""
    
    def __init__(self, message: str, provider: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.provider = provider
        self.status_code = status_code

