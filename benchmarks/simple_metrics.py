"""
Simple Metrics Collection for LIR Validation

Minimal metrics collector - just enough to validate LIR improvements.
Not a full observability platform.

Usage:
    metrics = SimpleMetrics("scenario_name")
    metrics.start()
    
    # During work
    metrics.record_llm_call(success=True, latency=1.5)
    metrics.sample_thermal()
    
    # After work
    metrics.stop()
    metrics.save("results/metrics_scenario.json")
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import psutil


@dataclass
class ThermalSample:
    """Single thermal measurement"""
    timestamp: float  # Seconds since start
    cpu_avg: float    # Average CPU %
    cpu_max: float    # Max single core %
    memory_percent: float


@dataclass 
class LLMCallMetric:
    """Single LLM call measurement"""
    timestamp: float  # Seconds since start
    success: bool
    latency_seconds: float
    tokens_estimated: int = 0


@dataclass
class SimpleMetrics:
    """
    Simple metrics collector for LIR validation.
    
    Collects:
    - Runtime (start/stop)
    - LLM call counts and latencies
    - Thermal samples (CPU%, max core)
    - Parse success rate
    
    Extended for stress testing:
    - Latency histogram for P50/P95/P99
    - Thermal timeline for hot_duration analysis
    - Throughput calculation
    
    Attributes:
        scenario: Name of the scenario being measured
    """
    scenario: str
    
    # Timing
    _start_time: Optional[float] = field(default=None, repr=False)
    _end_time: Optional[float] = field(default=None, repr=False)
    _warmup_seconds: float = field(default=0.0, repr=False)
    
    # LLM metrics
    _llm_calls: List[LLMCallMetric] = field(default_factory=list, repr=False)
    _parse_success: int = field(default=0, repr=False)
    _parse_total: int = field(default=0, repr=False)
    
    # Stress test: raw latency histogram
    _latencies: List[float] = field(default_factory=list, repr=False)
    
    # Thermal samples
    _thermal_samples: List[ThermalSample] = field(default_factory=list, repr=False)
    
    # Stress test: thermal timeline (dict format for JSON)
    _thermal_timeline: List[Dict[str, Any]] = field(default_factory=list, repr=False)
    
    # Classification results
    _classifications: Dict[str, int] = field(default_factory=dict, repr=False)
    
    # Concurrency (for stress tests)
    _concurrency: int = field(default=1, repr=False)
    
    def start(self) -> None:
        """Start timing and take initial thermal sample"""
        self._start_time = time.time()
        self._thermal_samples = []
        self._llm_calls = []
        self.sample_thermal()
    
    def stop(self) -> None:
        """Stop timing and take final thermal sample"""
        self._end_time = time.time()
        self.sample_thermal()
    
    @property
    def runtime_seconds(self) -> float:
        """Total runtime in seconds"""
        if self._start_time is None:
            return 0.0
        end = self._end_time or time.time()
        return end - self._start_time
    
    def sample_thermal(self) -> ThermalSample:
        """Take a thermal sample and record it"""
        elapsed = time.time() - (self._start_time or time.time())
        
        cpu_avg = psutil.cpu_percent(interval=0.1)
        per_cpu = psutil.cpu_percent(interval=0, percpu=True)
        cpu_max = max(per_cpu) if per_cpu else 0.0
        memory = psutil.virtual_memory().percent
        
        sample = ThermalSample(
            timestamp=elapsed,
            cpu_avg=cpu_avg,
            cpu_max=cpu_max,
            memory_percent=memory,
        )
        self._thermal_samples.append(sample)
        return sample
    
    def record_llm_call(
        self,
        success: bool,
        latency_seconds: float,
        tokens_estimated: int = 0,
    ) -> None:
        """Record a single LLM call"""
        elapsed = time.time() - (self._start_time or time.time())
        
        metric = LLMCallMetric(
            timestamp=elapsed,
            success=success,
            latency_seconds=latency_seconds,
            tokens_estimated=tokens_estimated,
        )
        self._llm_calls.append(metric)
    
    def record_parse_result(self, success: bool) -> None:
        """Record a parse attempt result"""
        self._parse_total += 1
        if success:
            self._parse_success += 1
    
    def record_classification(self, decision: str) -> None:
        """Record a classification decision"""
        self._classifications[decision] = self._classifications.get(decision, 0) + 1
    
    @property
    def llm_call_count(self) -> int:
        """Total LLM calls made"""
        return len(self._llm_calls)
    
    @property
    def llm_success_count(self) -> int:
        """Successful LLM calls"""
        return sum(1 for c in self._llm_calls if c.success)
    
    @property
    def parse_success_rate(self) -> float:
        """Parse success rate (0.0 - 1.0)"""
        if self._parse_total == 0:
            return 1.0
        return self._parse_success / self._parse_total
    
    @property
    def avg_latency(self) -> float:
        """Average LLM call latency in seconds"""
        if not self._llm_calls:
            return 0.0
        return sum(c.latency_seconds for c in self._llm_calls) / len(self._llm_calls)
    
    def _get_latencies(self) -> List[float]:
        """Get all latencies from either histogram or LLM calls"""
        if self._latencies:
            return self._latencies
        return [c.latency_seconds for c in self._llm_calls]
    
    def _percentile(self, p: float) -> float:
        """Calculate percentile from latencies"""
        latencies = self._get_latencies()
        if not latencies:
            return 0.0
        sorted_latencies = sorted(latencies)
        idx = int(len(sorted_latencies) * p)
        return sorted_latencies[min(idx, len(sorted_latencies) - 1)]
    
    @property
    def p50_latency(self) -> float:
        """50th percentile (median) LLM call latency"""
        return self._percentile(0.50)
    
    @property
    def p95_latency(self) -> float:
        """95th percentile LLM call latency"""
        return self._percentile(0.95)
    
    @property
    def p99_latency(self) -> float:
        """99th percentile LLM call latency"""
        return self._percentile(0.99)
    
    def record_latency(self, latency_seconds: float) -> None:
        """Record a raw latency value (for stress tests)"""
        self._latencies.append(latency_seconds)
    
    @property
    def max_cpu_percent(self) -> float:
        """Maximum single-core CPU usage observed"""
        if not self._thermal_samples:
            return 0.0
        return max(s.cpu_max for s in self._thermal_samples)
    
    @property
    def avg_cpu_percent(self) -> float:
        """Average CPU usage during run"""
        if not self._thermal_samples:
            return 0.0
        return sum(s.cpu_avg for s in self._thermal_samples) / len(self._thermal_samples)
    
    @property
    def hot_duration_seconds(self) -> float:
        """Time spent with max CPU > 80% (stress test metric)"""
        # Use thermal_timeline if available (stress test), else thermal_samples
        if self._thermal_timeline:
            return sum(2.0 for s in self._thermal_timeline if s.get('max_cpu', 0) > 80)
        return sum(2.0 for s in self._thermal_samples if s.cpu_max > 80)
    
    @property
    def warm_duration_seconds(self) -> float:
        """Time spent with max CPU > 50%"""
        if self._thermal_timeline:
            return sum(2.0 for s in self._thermal_timeline if s.get('max_cpu', 0) > 50)
        return sum(2.0 for s in self._thermal_samples if s.cpu_max > 50)
    
    @property
    def throughput_calls_per_min(self) -> float:
        """Throughput in calls per minute"""
        if self.runtime_seconds <= 0:
            return 0.0
        total_calls = len(self._latencies) if self._latencies else self.llm_call_count
        return (total_calls / self.runtime_seconds) * 60
    
    def record_thermal_sample(self, timestamp: float, avg_cpu: float, max_cpu: float, memory: float = 0) -> None:
        """Record a thermal sample to timeline (for stress tests)"""
        self._thermal_timeline.append({
            "timestamp": round(timestamp, 1),
            "avg_cpu": round(avg_cpu, 1),
            "max_cpu": round(max_cpu, 1),
            "memory_percent": round(memory, 1),
        })
    
    def to_dict(self) -> Dict[str, Any]:
        """Export metrics as dictionary"""
        total_calls = len(self._latencies) if self._latencies else self.llm_call_count
        thermal_samples = len(self._thermal_timeline) if self._thermal_timeline else len(self._thermal_samples)
        
        result = {
            "scenario": self.scenario,
            "runtime_seconds": round(self.runtime_seconds, 2),
            "warmup_seconds": round(self._warmup_seconds, 2),
            "concurrency": self._concurrency,
            "llm": {
                "total_calls": total_calls,
                "successful_calls": self.llm_success_count,
                "avg_latency_seconds": round(self.avg_latency, 3),
                "p50_latency_seconds": round(self.p50_latency, 3),
                "p95_latency_seconds": round(self.p95_latency, 3),
                "p99_latency_seconds": round(self.p99_latency, 3),
            },
            "quality": {
                "parse_success_rate": round(self.parse_success_rate, 3),
                "parse_total": self._parse_total,
                "classifications": self._classifications,
            },
            "thermal": {
                "avg_cpu_percent": round(self.avg_cpu_percent, 1),
                "max_cpu_percent": round(self.max_cpu_percent, 1),
                "samples_count": thermal_samples,
                "hot_duration_seconds": round(self.hot_duration_seconds, 1),
                "warm_duration_seconds": round(self.warm_duration_seconds, 1),
            },
            "throughput": {
                "calls_per_minute": round(self.throughput_calls_per_min, 2),
            },
        }
        
        # Include histogram and timeline for stress tests
        if self._latencies:
            result["latency_histogram"] = [round(l, 3) for l in self._latencies]
        if self._thermal_timeline:
            result["thermal_timeline"] = self._thermal_timeline
        
        return result
    
    def save(self, path: str | Path) -> None:
        """Save metrics to JSON file"""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)
    
    @classmethod
    def load(cls, path: str | Path) -> Dict[str, Any]:
        """Load metrics from JSON file"""
        with open(path) as f:
            return json.load(f)
    
    def summary(self) -> str:
        """Generate human-readable summary"""
        total_calls = len(self._latencies) if self._latencies else self.llm_call_count
        
        lines = [
            f"=== {self.scenario} ===",
            f"Runtime: {self.runtime_seconds:.1f}s",
            f"Throughput: {self.throughput_calls_per_min:.1f} calls/min",
            f"LLM calls: {total_calls} ({self.llm_success_count} successful)",
            "",
            "Latency:",
            f"  P50: {self.p50_latency:.2f}s",
            f"  P95: {self.p95_latency:.2f}s",
            f"  P99: {self.p99_latency:.2f}s",
            f"  Avg: {self.avg_latency:.2f}s",
            "",
            "Thermal:",
            f"  Avg CPU: {self.avg_cpu_percent:.1f}%",
            f"  Max CPU: {self.max_cpu_percent:.1f}%",
            f"  Hot duration (>80%): {self.hot_duration_seconds:.1f}s",
            f"  Warm duration (>50%): {self.warm_duration_seconds:.1f}s",
        ]
        
        if self._classifications:
            lines.append("")
            lines.append("Classifications:")
            for decision, count in sorted(self._classifications.items()):
                lines.append(f"  {decision}: {count}")
        
        return "\n".join(lines)

