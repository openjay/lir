"""
LIR Thermal Governor - Adaptive Load Control via psutil

Monitors system thermal state and automatically adjusts:
- Concurrency limits
- Batching window
- Cooldown periods

Uses psutil for cross-platform, no-sudo-required monitoring.

Features:
- CPU usage per core (identify hottest cores)
- CPU frequency tracking (throttling detection)
- Adaptive concurrency adjustment
- Automatic cooldown insertion
- Graceful degradation if psutil unavailable

Usage:
    governor = ThermalGovernor(policy="balanced")
    
    # Start monitoring
    await governor.start()
    
    # Check before processing
    if governor.should_throttle():
        await governor.cooldown()
    
    # Get adjusted limits
    limits = governor.get_adjusted_limits()
    scheduler.update_limits(**limits)
    
    # Stop monitoring
    await governor.stop()
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# Try to import psutil
try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False
    logger.warning("psutil not available, thermal monitoring disabled")


class ThermalState(Enum):
    """System thermal state"""
    COOL = "cool"        # Normal operation
    WARM = "warm"        # Slightly elevated, monitor closely
    HOT = "hot"          # Elevated, reduce load
    CRITICAL = "critical"  # Very high, pause processing


@dataclass
class ThermalMetrics:
    """
    Current thermal metrics snapshot.
    
    Attributes:
        timestamp: When metrics were collected
        cpu_percent_avg: Average CPU usage across all cores
        cpu_percent_max: Maximum CPU usage (hottest core)
        cpu_percent_per_core: CPU usage per core
        cpu_freq_current: Current CPU frequency (MHz)
        cpu_freq_max: Maximum CPU frequency (MHz)
        cpu_freq_ratio: Current/Max frequency ratio (throttling indicator)
        memory_percent: Memory usage percentage
        state: Derived thermal state
    """
    timestamp: float = field(default_factory=time.time)
    cpu_percent_avg: float = 0.0
    cpu_percent_max: float = 0.0
    cpu_percent_per_core: List[float] = field(default_factory=list)
    cpu_freq_current: Optional[float] = None
    cpu_freq_max: Optional[float] = None
    cpu_freq_ratio: float = 1.0
    memory_percent: float = 0.0
    state: ThermalState = ThermalState.COOL
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "timestamp": self.timestamp,
            "cpu_percent_avg": self.cpu_percent_avg,
            "cpu_percent_max": self.cpu_percent_max,
            "cpu_percent_per_core": self.cpu_percent_per_core,
            "cpu_freq_current": self.cpu_freq_current,
            "cpu_freq_max": self.cpu_freq_max,
            "cpu_freq_ratio": self.cpu_freq_ratio,
            "memory_percent": self.memory_percent,
            "state": self.state.value,
        }


@dataclass
class ThermalPolicy:
    """
    Thermal policy configuration.
    
    Defines thresholds and responses for each thermal level.
    """
    name: str
    
    # CPU thresholds (hottest core)
    cool_threshold: float = 50.0      # Below this = COOL
    warm_threshold: float = 70.0      # Below this = WARM
    hot_threshold: float = 85.0       # Below this = HOT, above = CRITICAL
    
    # Frequency throttling threshold
    freq_throttle_ratio: float = 0.9  # If freq < 90% of max, consider throttled
    
    # Response actions
    warm_concurrent_factor: float = 1.0    # Multiply max_concurrent by this when WARM
    hot_concurrent_factor: float = 0.5     # Multiply max_concurrent by this when HOT
    critical_concurrent_factor: float = 0.0  # Multiply max_concurrent by this when CRITICAL
    
    # Batching window adjustments (multipliers)
    warm_window_factor: float = 1.0
    hot_window_factor: float = 1.5
    critical_window_factor: float = 2.0
    
    # Cooldown durations (seconds)
    warm_cooldown: float = 0.0
    hot_cooldown: float = 1.0
    critical_cooldown: float = 3.0
    
    # Monitoring interval (seconds)
    monitor_interval: float = 1.0


# Default policies
THERMAL_POLICIES = {
    "conservative": ThermalPolicy(
        name="conservative",
        cool_threshold=40.0,
        warm_threshold=60.0,
        hot_threshold=75.0,
        warm_concurrent_factor=0.8,
        hot_concurrent_factor=0.3,
        critical_concurrent_factor=0.0,
        hot_cooldown=2.0,
        critical_cooldown=5.0,
    ),
    "normal": ThermalPolicy(
        name="normal",
        cool_threshold=50.0,
        warm_threshold=70.0,
        hot_threshold=85.0,
        warm_concurrent_factor=1.0,
        hot_concurrent_factor=0.5,
        critical_concurrent_factor=0.0,
        hot_cooldown=1.0,
        critical_cooldown=3.0,
    ),
    "aggressive": ThermalPolicy(
        name="aggressive",
        cool_threshold=60.0,
        warm_threshold=80.0,
        hot_threshold=95.0,
        warm_concurrent_factor=1.0,
        hot_concurrent_factor=0.7,
        critical_concurrent_factor=0.3,
        hot_cooldown=0.5,
        critical_cooldown=1.0,
    ),
}


class ThermalMonitor:
    """
    System thermal metrics collector using psutil.
    
    Collects:
    - CPU usage per core
    - CPU frequency
    - Memory usage
    
    Thread-safe for concurrent access.
    """
    
    def __init__(self, sample_interval: float = 0.5):
        """
        Initialize thermal monitor.
        
        Args:
            sample_interval: Interval for CPU sampling (seconds)
        """
        self.sample_interval = sample_interval
        self._last_metrics: Optional[ThermalMetrics] = None
        self._lock = asyncio.Lock()
    
    async def collect(self) -> ThermalMetrics:
        """
        Collect current thermal metrics.
        
        Returns:
            ThermalMetrics snapshot
        """
        if not HAS_PSUTIL:
            # Return default metrics if psutil unavailable
            return ThermalMetrics(state=ThermalState.COOL)
        
        async with self._lock:
            try:
                # CPU usage per core (blocking call, but fast)
                cpu_per_core = psutil.cpu_percent(
                    interval=self.sample_interval,
                    percpu=True,
                )
                
                # CPU frequency
                cpu_freq = psutil.cpu_freq()
                freq_current = cpu_freq.current if cpu_freq else None
                freq_max = cpu_freq.max if cpu_freq else None
                freq_ratio = (freq_current / freq_max) if (freq_current and freq_max) else 1.0
                
                # Memory
                memory = psutil.virtual_memory()
                
                metrics = ThermalMetrics(
                    cpu_percent_avg=sum(cpu_per_core) / len(cpu_per_core) if cpu_per_core else 0.0,
                    cpu_percent_max=max(cpu_per_core) if cpu_per_core else 0.0,
                    cpu_percent_per_core=cpu_per_core,
                    cpu_freq_current=freq_current,
                    cpu_freq_max=freq_max,
                    cpu_freq_ratio=freq_ratio,
                    memory_percent=memory.percent,
                )
                
                self._last_metrics = metrics
                return metrics
                
            except Exception as e:
                logger.warning("Failed to collect thermal metrics: %s", e)
                return ThermalMetrics(state=ThermalState.COOL)
    
    def get_last_metrics(self) -> Optional[ThermalMetrics]:
        """Get last collected metrics (non-blocking)"""
        return self._last_metrics


class ThermalGovernor:
    """
    Adaptive thermal governor.
    
    Monitors system state and adjusts concurrency/batching limits
    to maintain thermal stability.
    
    Usage:
        governor = ThermalGovernor(
            policy="normal",
            base_max_concurrent=3,
            base_batch_window_ms=40,
        )
        
        await governor.start()
        
        # In processing loop
        if governor.should_throttle():
            await governor.cooldown()
        
        limits = governor.get_adjusted_limits()
        scheduler.update_limits(**limits)
    """
    
    def __init__(
        self,
        policy: str = "normal",
        base_max_concurrent: int = 3,
        base_batch_window_ms: int = 40,
        on_state_change: Optional[Callable[[ThermalState, ThermalState], None]] = None,
    ):
        """
        Initialize thermal governor.
        
        Args:
            policy: Thermal policy name ("conservative", "normal", "aggressive")
            base_max_concurrent: Base max concurrent requests
            base_batch_window_ms: Base batching window
            on_state_change: Callback when thermal state changes
        """
        self.policy = THERMAL_POLICIES.get(policy, THERMAL_POLICIES["normal"])
        self.base_max_concurrent = base_max_concurrent
        self.base_batch_window_ms = base_batch_window_ms
        self.on_state_change = on_state_change
        
        self.monitor = ThermalMonitor(sample_interval=0.5)
        
        self._current_state = ThermalState.COOL
        self._current_metrics: Optional[ThermalMetrics] = None
        self._running = False
        self._monitor_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()
        
        # Metrics
        self._state_history: List[tuple[float, ThermalState]] = []
        self._cooldown_count = 0
        self._total_cooldown_time = 0.0
    
    async def start(self) -> None:
        """Start thermal monitoring"""
        if self._running:
            return
        
        self._running = True
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        logger.info("ThermalGovernor started (policy=%s)", self.policy.name)
    
    async def stop(self) -> None:
        """Stop thermal monitoring"""
        self._running = False
        
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        
        logger.info("ThermalGovernor stopped")
    
    async def _monitor_loop(self) -> None:
        """Background monitoring loop"""
        while self._running:
            try:
                metrics = await self.monitor.collect()
                await self._update_state(metrics)
                await asyncio.sleep(self.policy.monitor_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error in monitor loop: %s", e)
                await asyncio.sleep(1.0)
    
    async def _update_state(self, metrics: ThermalMetrics) -> None:
        """Update thermal state based on metrics"""
        async with self._lock:
            self._current_metrics = metrics
            
            # Determine state based on hottest core
            cpu_max = metrics.cpu_percent_max
            old_state = self._current_state
            
            if cpu_max >= self.policy.hot_threshold:
                new_state = ThermalState.CRITICAL
            elif cpu_max >= self.policy.warm_threshold:
                new_state = ThermalState.HOT
            elif cpu_max >= self.policy.cool_threshold:
                new_state = ThermalState.WARM
            else:
                new_state = ThermalState.COOL
            
            # Check for frequency throttling
            if metrics.cpu_freq_ratio < self.policy.freq_throttle_ratio:
                # CPU is being throttled, consider it HOT at minimum
                if new_state == ThermalState.COOL or new_state == ThermalState.WARM:
                    new_state = ThermalState.HOT
            
            metrics.state = new_state
            
            # State change handling
            if new_state != old_state:
                self._current_state = new_state
                self._state_history.append((time.time(), new_state))
                
                # Keep history bounded
                if len(self._state_history) > 100:
                    self._state_history = self._state_history[-100:]
                
                logger.info(
                    "Thermal state changed: %s -> %s (cpu_max=%.1f%%, freq_ratio=%.2f)",
                    old_state.value,
                    new_state.value,
                    cpu_max,
                    metrics.cpu_freq_ratio,
                )
                
                if self.on_state_change:
                    try:
                        self.on_state_change(old_state, new_state)
                    except Exception as e:
                        logger.error("Error in state change callback: %s", e)
    
    @property
    def current_state(self) -> ThermalState:
        """Current thermal state"""
        return self._current_state
    
    @property
    def current_metrics(self) -> Optional[ThermalMetrics]:
        """Current thermal metrics"""
        return self._current_metrics
    
    def should_throttle(self) -> bool:
        """Check if processing should be throttled"""
        return self._current_state in (ThermalState.HOT, ThermalState.CRITICAL)
    
    def should_pause(self) -> bool:
        """Check if processing should be paused"""
        return self._current_state == ThermalState.CRITICAL
    
    async def cooldown(self) -> float:
        """
        Perform cooldown if needed.
        
        Returns:
            Time spent cooling down (seconds)
        """
        state = self._current_state
        
        if state == ThermalState.CRITICAL:
            duration = self.policy.critical_cooldown
        elif state == ThermalState.HOT:
            duration = self.policy.hot_cooldown
        elif state == ThermalState.WARM:
            duration = self.policy.warm_cooldown
        else:
            return 0.0
        
        if duration > 0:
            logger.debug("Cooling down for %.1fs (state=%s)", duration, state.value)
            self._cooldown_count += 1
            self._total_cooldown_time += duration
            await asyncio.sleep(duration)
        
        return duration
    
    def get_adjusted_limits(self) -> Dict[str, Any]:
        """
        Get adjusted limits based on current thermal state.
        
        Returns:
            Dict with adjusted max_concurrent_requests and batch_window_ms
        """
        state = self._current_state
        
        # Concurrency adjustment
        if state == ThermalState.CRITICAL:
            concurrent_factor = self.policy.critical_concurrent_factor
        elif state == ThermalState.HOT:
            concurrent_factor = self.policy.hot_concurrent_factor
        elif state == ThermalState.WARM:
            concurrent_factor = self.policy.warm_concurrent_factor
        else:
            concurrent_factor = 1.0
        
        adjusted_concurrent = max(1, int(self.base_max_concurrent * concurrent_factor))
        
        # Batching window adjustment
        if state == ThermalState.CRITICAL:
            window_factor = self.policy.critical_window_factor
        elif state == ThermalState.HOT:
            window_factor = self.policy.hot_window_factor
        elif state == ThermalState.WARM:
            window_factor = self.policy.warm_window_factor
        else:
            window_factor = 1.0
        
        adjusted_window = int(self.base_batch_window_ms * window_factor)
        
        return {
            "max_concurrent_requests": adjusted_concurrent,
            "batch_window_ms": adjusted_window,
        }
    
    def set_policy(self, policy: str) -> None:
        """
        Change thermal policy.
        
        Args:
            policy: Policy name ("conservative", "normal", "aggressive")
        """
        if policy in THERMAL_POLICIES:
            old_policy = self.policy.name
            self.policy = THERMAL_POLICIES[policy]
            logger.info("Thermal policy changed: %s -> %s", old_policy, policy)
        else:
            logger.warning("Unknown thermal policy: %s", policy)
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get governor metrics"""
        return {
            "policy": self.policy.name,
            "current_state": self._current_state.value,
            "base_max_concurrent": self.base_max_concurrent,
            "base_batch_window_ms": self.base_batch_window_ms,
            "adjusted_limits": self.get_adjusted_limits(),
            "cooldown_count": self._cooldown_count,
            "total_cooldown_time": self._total_cooldown_time,
            "state_history_count": len(self._state_history),
            "current_metrics": self._current_metrics.to_dict() if self._current_metrics else None,
        }

