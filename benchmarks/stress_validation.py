#!/usr/bin/env python3
"""
Stress Test for LIR Validation

Runs N LLM calls with optional concurrency, proper warmup, and continuous thermal sampling.
Designed to reach steady state and reveal true scaling differences.

Usage:
    python scripts/stress_validation.py --scenario=legacy --calls=200
    python scripts/stress_validation.py --scenario=lir --calls=200 --concurrent=4
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import psutil

# Add project root to path
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Fixed test files (first 5 from repo_index.json)
TEST_FILES = [
    {
        "path": "codewiki/codewiki/inspect_lifecycle_result.py",
        "kind": "python",
        "size_bytes": 6345,
    },
    {
        "path": "codewiki/codewiki/__init__.py",
        "kind": "python",
        "size_bytes": 1401,
    },
    {
        "path": "codewiki/codewiki/lifecycle_classifier.py",
        "kind": "python",
        "size_bytes": 27311,
    },
    {
        "path": "codewiki/codewiki/cli.py",
        "kind": "python",
        "size_bytes": 2720,
    },
    {
        "path": "codewiki/codewiki/llm_client.py",
        "kind": "python",
        "size_bytes": 10361,
    },
]

RESULTS_DIR = PROJECT_ROOT / "results"


@dataclass
class StressMetrics:
    """Metrics collected during stress test"""
    scenario: str
    total_calls: int
    concurrency: int
    
    # Timing
    runtime_seconds: float = 0.0
    warmup_seconds: float = 0.0
    
    # Latency histogram (all individual calls)
    latencies: List[float] = field(default_factory=list)
    
    # Thermal timeline (sampled every 2s)
    thermal_timeline: List[Dict[str, Any]] = field(default_factory=list)
    
    # Success tracking
    successful_calls: int = 0
    failed_calls: int = 0
    
    def _percentile(self, p: float) -> float:
        """Calculate percentile from latencies"""
        if not self.latencies:
            return 0.0
        sorted_latencies = sorted(self.latencies)
        idx = int(len(sorted_latencies) * p)
        return sorted_latencies[min(idx, len(sorted_latencies) - 1)]
    
    @property
    def p50(self) -> float:
        return self._percentile(0.50)
    
    @property
    def p95(self) -> float:
        return self._percentile(0.95)
    
    @property
    def p99(self) -> float:
        return self._percentile(0.99)
    
    @property
    def avg_latency(self) -> float:
        if not self.latencies:
            return 0.0
        return sum(self.latencies) / len(self.latencies)
    
    @property
    def hot_duration_seconds(self) -> float:
        """Time with max_cpu > 80%"""
        return sum(2.0 for s in self.thermal_timeline if s.get('max_cpu', 0) > 80)
    
    @property
    def warm_duration_seconds(self) -> float:
        """Time with max_cpu > 50%"""
        return sum(2.0 for s in self.thermal_timeline if s.get('max_cpu', 0) > 50)
    
    @property
    def throughput_calls_per_min(self) -> float:
        if self.runtime_seconds <= 0:
            return 0.0
        return (self.total_calls / self.runtime_seconds) * 60
    
    def to_dict(self) -> Dict[str, Any]:
        """Export to dictionary for JSON serialization"""
        return {
            "scenario": self.scenario,
            "total_calls": self.total_calls,
            "concurrency": self.concurrency,
            "runtime_seconds": round(self.runtime_seconds, 2),
            "warmup_seconds": round(self.warmup_seconds, 2),
            "llm": {
                "total_calls": self.total_calls,
                "successful_calls": self.successful_calls,
                "failed_calls": self.failed_calls,
                "avg_latency_seconds": round(self.avg_latency, 3),
                "p50_latency_seconds": round(self.p50, 3),
                "p95_latency_seconds": round(self.p95, 3),
                "p99_latency_seconds": round(self.p99, 3),
            },
            "thermal": {
                "samples_count": len(self.thermal_timeline),
                "hot_duration_seconds": round(self.hot_duration_seconds, 1),
                "warm_duration_seconds": round(self.warm_duration_seconds, 1),
                "max_cpu_percent": max((s.get('max_cpu', 0) for s in self.thermal_timeline), default=0),
                "avg_cpu_percent": sum(s.get('avg_cpu', 0) for s in self.thermal_timeline) / len(self.thermal_timeline) if self.thermal_timeline else 0,
            },
            "throughput": {
                "calls_per_minute": round(self.throughput_calls_per_min, 2),
            },
            "quality": {
                "parse_success_rate": self.successful_calls / self.total_calls if self.total_calls > 0 else 0,
                "classifications": {},  # Filled by caller if needed
            },
            "latency_histogram": [round(l, 3) for l in self.latencies],
            "thermal_timeline": self.thermal_timeline,
        }
    
    def save(self, path: Path) -> None:
        """Save metrics to JSON file"""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w') as f:
            json.dump(self.to_dict(), f, indent=2)
    
    def summary(self) -> str:
        """Generate human-readable summary"""
        return f"""
