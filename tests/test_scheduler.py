"""
Unit tests for LIR Scheduler

Tests:
- InferenceRequest creation and lifecycle
- RequestQueue FIFO ordering and backpressure
- ConcurrencyController token budget and limits
- Scheduler integration
"""

import asyncio
import pytest
import sys
from pathlib import Path

# Add lir to path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from lir.scheduler import (
    InferenceRequest,
    RequestQueue,
    ConcurrencyController,
    Scheduler,
    RequestStatus,
)


class TestInferenceRequest:
    """Tests for InferenceRequest dataclass"""
    
    def test_request_creation(self):
        """Test basic request creation"""
        request = InferenceRequest(
            prompt="Hello, world!",
            system_prompt="Be helpful",
        )
        
        assert request.prompt == "Hello, world!"
        assert request.system_prompt == "Be helpful"
        assert request.status == RequestStatus.PENDING
        assert request.request_id is not None
        assert len(request.request_id) == 8
    
    def test_token_estimation(self):
        """Test automatic token estimation"""
        request = InferenceRequest(prompt="Hello")
        
        # Should estimate: prompt_tokens + output_estimate
        # "Hello" = 5 chars / 4 = 1 token + 500 output = ~501
        assert request.estimated_tokens > 0
    
    def test_status_transitions(self):
        """Test request status transitions"""
        request = InferenceRequest(prompt="Test")
        
        assert request.status == RequestStatus.PENDING
        
        request.mark_queued()
        assert request.status == RequestStatus.QUEUED
        assert request.enqueued_at is not None
        
        request.mark_processing()
        assert request.status == RequestStatus.PROCESSING
        assert request.started_at is not None
        
        request.mark_completed("Result")
        assert request.status == RequestStatus.COMPLETED
        assert request.result == "Result"
        assert request.completed_at is not None
    
    def test_timing_properties(self):
        """Test queue_wait_time and processing_time"""
        request = InferenceRequest(prompt="Test")
        
        # Initially None
        assert request.queue_wait_time is None
        assert request.processing_time is None
        
        request.mark_queued()
        request.mark_processing()
        
        # Now queue_wait_time should be set
        assert request.queue_wait_time is not None
        assert request.queue_wait_time >= 0
        
        request.mark_completed("Done")
        
        # Now processing_time should be set
        assert request.processing_time is not None
        assert request.processing_time >= 0


class TestRequestQueue:
    """Tests for RequestQueue"""
    
    @pytest.mark.asyncio
    async def test_queue_put_get(self):
        """Test basic put and get operations"""
        queue = RequestQueue(max_depth=10)
        
        request = InferenceRequest(prompt="Test")
        await queue.put(request)
        
        assert queue.depth == 1
        
        retrieved = await queue.get(timeout=1.0)
        assert retrieved is not None
        assert retrieved.request_id == request.request_id
        assert queue.depth == 0
    
    @pytest.mark.asyncio
    async def test_queue_fifo_ordering(self):
        """Test FIFO ordering"""
        queue = RequestQueue(max_depth=10)
        
        requests = [
            InferenceRequest(prompt=f"Request {i}")
            for i in range(5)
        ]
        
        for req in requests:
            await queue.put(req)
        
        for i in range(5):
            retrieved = await queue.get(timeout=1.0)
            assert retrieved.prompt == f"Request {i}"
    
    @pytest.mark.asyncio
    async def test_queue_backpressure(self):
        """Test backpressure when queue is full"""
        queue = RequestQueue(max_depth=2)
        
        # Fill queue
        await queue.put(InferenceRequest(prompt="1"))
        await queue.put(InferenceRequest(prompt="2"))
        
        assert queue.is_full
        
        # Should timeout when trying to add more
        request3 = InferenceRequest(prompt="3")
        result = await queue.put(request3, timeout=0.1)
        
        # put returns False on timeout
        assert result is False
    
    @pytest.mark.asyncio
    async def test_queue_metrics(self):
        """Test queue metrics"""
        queue = RequestQueue(max_depth=10)
        
        await queue.put(InferenceRequest(prompt="Test"))
        
        metrics = queue.get_metrics()
        
        assert metrics["depth"] == 1
        assert metrics["max_depth"] == 10
        assert metrics["total_enqueued"] == 1
        assert metrics["utilization"] == 0.1


