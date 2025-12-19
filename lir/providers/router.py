"""
LIR Provider Router - Intelligent provider selection and routing

Features:
- Priority-based provider selection
- Automatic failover on errors
- Thermal-aware routing (switch to faster provider when hot)
- Health check integration
- Load balancing (future)

Usage:
    router = ProviderRouter([
        OllamaProvider(base_url="http://localhost:11434", priority=1),
        LMStudioProvider(base_url="http://localhost:1234", priority=2),
    ])
    
    # Initialize and check health
    await router.initialize()
    
    # Generate with automatic provider selection
    result = await router.generate("Hello, world!")
    
    # Or specify provider
    result = await router.generate("Hello", provider="lm_studio")
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

from .base import (
    BaseProvider,
    GenerationResult,
    ProviderCapabilities,
    ProviderError,
    ProviderStatus,
)

logger = logging.getLogger(__name__)


class ProviderRouter:
    """
    Intelligent provider router with failover and routing strategies.
    
    Supports:
    - Priority-based selection (lower priority number = higher preference)
    - Automatic failover on provider errors
    - Thermal-aware routing (prefer faster providers when system is hot)
    - Manual provider selection
    """
    
    def __init__(
        self,
        providers: List[BaseProvider],
        prefer_fast_when_hot: bool = True,
    ):
        """
        Initialize provider router.
        
        Args:
            providers: List of provider instances
            prefer_fast_when_hot: When True, prefer faster providers during thermal stress
        """
        self.providers = sorted(providers, key=lambda p: p.priority)
        self.prefer_fast_when_hot = prefer_fast_when_hot
        
        self._active_provider: Optional[BaseProvider] = None
        self._is_hot = False  # Set by thermal governor
        self._initialized = False
        
        # Provider lookup by name
        self._provider_map: Dict[str, BaseProvider] = {
            p.name: p for p in providers
        }
    
    async def initialize(self) -> bool:
        """
        Initialize router by checking all provider health.
        
        Returns:
            True if at least one provider is healthy
        """
        healthy_count = 0
        
        for provider in self.providers:
            try:
                is_healthy = await provider.health_check()
                if is_healthy:
                    healthy_count += 1
                    logger.info(
                        "Provider %s is healthy (priority=%d)",
                        provider.name,
                        provider.priority,
                    )
                else:
                    logger.warning(
                        "Provider %s is unhealthy",
                        provider.name,
                    )
            except Exception as e:
                logger.warning(
                    "Provider %s health check failed: %s",
                    provider.name,
                    e,
                )
        
        # Select active provider
        self._active_provider = self._select_provider()
        self._initialized = True
        
        if self._active_provider:
            logger.info(
                "Active provider: %s (%s)",
                self._active_provider.name,
                self._active_provider.base_url,
            )
        else:
            logger.warning("No healthy providers available")
        
        return healthy_count > 0
    
    def _select_provider(self, exclude: Optional[str] = None) -> Optional[BaseProvider]:
        """
        Select best available provider.
        
        Args:
            exclude: Provider name to exclude (for failover)
            
        Returns:
            Best available provider or None
        """
        candidates = [
            p for p in self.providers
            if p.is_healthy and (exclude is None or p.name != exclude)
        ]
        
        if not candidates:
            # Fall back to any provider if none healthy
            candidates = [
                p for p in self.providers
                if exclude is None or p.name != exclude
            ]
        
        if not candidates:
            return None
        
        # If hot and prefer_fast_when_hot, prefer LM Studio (typically faster)
        if self._is_hot and self.prefer_fast_when_hot:
            for p in candidates:
                if p.name == "lm_studio":
                    return p
        
        # Return highest priority (lowest number)
        return candidates[0]
    
    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.1,
        max_tokens: int = 500,
        provider: Optional[str] = None,
        **kwargs,
    ) -> GenerationResult:
        """
        Generate text with automatic provider selection and failover.
        
        Args:
            prompt: User prompt
            system_prompt: Optional system context
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            provider: Specific provider to use (None = auto-select)
            **kwargs: Additional provider options
            
        Returns:
            GenerationResult with generated text
            
        Raises:
            ProviderError: If all providers fail
        """
        if not self._initialized:
            await self.initialize()
        
        # Select provider
        if provider:
            selected = self._provider_map.get(provider)
            if not selected:
                raise ProviderError(
                    f"Unknown provider: {provider}",
                    provider="router",
                )
        else:
            selected = self._active_provider or self._select_provider()
        
        if not selected:
            raise ProviderError(
                "No providers available",
                provider="router",
            )
        
        # Try selected provider, then failover
        tried_providers = set()
        last_error: Optional[Exception] = None
        
        while selected and selected.name not in tried_providers:
            tried_providers.add(selected.name)
            
            try:
                result = await selected.generate(
                    prompt=prompt,
                    system_prompt=system_prompt,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    **kwargs,
                )
                
                # Update active provider on success
                self._active_provider = selected
                return result
                
            except ProviderError as e:
                logger.warning(
                    "Provider %s failed: %s, trying failover",
                    selected.name,
                    e,
                )
                last_error = e
                
                # Try next provider
                selected = self._select_provider(exclude=selected.name)
                
            except Exception as e:
                logger.error(
                    "Unexpected error from provider %s: %s",
                    selected.name,
                    e,
                )
                last_error = e
                selected = self._select_provider(exclude=selected.name)
        
        # All providers failed
        raise ProviderError(
            f"All providers failed. Last error: {last_error}",
            provider="router",
        )
    
    async def generate_batch(
        self,
        prompts: List[str],
        system_prompts: Optional[List[Optional[str]]] = None,
        temperature: float = 0.1,
        max_tokens: int = 500,
        provider: Optional[str] = None,
        **kwargs,
    ) -> List[GenerationResult]:
        """
        Generate text for multiple prompts.
        
        Args:
            prompts: List of user prompts
            system_prompts: Optional list of system prompts
            temperature: Sampling temperature
            max_tokens: Maximum tokens per generation
            provider: Specific provider to use
            **kwargs: Additional options
            
        Returns:
            List of GenerationResult
        """
        if not self._initialized:
            await self.initialize()
        
        # Select provider
        if provider:
            selected = self._provider_map.get(provider)
        else:
            selected = self._active_provider or self._select_provider()
        
        if not selected:
            raise ProviderError(
                "No providers available",
                provider="router",
            )
        
        return await selected.generate_batch(
            prompts=prompts,
            system_prompts=system_prompts,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )
    
    def set_thermal_state(self, is_hot: bool) -> None:
        """
        Update thermal state for routing decisions.
        
        Args:
            is_hot: True if system is thermally stressed
        """
        if is_hot != self._is_hot:
            self._is_hot = is_hot
            
            if is_hot and self.prefer_fast_when_hot:
                # Re-select provider to prefer faster one
                new_provider = self._select_provider()
                if new_provider and new_provider != self._active_provider:
                    logger.info(
                        "Thermal routing: switching from %s to %s",
                        self._active_provider.name if self._active_provider else "none",
                        new_provider.name,
                    )
                    self._active_provider = new_provider
    
    @property
    def active_provider(self) -> Optional[BaseProvider]:
        """Currently active provider"""
        return self._active_provider
    
    @property
    def is_available(self) -> bool:
        """Check if any provider is available"""
        return self._active_provider is not None
    
    async def health_check_all(self) -> Dict[str, bool]:
        """
        Run health check on all providers.
        
        Returns:
            Dict mapping provider name to health status
        """
        results = {}
        for provider in self.providers:
            try:
                results[provider.name] = await provider.health_check()
            except Exception:
                results[provider.name] = False
        return results
    
    async def close(self) -> None:
        """Close all provider connections"""
        for provider in self.providers:
            try:
                await provider.close()
            except Exception as e:
                logger.warning(
                    "Error closing provider %s: %s",
                    provider.name,
                    e,
                )
    
    def get_provider(self, name: str) -> Optional[BaseProvider]:
        """Get provider by name"""
        return self._provider_map.get(name)
    
    def get_capabilities(self) -> Dict[str, ProviderCapabilities]:
        """Get capabilities of all providers"""
        return {
            p.name: p.get_capabilities()
            for p in self.providers
        }
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get router metrics"""
        return {
            "initialized": self._initialized,
            "active_provider": self._active_provider.name if self._active_provider else None,
            "is_hot": self._is_hot,
            "prefer_fast_when_hot": self.prefer_fast_when_hot,
            "providers": {
                p.name: p.get_metrics()
                for p in self.providers
            },
        }

