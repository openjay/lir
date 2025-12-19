"""
LIR Micro-batching Engine

Collects requests within a configurable time window and batches them
for more efficient processing. Reduces kernel startup overhead and
improves throughput.

Features:
- Configurable batching window (20-50ms typical)
- Max batch size limit
- Automatic batch formation and splitting
- Batch metrics tracking

Usage:
    engine = BatchingEngine(window_ms=40, max_batch_size=10)
    
    # Add requests as they arrive
    engine.add(request1)
    engine.add(request2)
    
    # Get formed batch when window expires
    batch = await engine.get_batch()
    
    # Process batch
    results = await provider.generate_batch(batch.prompts)
    
    # Distribute results back to requests
    batch.complete(results)
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .scheduler import InferenceRequest

logger = logging.getLogger(__name__)


@dataclass
class Batch:
    """
    A batch of inference requests to process together.
    
    Attributes:
        batch_id: Unique batch identifier
        requests: List of requests in this batch
        created_at: Timestamp when batch was created
        started_at: Timestamp when processing started
        completed_at: Timestamp when processing completed
    """
    batch_id: str
    requests: List[InferenceRequest] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    
    @property
    def size(self) -> int:
        """Number of requests in batch"""
        return len(self.requests)
    
    @property
    def total_estimated_tokens(self) -> int:
        """Total estimated tokens across all requests"""
        return sum(r.estimated_tokens for r in self.requests)
    
    @property
    def prompts(self) -> List[str]:
        """Extract prompts from all requests"""
        return [r.prompt for r in self.requests]
    
    @property
    def system_prompts(self) -> List[Optional[str]]:
        """Extract system prompts from all requests"""
        return [r.system_prompt for r in self.requests]
    
    @property
    def request_ids(self) -> List[str]:
        """Extract request IDs"""
        return [r.request_id for r in self.requests]
    
    def mark_started(self) -> None:
        """Mark batch as started processing"""
        self.started_at = time.time()
        for request in self.requests:
            request.mark_processing()
    
    def complete(self, results: List[Optional[str]]) -> None:
        """
        Complete batch with results.
        
        Args:
            results: List of results corresponding to each request
        """
        self.completed_at = time.time()
        
        if len(results) != len(self.requests):
            logger.error(
                "Batch %s: result count mismatch (%d results, %d requests)",
                self.batch_id,
                len(results),
                len(self.requests),
            )
            # Pad with None if needed
            while len(results) < len(self.requests):
                results.append(None)
        
        for request, result in zip(self.requests, results):
            if result is not None:
                request.mark_completed(result)
            else:
                request.mark_failed("No result returned")
    
    def fail(self, error: str) -> None:
        """Fail all requests in batch"""
        self.completed_at = time.time()
        for request in self.requests:
            request.mark_failed(error)
    
    @property
    def processing_time(self) -> Optional[float]:
        """Time spent processing (seconds)"""
        if self.started_at and self.completed_at:
            return self.completed_at - self.started_at
        return None
    
    @property
    def wait_time(self) -> Optional[float]:
        """Time from creation to start (seconds)"""
        if self.started_at:
            return self.started_at - self.created_at
        return None
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get batch metrics"""
        return {
            "batch_id": self.batch_id,
            "size": self.size,
            "total_tokens": self.total_estimated_tokens,
            "wait_time": self.wait_time,
            "processing_time": self.processing_time,
        }


