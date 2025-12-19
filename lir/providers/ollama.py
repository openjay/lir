"""
LIR Ollama Provider - Adapter for Ollama local LLM server

Supports:
- Ollama API (/api/generate, /api/tags)
- Connection pooling via aiohttp
- Streaming responses (optional)
- Model listing and selection
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

try:
    import aiohttp
    HAS_AIOHTTP = True
except ImportError:
    HAS_AIOHTTP = False

from .base import (
    BaseProvider,
    GenerationResult,
    ProviderCapabilities,
    ProviderError,
    ProviderStatus,
)

logger = logging.getLogger(__name__)


class OllamaProvider(BaseProvider):
    """
    Ollama provider adapter.
    
    Uses Ollama's native API:
    - POST /api/generate - Text generation
    - GET /api/tags - List available models
    
    Usage:
        provider = OllamaProvider(
            base_url="http://localhost:11434",
            model="qwen3:8b",
        )
        
        result = await provider.generate("Hello, world!")
    """
    
    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: Optional[str] = "qwen3:8b",
        timeout: float = 60.0,
        max_retries: int = 3,
        priority: int = 1,
    ):
        """
        Initialize Ollama provider.
        
        Args:
            base_url: Ollama server URL
            model: Model to use (default: qwen3:8b)
            timeout: Request timeout in seconds
            max_retries: Max retry attempts
            priority: Provider priority
        """
        super().__init__(
            base_url=base_url,
            model=model,
            timeout=timeout,
            max_retries=max_retries,
            priority=priority,
        )
        
        self._session: Optional[aiohttp.ClientSession] = None
        self._available_models: List[str] = []
    
    @property
    def name(self) -> str:
        return "ollama"
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session (connection pooling)"""
        if not HAS_AIOHTTP:
            raise ProviderError(
                "aiohttp not installed. Install with: pip install aiohttp",
                provider=self.name,
            )
        
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=self.timeout)
            self._session = aiohttp.ClientSession(timeout=timeout)
        
        return self._session
    
    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.1,
        max_tokens: int = 500,
        **kwargs,
    ) -> GenerationResult:
        """
        Generate text using Ollama API.
        
        Args:
            prompt: User prompt
            system_prompt: Optional system context
            temperature: Sampling temperature (0.0-1.0)
            max_tokens: Maximum tokens to generate
            **kwargs: Additional Ollama options
            
        Returns:
            GenerationResult with generated text
        """
        start_time = time.time()
        session = await self._get_session()
        
        # Build payload
        payload: Dict[str, Any] = {
            "model": self.model or "qwen3:8b",
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        
        if system_prompt:
            payload["system"] = system_prompt
        
        # Add any extra options
        if "options" in kwargs:
            payload["options"].update(kwargs["options"])
        
        url = f"{self.base_url}/api/generate"
        
        for attempt in range(self.max_retries):
            try:
                async with session.post(url, json=payload) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        raise ProviderError(
                            f"Ollama error {response.status}: {error_text}",
                            provider=self.name,
                            status_code=response.status,
                        )
                    
                    data = await response.json()
                    
                    text = data.get("response", "")
                    
                    # Calculate latency
                    latency_ms = (time.time() - start_time) * 1000
                    
                    # Extract token counts if available
                    prompt_tokens = data.get("prompt_eval_count")
                    completion_tokens = data.get("eval_count")
                    total_tokens = None
                    if prompt_tokens and completion_tokens:
                        total_tokens = prompt_tokens + completion_tokens
                    
                    self._record_success(total_tokens or 0)
                    
                    return GenerationResult(
                        text=text,
                        model=data.get("model", self.model),
                        provider=self.name,
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                        total_tokens=total_tokens,
                        latency_ms=latency_ms,
                        metadata={
                            "done": data.get("done"),
                            "context": data.get("context"),
                            "total_duration": data.get("total_duration"),
                            "load_duration": data.get("load_duration"),
                            "eval_duration": data.get("eval_duration"),
                        },
                    )
                    
            except aiohttp.ClientError as e:
                error_msg = f"Connection error (attempt {attempt + 1}/{self.max_retries}): {e}"
                logger.warning(error_msg)
                self._record_error(error_msg)
                
                if attempt == self.max_retries - 1:
                    raise ProviderError(error_msg, provider=self.name)
                
            except ProviderError:
                raise
                
            except Exception as e:
                error_msg = f"Unexpected error: {e}"
                logger.error(error_msg)
                self._record_error(error_msg)
                raise ProviderError(error_msg, provider=self.name)
        
        # Should not reach here
        raise ProviderError("Max retries exceeded", provider=self.name)
    
    async def health_check(self) -> bool:
        """
        Check Ollama health by listing models.
        
        Returns:
            True if Ollama is accessible and has models
        """
        try:
            session = await self._get_session()
            url = f"{self.base_url}/api/tags"
            
            async with session.get(url) as response:
                if response.status != 200:
                    self._status = ProviderStatus.UNHEALTHY
                    return False
                
                data = await response.json()
                models = data.get("models", [])
                self._available_models = [m.get("name", "") for m in models]
                
                self._status = ProviderStatus.HEALTHY
                return True
                
        except Exception as e:
            logger.warning("Ollama health check failed: %s", e)
            self._status = ProviderStatus.UNHEALTHY
            self._last_error = str(e)
            return False
    
    def get_capabilities(self) -> ProviderCapabilities:
        """Get Ollama capabilities"""
        return ProviderCapabilities(
            name=self.name,
            supports_streaming=True,
            supports_batch=False,  # Ollama doesn't have native batch API
            supports_tool_calls=False,  # Depends on model
            max_context_length=4096,  # Depends on model
            default_model=self.model or "qwen3:8b",
            available_models=self._available_models,
        )
    
    async def close(self) -> None:
        """Close aiohttp session"""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
    
    async def list_models(self) -> List[str]:
        """
        List available models.
        
        Returns:
            List of model names
        """
        try:
            session = await self._get_session()
            url = f"{self.base_url}/api/tags"
            
            async with session.get(url) as response:
                if response.status != 200:
                    return []
                
                data = await response.json()
                models = data.get("models", [])
                self._available_models = [m.get("name", "") for m in models]
                return self._available_models
                
        except Exception as e:
            logger.warning("Failed to list Ollama models: %s", e)
            return []

