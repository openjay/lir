"""
LIR LM Studio Provider - Adapter for LM Studio local server

LM Studio provides an OpenAI-compatible API, making it easy to integrate.
Typically faster inference than Ollama for smaller models.

Supports:
- OpenAI-compatible /v1/chat/completions
- OpenAI-compatible /v1/models
- Connection pooling via aiohttp
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


class LMStudioProvider(BaseProvider):
    """
    LM Studio provider adapter.
    
    Uses OpenAI-compatible API:
    - POST /v1/chat/completions - Chat completion
    - GET /v1/models - List available models
    
    Usage:
        provider = LMStudioProvider(
            base_url="http://localhost:1234",
            model="llama-3.2-3b-instruct",
        )
        
        result = await provider.generate("Hello, world!")
    """
    
    def __init__(
        self,
        base_url: str = "http://localhost:1234",
        model: Optional[str] = "local-model",
        timeout: float = 60.0,
        max_retries: int = 3,
        priority: int = 2,
    ):
        """
        Initialize LM Studio provider.
        
        Args:
            base_url: LM Studio server URL
            model: Model to use (default: local-model)
            timeout: Request timeout in seconds
            max_retries: Max retry attempts
            priority: Provider priority (default 2 = backup to Ollama)
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
        return "lm_studio"
    
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
        Generate text using LM Studio's OpenAI-compatible API.
        
        Args:
            prompt: User prompt
            system_prompt: Optional system context
            temperature: Sampling temperature (0.0-1.0)
            max_tokens: Maximum tokens to generate
            **kwargs: Additional options
            
        Returns:
            GenerationResult with generated text
        """
        start_time = time.time()
        session = await self._get_session()
        
        # Build messages (OpenAI chat format)
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        
        # Build payload
        payload: Dict[str, Any] = {
            "model": self.model or "local-model",
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        
        # Add any extra options
        payload.update(kwargs)
        
        url = f"{self.base_url}/v1/chat/completions"
        
        for attempt in range(self.max_retries):
            try:
                async with session.post(url, json=payload) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        raise ProviderError(
                            f"LM Studio error {response.status}: {error_text}",
                            provider=self.name,
                            status_code=response.status,
                        )
                    
                    data = await response.json()
                    
                    # Extract text from OpenAI format
                    choices = data.get("choices", [])
                    if not choices:
                        raise ProviderError(
                            "No choices in response",
                            provider=self.name,
                        )
                    
                    text = choices[0].get("message", {}).get("content", "")
                    
                    # Calculate latency
                    latency_ms = (time.time() - start_time) * 1000
                    
                    # Extract token counts
                    usage = data.get("usage", {})
                    prompt_tokens = usage.get("prompt_tokens")
                    completion_tokens = usage.get("completion_tokens")
                    total_tokens = usage.get("total_tokens")
                    
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
                            "id": data.get("id"),
                            "object": data.get("object"),
                            "created": data.get("created"),
                            "finish_reason": choices[0].get("finish_reason"),
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
        Check LM Studio health by listing models.
        
        Returns:
            True if LM Studio is accessible
        """
        try:
            session = await self._get_session()
            url = f"{self.base_url}/v1/models"
            
            async with session.get(url) as response:
                if response.status != 200:
                    self._status = ProviderStatus.UNHEALTHY
                    return False
                
                data = await response.json()
                models = data.get("data", [])
                self._available_models = [m.get("id", "") for m in models]
                
                self._status = ProviderStatus.HEALTHY
                return True
                
        except Exception as e:
            logger.warning("LM Studio health check failed: %s", e)
            self._status = ProviderStatus.UNHEALTHY
            self._last_error = str(e)
            return False
    
    def get_capabilities(self) -> ProviderCapabilities:
        """Get LM Studio capabilities"""
        return ProviderCapabilities(
            name=self.name,
            supports_streaming=True,
            supports_batch=False,
            supports_tool_calls=True,  # OpenAI-compatible
            max_context_length=8192,  # Typically larger for LM Studio
            default_model=self.model or "local-model",
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
            List of model IDs
        """
        try:
            session = await self._get_session()
            url = f"{self.base_url}/v1/models"
            
            async with session.get(url) as response:
                if response.status != 200:
                    return []
                
                data = await response.json()
                models = data.get("data", [])
                self._available_models = [m.get("id", "") for m in models]
                return self._available_models
                
        except Exception as e:
            logger.warning("Failed to list LM Studio models: %s", e)
            return []