=== Stress Test Results: {self.scenario} ===
Calls: {self.total_calls} (concurrency={self.concurrency})
Runtime: {self.runtime_seconds:.1f}s (warmup: {self.warmup_seconds:.1f}s)
Throughput: {self.throughput_calls_per_min:.1f} calls/min

Latency:
  P50: {self.p50:.2f}s
  P95: {self.p95:.2f}s
  P99: {self.p99:.2f}s
  Avg: {self.avg_latency:.2f}s

Thermal ({len(self.thermal_timeline)} samples):
  Hot duration (>80% CPU): {self.hot_duration_seconds:.1f}s
  Warm duration (>50% CPU): {self.warm_duration_seconds:.1f}s

Success: {self.successful_calls}/{self.total_calls} ({self.successful_calls/self.total_calls*100:.1f}%)
"""


def build_prompt(file_entry: Dict[str, Any]) -> tuple[str, str]:
    """Build classification prompt for a file entry"""
    path = file_entry.get("path", "")
    kind = file_entry.get("kind", "other")
    size = file_entry.get("size_bytes", 0)
    
    system_prompt = (
        "You are a senior software engineer specializing in repository hygiene. "
        "Classify files as: keep, review, archive, or delete. "
        "Output ONLY a JSON object with keys: recommendation, confidence, reasons."
    )
    
    user_prompt = f"""Analyze this file:
Path: {path}
Type: {kind}
Size: {size} bytes

