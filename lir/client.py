"""
LIR Client - Main SDK Interface

The primary interface for using the Local Inference Runtime.
Provides both async and sync APIs for flexibility.

Features:
- OpenAI-style interface (familiar API)
- Automatic batching and scheduling
- Thermal-aware throttling
- Multi-provider support with failover
- Comprehensive metrics

Usage:
    # Async usage (recommended)
    async with LIRClient(policy="balanced") as client:
        result = await client.generate("Hello, world!")
    
    # Sync usage (for existing sync code)
    client = SyncLIRClient(policy="balanced")
    result = client.generate("Hello, world!")
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import yaml

from .scheduler import InferenceRequest, Scheduler
from .batching import BatchingEngine, Batch, BatchProcessor
from .governor import ThermalGovernor, ThermalState
from .providers import (
    BaseProvider,
    OllamaProvider,
    LMStudioProvider,
    ProviderRouter,
)

logger = logging.getLogger(__name__)

# Default policies
DEFAULT_POLICIES = {
    "silent": {
        "max_concurrent_requests": 1,
        "max_tokens_inflight": 4096,
        "batch_window_ms": 100,
        "max_batch_size": 5,
        "thermal_policy": "conservative",
    },
    "balanced": {
        "max_concurrent_requests": 3,
        "max_tokens_inflight": 8192,
        "batch_window_ms": 40,
        "max_batch_size": 10,
        "thermal_policy": "normal",
    },
    "performance": {
        "max_concurrent_requests": 6,
        "max_tokens_inflight": 16384,
        "batch_window_ms": 20,
        "max_batch_size": 20,
        "thermal_policy": "aggressive",
    },
}


class LIRClient:
    """
    Main LIR client for async usage.
    
    Combines scheduler, batching, thermal governor, and provider router
    into a single easy-to-use interface.
    
    Usage:
        # Context manager (recommended)
        async with LIRClient(policy="balanced") as client:
            result = await client.generate("Hello!")
        
        # Manual lifecycle
        client = LIRClient(policy="balanced")
        await client.start()
        result = await client.generate("Hello!")
        await client.stop()
    """
    
    def __init__(
        self,
        policy: str = "balanced",
        config_path: Optional[Path] = None,
        providers: Optional[List[BaseProvider]] = None,
        ollama_url: str = "http://localhost:11434",
        lmstudio_url: str = "http://localhost:1234",
        ollama_model: str = "qwen3:8b",
        lmstudio_model: str = "local-model",
    ):
        """
        Initialize LIR client.
        
        Args:
            policy: Policy name ("silent", "balanced", "performance")
            config_path: Optional path to custom config YAML
            providers: Optional custom provider list (overrides URLs)
            ollama_url: Ollama server URL
            lmstudio_url: LM Studio server URL
            ollama_model: Ollama model name
            lmstudio_model: LM Studio model name
        """
        self.policy_name = policy
        self.config_path = config_path
        
        # Load policy
        self.policy = self._load_policy(policy, config_path)
        
        # Initialize providers
        if providers:
            self.providers = providers
        else:
            self.providers = [
                OllamaProvider(
                    base_url=ollama_url,
                    model=ollama_model,
                    priority=1,
                ),
                LMStudioProvider(
                    base_url=lmstudio_url,
                    model=lmstudio_model,
                    priority=2,
                ),
            ]
        
        # Initialize components
        self.router = ProviderRouter(
            providers=self.providers,
            prefer_fast_when_hot=True,
        )
        
        self.scheduler = Scheduler(
            max_concurrent_requests=self.policy["max_concurrent_requests"],
            max_tokens_inflight=self.policy["max_tokens_inflight"],
            max_queue_depth=100,
        )
        
        self.batching = BatchingEngine(
            window_ms=self.policy["batch_window_ms"],
            max_batch_size=self.policy["max_batch_size"],
        )
        
        self.governor = ThermalGovernor(
            policy=self.policy["thermal_policy"],
            base_max_concurrent=self.policy["max_concurrent_requests"],
            base_batch_window_ms=self.policy["batch_window_ms"],
            on_state_change=self._on_thermal_state_change,
        )
        
        # State
        self._running = False
        self._processor_task: Optional[asyncio.Task] = None
        self._start_time: Optional[float] = None
        
        # Metrics
        self._total_requests = 0
        self._total_tokens = 0
        self._total_latency = 0.0
    
    def _load_policy(self, policy_name: str, config_path: Optional[Path]) -> Dict[str, Any]:
        """Load policy from config or defaults"""
        # Try loading from config file
        if config_path and config_path.exists():
            try:
                with open(config_path) as f:
                    config = yaml.safe_load(f)
                    policies = config.get("policies", {})
                    if policy_name in policies:
                        return {**DEFAULT_POLICIES["balanced"], **policies[policy_name]}
            except Exception as e:
                logger.warning("Failed to load config from %s: %s", config_path, e)
        
        # Fall back to defaults
        return DEFAULT_POLICIES.get(policy_name, DEFAULT_POLICIES["balanced"])
    
    def _on_thermal_state_change(self, old_state: ThermalState, new_state: ThermalState) -> None:
        """Handle thermal state changes"""
        # Update router thermal state
        is_hot = new_state in (ThermalState.HOT, ThermalState.CRITICAL)
        self.router.set_thermal_state(is_hot)
        
        # Update scheduler limits
        limits = self.governor.get_adjusted_limits()
        self.scheduler.update_limits(
            max_concurrent_requests=limits["max_concurrent_requests"],
        )
        
        # Update batching window
        self.batching.update_window(limits["batch_window_ms"])
    
    async def start(self) -> None:
        """Start the LIR client"""
        if self._running:
            return
        
        logger.info("Starting LIR client (policy=%s)", self.policy_name)
        
        # Initialize router
        await self.router.initialize()
        
        # Start thermal governor
        await self.governor.start()
        
        # Start processor task
        self._running = True
        self._start_time = time.time()
        self._processor_task = asyncio.create_task(self._process_loop())
        
        logger.info("LIR client started")
    
    async def stop(self) -> None:
        """Stop the LIR client"""
        if not self._running:
            return
        
        logger.info("Stopping LIR client")
        
        self._running = False
        
        # Stop processor
        if self._processor_task:
            self._processor_task.cancel()
            try:
                await self._processor_task
            except asyncio.CancelledError:
                pass
        
        # Flush remaining batches
        batch = await self.batching.flush()
        if batch:
            await self._process_batch(batch)
        
        # Stop governor
        await self.governor.stop()
        
        # Close providers
        await self.router.close()
        
        logger.info("LIR client stopped")
    
    async def __aenter__(self) -> "LIRClient":
        """Async context manager entry"""
        await self.start()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit"""
        await self.stop()
    
    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.1,
        max_tokens: int = 500,
        **kwargs,
    ) -> Optional[str]:
        """
        Generate text from prompt.
        
        This is the main API method. Requests are automatically
        batched and scheduled for optimal performance.
        
        Args:
            prompt: User prompt
            system_prompt: Optional system context
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            **kwargs: Additional provider options
            
        Returns:
            Generated text or None on failure
        """
        if not self._running:
            await self.start()
        
        # Check thermal state
        if self.governor.should_pause():
            logger.warning("System critical, cooling down before processing")
            await self.governor.cooldown()
        
        # Create request
        request = InferenceRequest(
            prompt=prompt,
            system_prompt=system_prompt,
            metadata={
                "temperature": temperature,
                "max_tokens": max_tokens,
                **kwargs,
            },
        )
        
        # Create future for result
        loop = asyncio.get_event_loop()
        request._future = loop.create_future()
        
        # Add to batching engine
        await self.batching.add(request)
        
        # Wait for result
        try:
            result = await request._future
            self._total_requests += 1
            if request.total_time:
                self._total_latency += request.total_time
            return result
        except Exception as e:
            logger.error("Generation failed: %s", e)
            return None
    
    async def generate_batch(
        self,
        prompts: List[str],
        system_prompts: Optional[List[Optional[str]]] = None,
        temperature: float = 0.1,
        max_tokens: int = 500,
        **kwargs,
    ) -> List[Optional[str]]:
        """
        Generate text for multiple prompts.
        
        More efficient than calling generate() multiple times
        as requests are batched together.
        
        Args:
            prompts: List of user prompts
            system_prompts: Optional list of system prompts
            temperature: Sampling temperature
            max_tokens: Maximum tokens per generation
            **kwargs: Additional provider options
            
        Returns:
            List of generated texts (None for failures)
        """
        if system_prompts is None:
            system_prompts = [None] * len(prompts)
        
        # Submit all requests
        futures = []
        for prompt, sys_prompt in zip(prompts, system_prompts):
            future = asyncio.ensure_future(
                self.generate(
                    prompt=prompt,
                    system_prompt=sys_prompt,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    **kwargs,
                )
            )
            futures.append(future)
        
        # Wait for all results
        results = await asyncio.gather(*futures, return_exceptions=True)
        
        # Convert exceptions to None
        return [
            r if isinstance(r, str) else None
            for r in results
        ]
    
    async def _process_loop(self) -> None:
        """Main processing loop"""
        while self._running:
            try:
                # Get batch when ready
                batch = await self.batching.get_batch()
                
                if batch:
                    # Check thermal state
                    if self.governor.should_throttle():
                        await self.governor.cooldown()
                    
                    # Process batch
                    await self._process_batch(batch)
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error in process loop: %s", e)
                await asyncio.sleep(0.1)
    
    async def _process_batch(self, batch: Batch) -> None:
        """Process a single batch"""
        try:
            batch.mark_started()
            
            logger.debug(
                "Processing batch %s (%d requests)",
                batch.batch_id,
                batch.size,
            )
            
            # Get generation parameters from first request
            metadata = batch.requests[0].metadata if batch.requests else {}
            temperature = metadata.get("temperature", 0.1)
            max_tokens = metadata.get("max_tokens", 500)
            
            # Generate using router
            results = await self.router.generate_batch(
                prompts=batch.prompts,
                system_prompts=batch.system_prompts,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            
            # Extract text from results
            texts = [r.text if r else None for r in results]
            
            # Update token count
            for r in results:
                if r and r.total_tokens:
                    self._total_tokens += r.total_tokens
            
            # Complete batch
            batch.complete(texts)
            
            logger.debug(
                "Completed batch %s in %.2fs",
                batch.batch_id,
                batch.processing_time or 0,
            )
            
        except Exception as e:
            logger.error("Batch %s failed: %s", batch.batch_id, e)
            batch.fail(str(e))
    
    def is_available(self) -> bool:
        """Check if client is ready to process requests"""
        return self._running and self.router.is_available
    
    def set_policy(self, policy: str) -> None:
        """
        Change policy at runtime.
        
        Args:
            policy: Policy name ("silent", "balanced", "performance")
        """
        if policy not in DEFAULT_POLICIES:
            logger.warning("Unknown policy: %s", policy)
            return
        
        self.policy_name = policy
        self.policy = DEFAULT_POLICIES[policy]
        
        # Update components
        self.scheduler.update_limits(
            max_concurrent_requests=self.policy["max_concurrent_requests"],
            max_tokens_inflight=self.policy["max_tokens_inflight"],
        )
        self.batching.update_window(self.policy["batch_window_ms"])
        self.governor.set_policy(self.policy["thermal_policy"])
        
        logger.info("Policy changed to: %s", policy)
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get comprehensive metrics"""
        uptime = time.time() - self._start_time if self._start_time else 0
        avg_latency = self._total_latency / self._total_requests if self._total_requests > 0 else 0
        
        return {
            "client": {
                "policy": self.policy_name,
                "running": self._running,
                "uptime_seconds": uptime,
                "total_requests": self._total_requests,
                "total_tokens": self._total_tokens,
                "average_latency_seconds": avg_latency,
            },
            "scheduler": self.scheduler.get_metrics(),
            "batching": self.batching.get_metrics(),
            "governor": self.governor.get_metrics(),
            "router": self.router.get_metrics(),
        }


class SyncLIRClient:
    """
    Synchronous wrapper for LIRClient.
    
    For use in existing synchronous code that can't use async/await.
    Creates an event loop internally.
    
    Usage:
        # Context manager (recommended - ensures cleanup)
        with SyncLIRClient(policy="balanced") as client:
            result = client.generate("Hello, world!")
        
        # Manual lifecycle
        client = SyncLIRClient(policy="balanced")
        result = client.generate("Hello, world!")
        client.close()  # Important: always call close()
    """
    
    def __init__(
        self,
        policy: str = "balanced",
        config_path: Optional[Path] = None,
        **kwargs,
    ):
        """
        Initialize sync client.
        
        Args:
            policy: Policy name
            config_path: Optional config path
            **kwargs: Additional LIRClient options
        """
        self._loop = asyncio.new_event_loop()
        self._client = LIRClient(
            policy=policy,
            config_path=config_path,
            **kwargs,
        )
        self._started = False
        self._closed = False
    
    def _ensure_started(self) -> None:
        """Ensure client is started"""
        if self._closed:
            raise RuntimeError("Client has been closed")
        if not self._started:
            self._loop.run_until_complete(self._client.start())
            self._started = True
    
    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.1,
        max_tokens: int = 500,
        **kwargs,
    ) -> Optional[str]:
        """
        Generate text from prompt (synchronous).
        
        Args:
            prompt: User prompt
            system_prompt: Optional system context
            temperature: Sampling temperature
            max_tokens: Maximum tokens
            **kwargs: Additional options
            
        Returns:
            Generated text or None
        """
        self._ensure_started()
        return self._loop.run_until_complete(
            self._client.generate(
                prompt=prompt,
                system_prompt=system_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs,
            )
        )
    
    def generate_batch(
        self,
        prompts: List[str],
        system_prompts: Optional[List[Optional[str]]] = None,
        **kwargs,
    ) -> List[Optional[str]]:
        """Generate text for multiple prompts (synchronous)"""
        self._ensure_started()
        return self._loop.run_until_complete(
            self._client.generate_batch(
                prompts=prompts,
                system_prompts=system_prompts,
                **kwargs,
            )
        )
    
    def is_available(self) -> bool:
        """Check if client is available"""
        self._ensure_started()
        return self._client.is_available()
    
    def set_policy(self, policy: str) -> None:
        """Change policy"""
        self._client.set_policy(policy)
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get metrics"""
        return self._client.get_metrics()
    
    def close(self) -> None:
        """Close client and cleanup all resources"""
        if self._closed:
            return
        
        try:
            if self._started:
                # Stop the async client
                self._loop.run_until_complete(self._client.stop())
                self._started = False
            
            # Cancel any remaining tasks
            pending = asyncio.all_tasks(self._loop)
            for task in pending:
                task.cancel()
            
            # Wait for tasks to complete cancellation
            if pending:
                self._loop.run_until_complete(
                    asyncio.gather(*pending, return_exceptions=True)
                )
            
            # Shutdown async generators
            self._loop.run_until_complete(self._loop.shutdown_asyncgens())
            
        except Exception as e:
            logger.warning("Error during client shutdown: %s", e)
        finally:
            # Close the event loop
            if not self._loop.is_closed():
                self._loop.close()
            self._closed = True
    
    def __enter__(self) -> "SyncLIRClient":
        """Context manager entry"""
        self._ensure_started()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit"""
        self.close()
    
    def __del__(self) -> None:
        """Destructor - ensure cleanup on garbage collection"""
        if not self._closed:
            try:
                self.close()
            except Exception:
                pass  # Ignore errors during GC