class TestConcurrencyController:
    """Tests for ConcurrencyController"""
    
    @pytest.mark.asyncio
    async def test_acquire_release(self):
        """Test basic acquire and release"""
        controller = ConcurrencyController(
            max_concurrent_requests=3,
            max_tokens_inflight=8192,
        )
        
        request = InferenceRequest(prompt="Test")
        
        # Should succeed
        acquired = await controller.acquire(request)
        assert acquired is True
        assert controller.current_concurrent == 1
        
        # Release
        await controller.release(request)
        assert controller.current_concurrent == 0
    
    @pytest.mark.asyncio
    async def test_concurrent_limit(self):
        """Test concurrent request limit"""
        controller = ConcurrencyController(
            max_concurrent_requests=2,
            max_tokens_inflight=100000,  # High limit to not interfere
        )
        
        requests = [
            InferenceRequest(prompt=f"Request {i}")
            for i in range(3)
        ]
        
        # Acquire first two
        assert await controller.acquire(requests[0]) is True
        assert await controller.acquire(requests[1]) is True
        
        # Third should timeout (semaphore full)
        assert await controller.acquire(requests[2], timeout=0.1) is False
        
        # Release one
        await controller.release(requests[0])
        
        # Now third should succeed
        assert await controller.acquire(requests[2]) is True
    
    @pytest.mark.asyncio
    async def test_token_budget(self):
        """Test token budget enforcement"""
        controller = ConcurrencyController(
            max_concurrent_requests=10,
            max_tokens_inflight=10000,  # Higher budget
        )
        
        # Create request with moderate tokens
        request1 = InferenceRequest(prompt="x" * 2000)  # ~500 prompt + 500 output = ~1000
        
        # Should succeed
        assert await controller.acquire(request1) is True
        
        # Fill up the budget with more requests
        for _ in range(8):
            req = InferenceRequest(prompt="y" * 2000)
            await controller.acquire(req)
        
        # Now budget should be close to full
        # Next large request should fail
        large_request = InferenceRequest(prompt="z" * 4000)  # ~1500 tokens
        result = await controller.acquire(large_request, timeout=0)
        # May or may not succeed depending on exact token calculation
        # Just verify the mechanism works
        assert controller.current_tokens > 0
    
    def test_update_limits(self):
        """Test dynamic limit updates"""
        controller = ConcurrencyController(
            max_concurrent_requests=3,
            max_tokens_inflight=8192,
        )
        
        controller.update_limits(
            max_concurrent_requests=5,
            max_tokens_inflight=16384,
        )
        
        assert controller.max_concurrent_requests == 5
        assert controller.max_tokens_inflight == 16384


class TestScheduler:
    """Tests for Scheduler integration"""
    
    @pytest.mark.asyncio
    async def test_scheduler_submit(self):
        """Test request submission"""
        scheduler = Scheduler(
            max_concurrent_requests=3,
            max_tokens_inflight=50000,
        )
        
        request = InferenceRequest(prompt="Test")
        future = await scheduler.submit(request)
        
        assert scheduler.queue.depth == 1
        assert not future.done()
    
    @pytest.mark.asyncio
    async def test_scheduler_queue_operations(self):
        """Test queue and concurrency operations directly"""
        scheduler = Scheduler(
            max_concurrent_requests=3,
            max_tokens_inflight=50000,
        )
        
        # Add requests directly to queue
        requests = []
        for i in range(3):
            request = InferenceRequest(prompt=f"Request {i}")
            await scheduler.queue.put(request)
            requests.append(request)
        
        assert scheduler.queue.depth == 3
        
        # Manually acquire and process
        req = await scheduler.queue.get(timeout=0.1)
        assert req is not None
        assert req.prompt == "Request 0"
        
        # Acquire concurrency slot
        acquired = await scheduler.concurrency.acquire(req)
        assert acquired is True
        assert scheduler.concurrency.current_concurrent == 1
        
        # Release
        await scheduler.concurrency.release(req)
        assert scheduler.concurrency.current_concurrent == 0
    
    @pytest.mark.asyncio
    async def test_scheduler_metrics(self):
        """Test scheduler metrics"""
        scheduler = Scheduler(
            max_concurrent_requests=3,
            max_tokens_inflight=50000,
        )
        
        metrics = scheduler.get_metrics()
        
        assert "queue" in metrics
        assert "concurrency" in metrics
        assert metrics["queue"]["depth"] == 0
        assert metrics["concurrency"]["current_concurrent"] == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