Respond with a JSON object."""
    
    return system_prompt, user_prompt


async def thermal_sampling_loop(
    metrics: StressMetrics,
    interval: float = 2.0,
    stop_event: asyncio.Event = None,
) -> None:
    """Continuously sample thermal state"""
    start_time = time.time()
    
    while stop_event is None or not stop_event.is_set():
        try:
            cpu_avg = psutil.cpu_percent(interval=0.1)
            per_cpu = psutil.cpu_percent(interval=0, percpu=True)
            max_cpu = max(per_cpu) if per_cpu else 0
            memory = psutil.virtual_memory().percent
            
            sample = {
                "timestamp": round(time.time() - start_time, 1),
                "avg_cpu": round(cpu_avg, 1),
                "max_cpu": round(max_cpu, 1),
                "memory_percent": round(memory, 1),
            }
            metrics.thermal_timeline.append(sample)
            
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"Thermal sampling error: {e}")
            await asyncio.sleep(interval)


async def run_legacy_call(prompt: str, system_prompt: str) -> Optional[str]:
    """Run a single call using legacy LocalLLMClient"""
    from codewiki.llm_client import LocalLLMClient
    
    # Run in thread pool since legacy client is sync
    loop = asyncio.get_event_loop()
    
    def sync_call():
        client = LocalLLMClient()
        if not client.is_available():
            return None
        return client.generate(prompt, system_prompt)
    
    return await loop.run_in_executor(None, sync_call)


async def run_lir_call(
    client,
    prompt: str,
    system_prompt: str,
) -> Optional[str]:
    """Run a single call using LIR client"""
    return await client.generate(prompt, system_prompt)


async def run_lir_batch(
    client,
    prompts: List[str],
    system_prompts: List[str],
) -> List[Optional[str]]:
    """Run batch of calls using LIR client"""
    return await client.generate_batch(prompts, system_prompts)


async def run_stress_test(
    scenario: str,
    num_calls: int = 200,
    concurrency: int = 1,
    warmup_calls: int = 3,
) -> StressMetrics:
    """
    Run stress test with proper warmup and thermal sampling.
    
    Args:
        scenario: "legacy" or "lir"
        num_calls: Total number of LLM calls
        concurrency: Number of concurrent requests (LIR only, legacy always 1)
        warmup_calls: Number of warmup calls (not counted)
    """
    use_lir = scenario == "lir"
    actual_concurrency = concurrency if use_lir else 1
    
    metrics = StressMetrics(
        scenario=f"{scenario}_c{actual_concurrency}",
        total_calls=num_calls,
        concurrency=actual_concurrency,
    )
    
    print(f"\n{'='*60}")
    print(f"Starting stress test: {metrics.scenario}")
    print(f"Calls: {num_calls}, Concurrency: {actual_concurrency}, Warmup: {warmup_calls}")
    print(f"{'='*60}\n")
    
    # Initialize LIR client if needed
    lir_client = None
    if use_lir:
        from lir import LIRClient
        lir_client = LIRClient(policy="balanced")
        await lir_client.start()
    
    # Build all prompts upfront (fixed, repeated)
    all_prompts = []
    all_system_prompts = []
    for i in range(num_calls + warmup_calls):
        file_entry = TEST_FILES[i % len(TEST_FILES)]
        system_prompt, user_prompt = build_prompt(file_entry)
        all_prompts.append(user_prompt)
        all_system_prompts.append(system_prompt)
    
    # Warmup phase (not recorded)
    print(f"Running {warmup_calls} warmup calls...")
    warmup_start = time.time()
    for i in range(warmup_calls):
        if use_lir:
            await run_lir_call(lir_client, all_prompts[i], all_system_prompts[i])
        else:
            await run_legacy_call(all_prompts[i], all_system_prompts[i])
    metrics.warmup_seconds = time.time() - warmup_start
    print(f"Warmup complete in {metrics.warmup_seconds:.1f}s\n")
    
    # Start thermal sampling
    stop_event = asyncio.Event()
    sampling_task = asyncio.create_task(
        thermal_sampling_loop(metrics, interval=2.0, stop_event=stop_event)
    )
    
    # Main test
    print(f"Running {num_calls} test calls...")
    start = time.time()
    
    # Offset prompts by warmup count
    test_prompts = all_prompts[warmup_calls:]
    test_system_prompts = all_system_prompts[warmup_calls:]
    
    if actual_concurrency == 1:
        # Sequential mode
        for i in range(num_calls):
            call_start = time.time()
            
            try:
                if use_lir:
                    result = await run_lir_call(lir_client, test_prompts[i], test_system_prompts[i])
                else:
                    result = await run_legacy_call(test_prompts[i], test_system_prompts[i])
                
                if result:
                    metrics.successful_calls += 1
                else:
                    metrics.failed_calls += 1
            except Exception as e:
                print(f"Call {i} failed: {e}")
                metrics.failed_calls += 1
            
            latency = time.time() - call_start
            metrics.latencies.append(latency)
            
            # Progress update every 10 calls
            if (i + 1) % 10 == 0:
                elapsed = time.time() - start
                rate = (i + 1) / elapsed * 60
                print(f"  Progress: {i+1}/{num_calls} ({rate:.1f} calls/min)")
    
    else:
        # Concurrent mode (LIR only)
        for batch_start in range(0, num_calls, actual_concurrency):
            batch_end = min(batch_start + actual_concurrency, num_calls)
            batch_prompts = test_prompts[batch_start:batch_end]
            batch_system = test_system_prompts[batch_start:batch_end]
            
            call_start = time.time()
            
            try:
                results = await run_lir_batch(lir_client, batch_prompts, batch_system)
                
                for result in results:
                    if result:
                        metrics.successful_calls += 1
                    else:
                        metrics.failed_calls += 1
            except Exception as e:
                print(f"Batch {batch_start}-{batch_end} failed: {e}")
                metrics.failed_calls += len(batch_prompts)
            
            batch_latency = time.time() - call_start
            # Record per-call latency as batch_time / batch_size
            per_call_latency = batch_latency / len(batch_prompts)
            for _ in batch_prompts:
                metrics.latencies.append(per_call_latency)
            
            # Progress update
            completed = batch_end
            if completed % 20 == 0 or completed == num_calls:
                elapsed = time.time() - start
                rate = completed / elapsed * 60
                print(f"  Progress: {completed}/{num_calls} ({rate:.1f} calls/min)")
    
    metrics.runtime_seconds = time.time() - start
    
    # Stop thermal sampling
    stop_event.set()
    sampling_task.cancel()
    try:
        await sampling_task
    except asyncio.CancelledError:
        pass
    
    # Cleanup LIR client
    if lir_client:
        await lir_client.stop()
    
    print(f"\nTest complete!")
    print(metrics.summary())
    
    return metrics


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="LIR Stress Test")
    parser.add_argument(
        "--scenario",
        choices=["legacy", "lir"],
        default="lir",
        help="Test scenario: legacy or lir",
    )
    parser.add_argument(
        "--calls",
        type=int,
        default=200,
        help="Number of LLM calls (default: 200)",
    )
    parser.add_argument(
        "--concurrent",
        type=int,
        default=1,
        help="Concurrency level (default: 1, LIR only)",
    )
    parser.add_argument(
        "--warmup",
        type=int,
        default=3,
        help="Warmup calls (default: 3)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output file path (default: results/stress_<scenario>.json)",
    )
    return parser.parse_args()


async def main() -> int:
    args = parse_args()
    
    # Ensure results directory exists
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    
    # Run stress test
    metrics = await run_stress_test(
        scenario=args.scenario,
        num_calls=args.calls,
        concurrency=args.concurrent,
        warmup_calls=args.warmup,
    )
    
    # Save results
    output_path = Path(args.output) if args.output else RESULTS_DIR / f"stress_{metrics.scenario}.json"
    metrics.save(output_path)
    print(f"\nResults saved to: {output_path}")
    
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

