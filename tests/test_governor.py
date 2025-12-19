"""
Unit tests for LIR Thermal Governor

Tests:
- ThermalMetrics collection
- ThermalState transitions
- ThermalGovernor adaptive behavior
- Limit adjustments
"""

import asyncio
import pytest
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add lir to path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from lir.governor import (
    ThermalState,
    ThermalMetrics,
    ThermalPolicy,
    ThermalMonitor,
    ThermalGovernor,
    THERMAL_POLICIES,
)


class TestThermalMetrics:
    """Tests for ThermalMetrics dataclass"""
    
    def test_metrics_creation(self):
        """Test basic metrics creation"""
        metrics = ThermalMetrics(
            cpu_percent_avg=50.0,
            cpu_percent_max=75.0,
            cpu_percent_per_core=[50.0, 75.0, 60.0, 40.0],
            memory_percent=60.0,
        )
        
        assert metrics.cpu_percent_avg == 50.0
        assert metrics.cpu_percent_max == 75.0
        assert len(metrics.cpu_percent_per_core) == 4
    
    def test_metrics_to_dict(self):
        """Test metrics serialization"""
        metrics = ThermalMetrics(
            cpu_percent_avg=50.0,
            cpu_percent_max=75.0,
            state=ThermalState.WARM,
        )
        
        data = metrics.to_dict()
        
        assert data["cpu_percent_avg"] == 50.0
        assert data["state"] == "warm"


class TestThermalPolicy:
    """Tests for ThermalPolicy"""
    
    def test_default_policies_exist(self):
        """Test default policies are defined"""
        assert "conservative" in THERMAL_POLICIES
        assert "normal" in THERMAL_POLICIES
        assert "aggressive" in THERMAL_POLICIES
    
    def test_policy_thresholds(self):
        """Test policy threshold ordering"""
        for name, policy in THERMAL_POLICIES.items():
            assert policy.cool_threshold < policy.warm_threshold
            assert policy.warm_threshold < policy.hot_threshold


class TestThermalMonitor:
    """Tests for ThermalMonitor"""
    
    @pytest.mark.asyncio
    async def test_collect_metrics(self):
        """Test metrics collection"""
        monitor = ThermalMonitor(sample_interval=0.1)
        
        metrics = await monitor.collect()
        
        # Should return valid metrics
        assert metrics is not None
        assert isinstance(metrics.cpu_percent_avg, float)
        assert isinstance(metrics.cpu_percent_max, float)
    
    @pytest.mark.asyncio
    async def test_collect_without_psutil(self):
        """Test graceful handling when psutil unavailable"""
        monitor = ThermalMonitor()
        
        # Mock HAS_PSUTIL = False
        with patch("lir.governor.HAS_PSUTIL", False):
            metrics = await monitor.collect()
            
            # Should return default metrics
            assert metrics.state == ThermalState.COOL


class TestThermalGovernor:
    """Tests for ThermalGovernor"""
    
    def test_governor_creation(self):
        """Test governor creation"""
        governor = ThermalGovernor(
            policy="normal",
            base_max_concurrent=3,
            base_batch_window_ms=40,
        )
        
        assert governor.policy.name == "normal"
        assert governor.base_max_concurrent == 3
        assert governor.current_state == ThermalState.COOL
    
    def test_should_throttle(self):
        """Test throttle detection"""
        governor = ThermalGovernor(policy="normal")
        
        # Default state is COOL
        assert governor.should_throttle() is False
        
        # Manually set to HOT
        governor._current_state = ThermalState.HOT
        assert governor.should_throttle() is True
        
        # CRITICAL should also throttle
        governor._current_state = ThermalState.CRITICAL
        assert governor.should_throttle() is True
    
    def test_should_pause(self):
        """Test pause detection"""
        governor = ThermalGovernor(policy="normal")
        
        # Only CRITICAL should pause
        governor._current_state = ThermalState.HOT
        assert governor.should_pause() is False
        
        governor._current_state = ThermalState.CRITICAL
        assert governor.should_pause() is True
    
    def test_get_adjusted_limits_cool(self):
        """Test limits when COOL"""
        governor = ThermalGovernor(
            policy="normal",
            base_max_concurrent=3,
            base_batch_window_ms=40,
        )
        
        governor._current_state = ThermalState.COOL
        limits = governor.get_adjusted_limits()
        
        # Should be unchanged
        assert limits["max_concurrent_requests"] == 3
        assert limits["batch_window_ms"] == 40
    
    def test_get_adjusted_limits_hot(self):
        """Test limits when HOT"""
        governor = ThermalGovernor(
            policy="normal",
            base_max_concurrent=4,
            base_batch_window_ms=40,
        )
        
        governor._current_state = ThermalState.HOT
        limits = governor.get_adjusted_limits()
        
        # Should be reduced (hot_concurrent_factor = 0.5 for normal)
        assert limits["max_concurrent_requests"] == 2  # 4 * 0.5
        assert limits["batch_window_ms"] == 60  # 40 * 1.5
    
    def test_get_adjusted_limits_critical(self):
        """Test limits when CRITICAL"""
        governor = ThermalGovernor(
            policy="normal",
            base_max_concurrent=4,
            base_batch_window_ms=40,
        )
        
        governor._current_state = ThermalState.CRITICAL
        limits = governor.get_adjusted_limits()
        
        # Should be minimal (critical_concurrent_factor = 0.0 for normal)
        # But minimum is 1
        assert limits["max_concurrent_requests"] == 1
        assert limits["batch_window_ms"] == 80  # 40 * 2.0
    
    def test_set_policy(self):
        """Test policy change"""
        governor = ThermalGovernor(policy="normal")
        
        governor.set_policy("aggressive")
        
        assert governor.policy.name == "aggressive"
    
    @pytest.mark.asyncio
    async def test_cooldown(self):
        """Test cooldown duration"""
        governor = ThermalGovernor(policy="normal")
        
        # COOL state should have no cooldown
        governor._current_state = ThermalState.COOL
        duration = await governor.cooldown()
        assert duration == 0.0
        
        # HOT state should have cooldown
        governor._current_state = ThermalState.HOT
        # Don't actually wait, just verify it would
        assert governor.policy.hot_cooldown > 0
    
    def test_metrics(self):
        """Test governor metrics"""
        governor = ThermalGovernor(
            policy="normal",
            base_max_concurrent=3,
        )
        
        metrics = governor.get_metrics()
        
        assert metrics["policy"] == "normal"
        assert metrics["current_state"] == "cool"
        assert metrics["base_max_concurrent"] == 3
    
    @pytest.mark.asyncio
    async def test_state_change_callback(self):
        """Test state change callback"""
        callback_called = []
        
        def on_change(old, new):
            callback_called.append((old, new))
        
        governor = ThermalGovernor(
            policy="normal",
            on_state_change=on_change,
        )
        
        # Simulate state change
        mock_metrics = ThermalMetrics(
            cpu_percent_max=80.0,  # Above warm_threshold (70)
            state=ThermalState.HOT,
        )
        
        await governor._update_state(mock_metrics)
        
        # Callback should have been called
        assert len(callback_called) == 1
        assert callback_called[0] == (ThermalState.COOL, ThermalState.HOT)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