class BatchingEngine:
    """
    Micro-batching engine for request aggregation.
    
    Collects requests within a time window and forms batches.
    This improves throughput by reducing per-request overhead.
    
    Usage:
        engine = BatchingEngine(window_ms=40, max_batch_size=10)
        
        # In request handler
        await engine.add(request)
        
        # In processor loop
        while True:
            batch = await engine.get_batch()
            if batch:
                results = await process(batch)
                batch.complete(results)
    """
    
    def __init__(
        self,
        window_ms: int = 40,
        max_batch_size: int = 10,
        min_batch_size: int = 1,
    ):
        """
        Initialize batching engine.
        
        Args:
            window_ms: Batching window in milliseconds (0 = disabled)
            max_batch_size: Maximum requests per batch
            min_batch_size: Minimum requests to form a batch (except on timeout)
        """
        self.window_ms = window_ms
        self.max_batch_size = max_batch_size
        self.min_batch_size = min_batch_size
        
        self._pending: List[InferenceRequest] = []
        self._batch_counter = 0
        self._lock = asyncio.Lock()
        self._batch_ready = asyncio.Event()
        self._window_start: Optional[float] = None
        
        # Metrics
        self._total_batches = 0
        self._total_requests = 0
        self._total_batch_size = 0
    
    async def add(self, request: InferenceRequest) -> None:
        """
        Add request to pending batch.
        
        Args:
            request: Request to add
        """
        async with self._lock:
            # Start window timer on first request
            if not self._pending:
                self._window_start = time.time()
            
            self._pending.append(request)
            self._total_requests += 1
            
            # Check if batch is ready
            if len(self._pending) >= self.max_batch_size:
                self._batch_ready.set()
            
            logger.debug(
                "Added request %s to batch (pending=%d)",
                request.request_id,
                len(self._pending),
            )
    
    async def get_batch(self, timeout: Optional[float] = None) -> Optional[Batch]:
        """
        Get next batch when ready.
        
        A batch is ready when:
        1. Max batch size reached, OR
        2. Window timeout expired (and min_batch_size met), OR
        3. Explicit timeout (returns whatever is pending)
        
        Args:
            timeout: Max time to wait for batch (None = use window_ms)
            
        Returns:
            Batch if ready, None if empty
        """
        # Calculate effective timeout
        if timeout is None:
            timeout = self.window_ms / 1000.0 if self.window_ms > 0 else 0.1
        
        # Wait for batch to be ready or timeout
        try:
            await asyncio.wait_for(
                self._batch_ready.wait(),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            pass
        
        # Form batch from pending requests
        async with self._lock:
            if not self._pending:
                self._batch_ready.clear()
                return None
            
            # Check if we should wait for more requests
            if self.window_ms > 0 and self._window_start:
                elapsed_ms = (time.time() - self._window_start) * 1000
                if elapsed_ms < self.window_ms and len(self._pending) < self.min_batch_size:
                    # Window not expired and not enough requests
                    self._batch_ready.clear()
                    return None
            
            # Form batch
            batch_requests = self._pending[:self.max_batch_size]
            self._pending = self._pending[self.max_batch_size:]
            
            # Reset window if pending is empty
            if not self._pending:
                self._window_start = None
            else:
                self._window_start = time.time()
            
            self._batch_ready.clear()
            
            # Create batch
            self._batch_counter += 1
            batch = Batch(
                batch_id=f"batch-{self._batch_counter:06d}",
                requests=batch_requests,
            )
            
            # Update metrics
            self._total_batches += 1
            self._total_batch_size += batch.size
            
            logger.debug(
                "Formed batch %s with %d requests (pending=%d)",
                batch.batch_id,
                batch.size,
                len(self._pending),
            )
            
            return batch
    
    async def flush(self) -> Optional[Batch]:
        """
        Force flush pending requests into a batch.
        
        Returns:
            Batch with all pending requests, or None if empty
        """
        async with self._lock:
            if not self._pending:
                return None
            
            batch_requests = self._pending[:]
            self._pending = []
            self._window_start = None
            self._batch_ready.clear()
            
            self._batch_counter += 1
            batch = Batch(
                batch_id=f"batch-{self._batch_counter:06d}",
                requests=batch_requests,
            )
            
            self._total_batches += 1
            self._total_batch_size += batch.size
            
            logger.debug(
                "Flushed batch %s with %d requests",
                batch.batch_id,
                batch.size,
            )
            
            return batch
    
    @property
    def pending_count(self) -> int:
        """Number of pending requests"""
        return len(self._pending)
    
    @property
    def has_pending(self) -> bool:
        """Check if there are pending requests"""
        return len(self._pending) > 0
    
    @property
    def average_batch_size(self) -> float:
        """Average batch size"""
        if self._total_batches == 0:
            return 0.0
        return self._total_batch_size / self._total_batches
    
    def update_window(self, window_ms: int) -> None:
        """
        Update batching window (for thermal governor).
        
        Args:
            window_ms: New window in milliseconds
        """
        old_window = self.window_ms
        self.window_ms = window_ms
        logger.info("Updated batching window: %d -> %d ms", old_window, window_ms)
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get batching metrics"""
        return {
            "window_ms": self.window_ms,
            "max_batch_size": self.max_batch_size,
            "min_batch_size": self.min_batch_size,
            "pending_count": self.pending_count,
            "total_batches": self._total_batches,
            "total_requests": self._total_requests,
            "average_batch_size": self.average_batch_size,
        }


class BatchProcessor:
    """
    High-level batch processor that combines batching with processing.
    
    Usage:
        processor = BatchProcessor(
            batching=BatchingEngine(window_ms=40),
            process_fn=provider.generate_batch,
        )
        
        # Start processor
        await processor.start()
        
        # Submit requests
        result = await processor.submit(request)
        
        # Stop processor
        await processor.stop()
    """
    
    def __init__(
        self,
        batching: BatchingEngine,
        process_fn,  # Callable[[Batch], Awaitable[List[Optional[str]]]]
    ):
        """
        Initialize batch processor.
        
        Args:
            batching: Batching engine instance
            process_fn: Async function to process a batch
        """
        self.batching = batching
        self.process_fn = process_fn
        
        self._running = False
        self._processor_task: Optional[asyncio.Task] = None
    
    async def start(self) -> None:
        """Start the batch processor"""
        if self._running:
            return
        
        self._running = True
        self._processor_task = asyncio.create_task(self._process_loop())
        logger.info("BatchProcessor started")
    
    async def stop(self) -> None:
        """Stop the batch processor"""
        self._running = False
        
        # Flush remaining requests
        batch = await self.batching.flush()
        if batch:
            await self._process_batch(batch)
        
        if self._processor_task:
            self._processor_task.cancel()
            try:
                await self._processor_task
            except asyncio.CancelledError:
                pass
        
        logger.info("BatchProcessor stopped")
    
    async def submit(self, request: InferenceRequest) -> str:
        """
        Submit request and wait for result.
        
        Args:
            request: Request to submit
            
        Returns:
            Generated text result
            
        Raises:
            RuntimeError: If processing fails
        """
        # Create future for result
        loop = asyncio.get_event_loop()
        request._future = loop.create_future()
        
        # Add to batching engine
        await self.batching.add(request)
        
        # Wait for result
        return await request._future
    
    async def _process_loop(self) -> None:
        """Main processing loop"""
        while self._running:
            try:
                batch = await self.batching.get_batch()
                if batch:
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
                "Processing batch %s (%d requests, %d tokens)",
                batch.batch_id,
                batch.size,
                batch.total_estimated_tokens,
            )
            
            # Call process function
            results = await self.process_fn(batch)
            
            # Complete batch
            batch.complete(results)
            
            logger.debug(
                "Completed batch %s in %.2fs",
                batch.batch_id,
                batch.processing_time or 0,
            )
            
        except Exception as e:
            logger.error("Batch %s failed: %s", batch.batch_id, e)
            batch.fail(str(e))
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get processor metrics"""
        return {
            "running": self._running,
            "batching": self.batching.get_metrics(),
        }

