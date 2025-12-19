"""
LIR Scheduler - Request Queue + Concurrency Control + Token Budget

Provides:
- Thread-safe request queue with FIFO ordering
- Token-aware concurrency control (semaphore + token budget)
- Backpressure handling (max queue depth)
- Request metadata tracking (enqueue time, tokens estimate)

Usage:
    scheduler = Scheduler(max_concurrent=3, max_tokens_inflight=8192)
    
    # Enqueue request
    request = InferenceRequest(prompt="Hello", system_prompt="Be helpful")
    await scheduler.enqueue(request)
    
    # Process requests
    async for batch in scheduler.get_batches():
        results = await process_batch(batch)
        scheduler.complete(batch, results)
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class RequestStatus(Enum):
    """Request lifecycle status"""
    PENDING = "pending"
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class InferenceRequest:
    """
    Single inference request with metadata.
    
    Attributes:
        request_id: Unique identifier
        prompt: User prompt text
        system_prompt: Optional system context
        estimated_tokens: Estimated token count (prompt + expected output)
        priority: Request priority (0 = highest, reserved for future)
        created_at: Timestamp when request was created
        enqueued_at: Timestamp when request entered queue
        started_at: Timestamp when processing started
        completed_at: Timestamp when processing completed
        status: Current request status
        result: Generated text result (when completed)
        error: Error message (when failed)
        metadata: Additional metadata (provider, model, etc.)
    """
    prompt: str
    system_prompt: Optional[str] = None
    request_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    estimated_tokens: int = 0
    priority: int = 0
    created_at: float = field(default_factory=time.time)
    enqueued_at: Optional[float] = None
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    status: RequestStatus = RequestStatus.PENDING
    result: Optional[str] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    # Internal: Future for async result waiting
    _future: Optional[asyncio.Future] = field(default=None, repr=False)
    
    def __post_init__(self):
        """Estimate tokens if not provided"""
        if self.estimated_tokens == 0:
            # Rough estimate: ~1 token per 4 characters + expected output
            prompt_tokens = len(self.prompt) // 4
            system_tokens = len(self.system_prompt) // 4 if self.system_prompt else 0
            output_estimate = 500  # Default expected output tokens
            self.estimated_tokens = prompt_tokens + system_tokens + output_estimate
    
    def mark_queued(self) -> None:
        """Mark request as queued"""
        self.status = RequestStatus.QUEUED
        self.enqueued_at = time.time()
    
    def mark_processing(self) -> None:
        """Mark request as processing"""
        self.status = RequestStatus.PROCESSING
        self.started_at = time.time()
    
    def mark_completed(self, result: str) -> None:
        """Mark request as completed with result"""
        self.status = RequestStatus.COMPLETED
        self.completed_at = time.time()
        self.result = result
        if self._future and not self._future.done():
            self._future.set_result(result)
    
    def mark_failed(self, error: str) -> None:
        """Mark request as failed with error"""
        self.status = RequestStatus.FAILED
        self.completed_at = time.time()
        self.error = error
        if self._future and not self._future.done():
            self._future.set_exception(RuntimeError(error))
    
    def mark_cancelled(self) -> None:
        """Mark request as cancelled"""
        self.status = RequestStatus.CANCELLED
        self.completed_at = time.time()
        if self._future and not self._future.done():
            self._future.cancel()
    
    @property
    def queue_wait_time(self) -> Optional[float]:
        """Time spent waiting in queue (seconds)"""
        if self.enqueued_at and self.started_at:
            return self.started_at - self.enqueued_at
        return None
    
    @property
    def processing_time(self) -> Optional[float]:
        """Time spent processing (seconds)"""
        if self.started_at and self.completed_at:
            return self.completed_at - self.started_at
        return None
    
    @property
    def total_time(self) -> Optional[float]:
        """Total time from creation to completion (seconds)"""
        if self.completed_at:
            return self.completed_at - self.created_at
        return None


class RequestQueue:
    """
    Thread-safe async request queue with backpressure.
    
    Features:
    - FIFO ordering (priority reserved for future)
    - Max queue depth with backpressure
    - Async put/get operations
    - Queue metrics
    
    Usage:
        queue = RequestQueue(max_depth=100)
        await queue.put(request)
        request = await queue.get()
    """
    
    def __init__(self, max_depth: int = 100):
        """
        Initialize request queue.
        
        Args:
            max_depth: Maximum queue depth (backpressure threshold)
        """
        self.max_depth = max_depth
        self._queue: asyncio.Queue[InferenceRequest] = asyncio.Queue(maxsize=max_depth)
        self._total_enqueued = 0
        self._total_dequeued = 0
        self._lock = asyncio.Lock()
    
    async def put(self, request: InferenceRequest, timeout: Optional[float] = None) -> bool:
        """
        Add request to queue.
        
        Args:
            request: Request to enqueue
            timeout: Max time to wait if queue is full (None = wait forever)
            
        Returns:
            True if enqueued, False if timeout
            
        Raises:
            asyncio.QueueFull: If queue is full and timeout=0
        """
        try:
            request.mark_queued()
            if timeout == 0:
                self._queue.put_nowait(request)
            else:
                await asyncio.wait_for(self._queue.put(request), timeout=timeout)
            
            async with self._lock:
                self._total_enqueued += 1
            
            logger.debug(
                "Request %s enqueued (depth=%d, tokens=%d)",
                request.request_id,
                self.depth,
                request.estimated_tokens,
            )
            return True
            
        except asyncio.TimeoutError:
            logger.warning("Queue full, request %s timed out", request.request_id)
            return False
        except asyncio.QueueFull:
            logger.warning("Queue full, request %s rejected", request.request_id)
            raise
    
    async def get(self, timeout: Optional[float] = None) -> Optional[InferenceRequest]:
        """
        Get next request from queue.
        
        Args:
            timeout: Max time to wait for request (None = wait forever)
            
        Returns:
            Next request or None if timeout
        """
        try:
            if timeout is None:
                request = await self._queue.get()
            else:
                request = await asyncio.wait_for(self._queue.get(), timeout=timeout)
            
            async with self._lock:
                self._total_dequeued += 1
            
            return request
            
        except asyncio.TimeoutError:
            return None
    
    def get_nowait(self) -> Optional[InferenceRequest]:
        """Get request without waiting (returns None if empty)"""
        try:
            request = self._queue.get_nowait()
            self._total_dequeued += 1
            return request
        except asyncio.QueueEmpty:
            return None
    
    def task_done(self) -> None:
        """Mark a dequeued task as done"""
        self._queue.task_done()
    
    @property
    def depth(self) -> int:
        """Current queue depth"""
        return self._queue.qsize()
    
    @property
    def is_empty(self) -> bool:
        """Check if queue is empty"""
        return self._queue.empty()
    
    @property
    def is_full(self) -> bool:
        """Check if queue is at max depth"""
        return self._queue.full()
    
    @property
    def utilization(self) -> float:
        """Queue utilization (0.0 to 1.0)"""
        return self.depth / self.max_depth if self.max_depth > 0 else 0.0
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get queue metrics"""
        return {
            "depth": self.depth,
            "max_depth": self.max_depth,
            "utilization": self.utilization,
            "total_enqueued": self._total_enqueued,
            "total_dequeued": self._total_dequeued,
            "is_empty": self.is_empty,
            "is_full": self.is_full,
        }


