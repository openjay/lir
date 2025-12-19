"""
Unit tests for LIR Batching Engine

Tests:
- Batch creation and completion
- Batching window timing
- Max batch size enforcement
- Flush functionality
"""

import asyncio
import pytest
import sys
from pathlib import Path

# Add lir to path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from lir.scheduler import InferenceRequest
from lir.batching import Batch, BatchingEngine


class TestBatch:
    """Tests for Batch dataclass"""
    
    def test_batch_creation(self):
        """Test basic batch creation"""
        requests = [
            InferenceRequest(prompt=f"Request {i}")
            for i in range(3)
        ]
        
        batch = Batch(
            batch_id="test-001",
            requests=requests,
        )
        
        assert batch.batch_id == "test-001"
        assert batch.size == 3
        assert len(batch.prompts) == 3
    
    def test_batch_prompts(self):
        """Test prompt extraction"""
        requests = [
            InferenceRequest(prompt="Hello", system_prompt="Be helpful"),
            InferenceRequest(prompt="World", system_prompt=None),
        ]
        
        batch = Batch(batch_id="test", requests=requests)
        
        assert batch.prompts == ["Hello", "World"]
        assert batch.system_prompts == ["Be helpful", None]
    
    def test_batch_complete(self):
        """Test batch completion"""
        requests = [
            InferenceRequest(prompt=f"Request {i}")
            for i in range(2)
        ]
        
        batch = Batch(batch_id="test", requests=requests)
        batch.mark_started()
        
        results = ["Result 0", "Result 1"]
        batch.complete(results)
        
        assert batch.completed_at is not None
        assert requests[0].result == "Result 0"
        assert requests[1].result == "Result 1"
    
    def test_batch_fail(self):
        """Test batch failure"""
        requests = [
            InferenceRequest(prompt="Test")
        ]
        
        batch = Batch(batch_id="test", requests=requests)
        batch.fail("Connection error")
        
        assert requests[0].error == "Connection error"


class TestBatchingEngine:
    """Tests for BatchingEngine"""
    
    @pytest.mark.asyncio
    async def test_add_and_get_batch(self):
        """Test adding requests and getting batch"""
        engine = BatchingEngine(
            window_ms=50,
            max_batch_size=5,
        )
        
        # Add requests
        for i in range(3):
            await engine.add(InferenceRequest(prompt=f"Request {i}"))
        
        assert engine.pending_count == 3
        
        # Get batch (should return after window)
        batch = await engine.get_batch(timeout=0.1)
        
        assert batch is not None
        assert batch.size == 3
        assert engine.pending_count == 0
    
    @pytest.mark.asyncio
    async def test_max_batch_size(self):
        """Test max batch size enforcement"""
        engine = BatchingEngine(
            window_ms=100,
            max_batch_size=3,
        )
        
        # Add more than max
        for i in range(5):
            await engine.add(InferenceRequest(prompt=f"Request {i}"))
        
        # First batch should be max size
        batch1 = await engine.get_batch(timeout=0.01)
        assert batch1 is not None
        assert batch1.size == 3
        
        # Remaining should be in second batch
        assert engine.pending_count == 2
    
    @pytest.mark.asyncio
    async def test_flush(self):
        """Test flush functionality"""
        engine = BatchingEngine(
            window_ms=1000,  # Long window
            max_batch_size=10,
        )
        
        # Add requests
        await engine.add(InferenceRequest(prompt="Test 1"))
        await engine.add(InferenceRequest(prompt="Test 2"))
        
        # Flush immediately
        batch = await engine.flush()
        
        assert batch is not None
        assert batch.size == 2
        assert engine.pending_count == 0
    
    @pytest.mark.asyncio
    async def test_empty_get_batch(self):
        """Test get_batch when empty"""
        engine = BatchingEngine(window_ms=50)
        
        batch = await engine.get_batch(timeout=0.05)
        
        assert batch is None
    
    def test_update_window(self):
        """Test window update"""
        engine = BatchingEngine(window_ms=50)
        
        engine.update_window(100)
        
        assert engine.window_ms == 100
    
    @pytest.mark.asyncio
    async def test_metrics(self):
        """Test batching metrics"""
        engine = BatchingEngine(
            window_ms=50,
            max_batch_size=5,
        )
        
        # Add and get batch
        await engine.add(InferenceRequest(prompt="Test"))
        await engine.get_batch(timeout=0.1)
        
        metrics = engine.get_metrics()
        
        assert metrics["total_batches"] == 1
        assert metrics["total_requests"] == 1
        assert metrics["average_batch_size"] == 1.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