class ConcurrencyController:
    """
    Token-aware concurrency controller.
    
    Controls concurrent requests based on:
    1. Max concurrent requests (semaphore)
    2. Max tokens in-flight (token budget)
    
    Usage:
        controller = ConcurrencyController(max_concurrent=3, max_tokens=8192)
        
        async with controller.acquire(request):
            result = await process(request)
    """
    
    def __init__(
        self,
        max_concurrent_requests: int = 3,
        max_tokens_inflight: int = 8192,
    ):
        """
        Initialize concurrency controller.
        
        Args:
            max_concurrent_requests: Max parallel requests
            max_tokens_inflight: Max total tokens being processed
        """
        self.max_concurrent_requests = max_concurrent_requests
        self.max_tokens_inflight = max_tokens_inflight
        
        self._semaphore = asyncio.Semaphore(max_concurrent_requests)
        self._tokens_inflight = 0
        self._requests_inflight = 0
        self._lock = asyncio.Lock()
        
        # Metrics
        self._total_acquired = 0
        self._total_released = 0
        self._total_rejected = 0
        self._peak_concurrent = 0
        self._peak_tokens = 0
    
    async def acquire(self, request: InferenceRequest, timeout: Optional[float] = None) -> bool:
        """
        Acquire slot for request.
        
        Args:
            request: Request to acquire slot for
            timeout: Max time to wait (None = wait forever)
            
        Returns:
            True if acquired, False if timeout or rejected
        """
        try:
            # Wait for semaphore
            if timeout is not None:
                acquired = await asyncio.wait_for(
                    self._semaphore.acquire(),
                    timeout=timeout,
                )
                if not acquired:
                    return False
            else:
                await self._semaphore.acquire()
            
            # Check token budget
            async with self._lock:
                if self._tokens_inflight + request.estimated_tokens > self.max_tokens_inflight:
                    # Token budget exceeded, release semaphore
                    self._semaphore.release()
                    self._total_rejected += 1
                    logger.warning(
                        "Token budget exceeded: %d + %d > %d",
                        self._tokens_inflight,
                        request.estimated_tokens,
                        self.max_tokens_inflight,
                    )
                    return False
                
                # Acquire successful
                self._tokens_inflight += request.estimated_tokens
                self._requests_inflight += 1
                self._total_acquired += 1
                
                # Update peaks
                self._peak_concurrent = max(self._peak_concurrent, self._requests_inflight)
                self._peak_tokens = max(self._peak_tokens, self._tokens_inflight)
            
            logger.debug(
                "Acquired slot for %s (concurrent=%d, tokens=%d)",
                request.request_id,
                self._requests_inflight,
                self._tokens_inflight,
            )
            return True
            
        except asyncio.TimeoutError:
            self._total_rejected += 1
            return False
    
    async def release(self, request: InferenceRequest) -> None:
        """
        Release slot for completed request.
        
        Args:
            request: Request to release slot for
        """
        async with self._lock:
            self._tokens_inflight = max(0, self._tokens_inflight - request.estimated_tokens)
            self._requests_inflight = max(0, self._requests_inflight - 1)
            self._total_released += 1
        
        self._semaphore.release()
        
        logger.debug(
            "Released slot for %s (concurrent=%d, tokens=%d)",
            request.request_id,
            self._requests_inflight,
            self._tokens_inflight,
        )
    
    def update_limits(
        self,
        max_concurrent_requests: Optional[int] = None,
        max_tokens_inflight: Optional[int] = None,
    ) -> None:
        """
        Update concurrency limits (for thermal governor).
        
        Note: Changes take effect for new acquisitions only.
        """
        if max_concurrent_requests is not None:
            old_max = self.max_concurrent_requests
            self.max_concurrent_requests = max_concurrent_requests
            
            # Adjust semaphore (add or remove permits)
            diff = max_concurrent_requests - old_max
            if diff > 0:
                # Add permits
                for _ in range(diff):
                    self._semaphore.release()
            # Note: Can't easily remove permits from asyncio.Semaphore
            # New limit will be enforced naturally as requests complete
            
            logger.info(
                "Updated max_concurrent_requests: %d -> %d",
                old_max,
                max_concurrent_requests,
            )
        
        if max_tokens_inflight is not None:
            old_max = self.max_tokens_inflight
            self.max_tokens_inflight = max_tokens_inflight
            logger.info(
                "Updated max_tokens_inflight: %d -> %d",
                old_max,
                max_tokens_inflight,
            )
    
    @property
    def current_concurrent(self) -> int:
        """Current number of concurrent requests"""
        return self._requests_inflight
    
    @property
    def current_tokens(self) -> int:
        """Current tokens in-flight"""
        return self._tokens_inflight
    
    @property
    def available_slots(self) -> int:
        """Number of available request slots"""
        return max(0, self.max_concurrent_requests - self._requests_inflight)
    
    @property
    def available_tokens(self) -> int:
        """Available token budget"""
        return max(0, self.max_tokens_inflight - self._tokens_inflight)
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get concurrency metrics"""
        return {
            "current_concurrent": self._requests_inflight,
            "max_concurrent": self.max_concurrent_requests,
            "current_tokens": self._tokens_inflight,
            "max_tokens": self.max_tokens_inflight,
            "available_slots": self.available_slots,
            "available_tokens": self.available_tokens,
            "total_acquired": self._total_acquired,
            "total_released": self._total_released,
            "total_rejected": self._total_rejected,
            "peak_concurrent": self._peak_concurrent,
            "peak_tokens": self._peak_tokens,
        }


class Scheduler:
    """
    Main scheduler combining queue and concurrency control.
    
    Usage:
        scheduler = Scheduler(max_concurrent=3, max_tokens=8192)
        
        # Submit request
        future = await scheduler.submit(request)
        result = await future
        
        # Or batch processing
        async for request in scheduler.get_ready_requests():
            await process(request)
    """
    
    def __init__(
        self,
        max_concurrent_requests: int = 3,
        max_tokens_inflight: int = 8192,
        max_queue_depth: int = 100,
    ):
        """
        Initialize scheduler.
        
        Args:
            max_concurrent_requests: Max parallel requests
            max_tokens_inflight: Max tokens being processed
            max_queue_depth: Max queue depth
        """
        self.queue = RequestQueue(max_depth=max_queue_depth)
        self.concurrency = ConcurrencyController(
            max_concurrent_requests=max_concurrent_requests,
            max_tokens_inflight=max_tokens_inflight,
        )
        self._running = False
        self._processor_task: Optional[asyncio.Task] = None
    
    async def submit(
        self,
        request: InferenceRequest,
        timeout: Optional[float] = None,
    ) -> asyncio.Future:
        """
        Submit request and get future for result.
        
        Args:
            request: Request to submit
            timeout: Max time to wait for queue space
            
        Returns:
            Future that resolves to result string
        """
        # Create future for result
        loop = asyncio.get_event_loop()
        request._future = loop.create_future()
        
        # Enqueue
        success = await self.queue.put(request, timeout=timeout)
        if not success:
            request.mark_failed("Queue timeout")
            raise asyncio.TimeoutError("Queue timeout")
        
        return request._future
    
    async def get_ready_requests(
        self,
        max_batch: int = 10,
        timeout: float = 0.05,
    ) -> List[InferenceRequest]:
        """
        Get requests that are ready to process.
        
        Args:
            max_batch: Max requests to return
            timeout: Max time to wait for first request
            
        Returns:
            List of requests ready to process
        """
        ready = []
        
        # Get first request (with timeout)
        first = await self.queue.get(timeout=timeout)
        if first is None:
            return ready
        
        # Try to acquire slot
        if not await self.concurrency.acquire(first, timeout=0):
            # Can't process yet, put back
            await self.queue.put(first, timeout=0)
            return ready
        
        first.mark_processing()
        ready.append(first)
        
        # Try to get more requests (non-blocking)
        while len(ready) < max_batch:
            request = self.queue.get_nowait()
            if request is None:
                break
            
            # Try to acquire slot
            if not await self.concurrency.acquire(request, timeout=0):
                # Can't process, put back
                await self.queue.put(request, timeout=0)
                break
            
            request.mark_processing()
            ready.append(request)
        
        return ready
    
    async def complete(self, request: InferenceRequest, result: str) -> None:
        """Mark request as completed and release resources"""
        request.mark_completed(result)
        await self.concurrency.release(request)
        self.queue.task_done()
    
    async def fail(self, request: InferenceRequest, error: str) -> None:
        """Mark request as failed and release resources"""
        request.mark_failed(error)
        await self.concurrency.release(request)
        self.queue.task_done()
    
    def update_limits(
        self,
        max_concurrent_requests: Optional[int] = None,
        max_tokens_inflight: Optional[int] = None,
    ) -> None:
        """Update concurrency limits (for thermal governor)"""
        self.concurrency.update_limits(
            max_concurrent_requests=max_concurrent_requests,
            max_tokens_inflight=max_tokens_inflight,
        )
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get scheduler metrics"""
        return {
            "queue": self.queue.get_metrics(),
            "concurrency": self.concurrency.get_metrics(),
        }

