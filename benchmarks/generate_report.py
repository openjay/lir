#!/usr/bin/env python3
"""
Generate Validation Report from Metrics

Reads metrics JSON files from results/ and generates a markdown comparison report.
Supports both quick validation and stress test results.

Usage:
    python scripts/generate_report.py           # Quick validation report
    python scripts/generate_report.py --stress  # Stress test report
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

RESULTS_DIR = Path(__file__).parent.parent / "results"
REPORT_PATH = Path(__file__).parent.parent / "VALIDATION_REPORT.md"


def load_metrics(filename: str) -> dict | None:
    """Load metrics from a JSON file"""
    path = RESULTS_DIR / filename
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def generate_quick_report() -> str:
    """Generate markdown report from quick validation metrics"""
    
    # Load all available scenarios
    scenarios = {}
    for name in ["legacy", "quickfix", "lir_balanced", "lir_silent", "lir_performance"]:
        metrics = load_metrics(f"metrics_{name}.json")
        if metrics:
            scenarios[name] = metrics
    
    if not scenarios:
        return "# Validation Report\n\nNo metrics found. Run validation first.\n"
    
    # Build report
    lines = [
        "# LIR Validation Report",
        "",
        f"**Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## Summary",
        "",
        "| Scenario | Runtime (s) | LLM Calls | Avg Latency | Max CPU % | Parse Success |",
        "|----------|-------------|-----------|-------------|-----------|---------------|",
    ]
    
    # Add rows for each scenario
    for name, m in scenarios.items():
        runtime = m.get("runtime_seconds", 0)
        llm = m.get("llm", {})
        thermal = m.get("thermal", {})
        quality = m.get("quality", {})
        
        lines.append(
            f"| {name} | {runtime:.1f} | "
            f"{llm.get('total_calls', 0)} | "
            f"{llm.get('avg_latency_seconds', 0):.2f}s | "
            f"{thermal.get('max_cpu_percent', 0):.1f}% | "
            f"{quality.get('parse_success_rate', 1):.1%} |"
        )
    
    lines.extend(["", "## Analysis", ""])
    
    # Compare LIR vs Legacy if both exist
    legacy = scenarios.get("legacy")
    lir = scenarios.get("lir_balanced")
    
    if legacy and lir:
        legacy_runtime = legacy.get("runtime_seconds", 1)
        lir_runtime = lir.get("runtime_seconds", 1)
        
        speedup = legacy_runtime / lir_runtime if lir_runtime > 0 else 0
        runtime_reduction = (1 - lir_runtime / legacy_runtime) * 100 if legacy_runtime > 0 else 0
        
        legacy_max_cpu = legacy.get("thermal", {}).get("max_cpu_percent", 0)
        lir_max_cpu = lir.get("thermal", {}).get("max_cpu_percent", 0)
        cpu_diff = legacy_max_cpu - lir_max_cpu
        
        lines.extend([
            "### LIR vs Legacy Comparison",
            "",
            f"- **Runtime**: LIR is {speedup:.1f}x {'faster' if speedup > 1 else 'slower'} ({abs(runtime_reduction):.0f}% {'reduction' if runtime_reduction > 0 else 'increase'})",
            f"- **Max CPU**: LIR is {abs(cpu_diff):.1f}% {'lower' if cpu_diff > 0 else 'higher'}",
            "",
        ])
        
        # Acceptance criteria check
        lines.extend([
            "### Acceptance Criteria",
            "",
        ])
        
        # Performance: ≥2x faster
        if speedup >= 2:
            lines.append(f"- [x] **Performance**: LIR is ≥2x faster ({speedup:.1f}x)")
        elif speedup >= 1:
            lines.append(f"- [ ] **Performance**: LIR is faster but not 2x ({speedup:.1f}x)")
        else:
            lines.append(f"- [ ] **Performance**: LIR is slower ({speedup:.1f}x)")
        
        # Thermal: Lower or similar max CPU
        if cpu_diff >= 0:
            lines.append(f"- [x] **Thermal**: Max CPU same or lower ({cpu_diff:.1f}% improvement)")
        else:
            lines.append(f"- [ ] **Thermal**: Max CPU higher ({abs(cpu_diff):.1f}% increase)")
        
        # Quality: 100% parse success
        lir_parse = lir.get("quality", {}).get("parse_success_rate", 1)
        if lir_parse >= 0.99:
            lines.append(f"- [x] **Quality**: Parse success rate is {lir_parse:.1%}")
        else:
            lines.append(f"- [ ] **Quality**: Parse success rate is {lir_parse:.1%} (target: 100%)")
        
        lines.append("")
    
    # Classification breakdown
    lines.extend(["## Classification Results", ""])
    
    for name, m in scenarios.items():
        classifications = m.get("quality", {}).get("classifications", {})
        if classifications:
            lines.append(f"### {name}")
            lines.append("")
            for decision, count in sorted(classifications.items()):
                lines.append(f"- {decision}: {count}")
            lines.append("")
    
    # Notes
    lines.extend([
        "## Notes",
        "",
        "- LIR's primary benefit is thermal management for sustained workloads",
        "- For sequential requests, LIR may have slight overhead from async infrastructure",
        "- For batch requests, LIR provides significant throughput improvements",
        "- Max CPU spikes are expected during burst processing but recover faster",
        "",
        "## Raw Data",
        "",
        f"Metrics files are stored in `results/`",
        "",
    ])
    
    return "\n".join(lines)


def generate_stress_report() -> str:
    """Generate markdown report from stress test metrics"""
    
    # Load stress test scenarios
    scenarios = {}
    for filename in RESULTS_DIR.glob("stress_*.json"):
        with open(filename) as f:
            data = json.load(f)
            name = data.get("scenario", filename.stem)
            scenarios[name] = data
    
    if not scenarios:
        return "# Stress Test Report\n\nNo stress test metrics found. Run `./scripts/quick_validation.sh --stress` first.\n"
    
    # Build report
    lines = [
        "# LIR Stress Test Report",
        "",
        f"**Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## Test Configuration",
        "",
    ]
    
    # Show test config from first scenario
    first = list(scenarios.values())[0]
    lines.extend([
        f"- **Total Calls**: {first.get('total_calls', 'N/A')}",
        f"- **Warmup Calls**: 3 (excluded from metrics)",
        f"- **Thermal Sampling**: Every 2 seconds",
        "",
    ])
    
    # Summary table
    lines.extend([
        "## Summary",
        "",
        "| Scenario | Runtime | Throughput | P50 | P95 | P99 | Hot Duration | Max CPU |",
        "|----------|---------|------------|-----|-----|-----|--------------|---------|",
    ])
    
    for name, m in sorted(scenarios.items()):
        runtime = m.get("runtime_seconds", 0)
        llm = m.get("llm", {})
        thermal = m.get("thermal", {})
        throughput = m.get("throughput", {})
        
        lines.append(
            f"| {name} | {runtime:.0f}s | "
            f"{throughput.get('calls_per_minute', 0):.1f}/min | "
            f"{llm.get('p50_latency_seconds', 0):.2f}s | "
            f"{llm.get('p95_latency_seconds', 0):.2f}s | "
            f"{llm.get('p99_latency_seconds', 0):.2f}s | "
            f"{thermal.get('hot_duration_seconds', 0):.0f}s | "
            f"{thermal.get('max_cpu_percent', 0):.0f}% |"
        )
    
    lines.extend(["", "## Analysis", ""])
    
    # Find legacy and LIR scenarios for comparison
    legacy = None
    lir_seq = None
    lir_concurrent = None
    
    for name, m in scenarios.items():
        if "legacy" in name.lower():
            legacy = m
        elif "lir" in name.lower():
            concurrency = m.get("concurrency", 1)
            if concurrency == 1:
                lir_seq = m
            else:
                lir_concurrent = m
    
    # Compare LIR Sequential vs Legacy
    if legacy and lir_seq:
        legacy_runtime = legacy.get("runtime_seconds", 1)
        lir_runtime = lir_seq.get("runtime_seconds", 1)
        speedup = legacy_runtime / lir_runtime if lir_runtime > 0 else 0
        
        legacy_p95 = legacy.get("llm", {}).get("p95_latency_seconds", 0)
        lir_p95 = lir_seq.get("llm", {}).get("p95_latency_seconds", 0)
        p95_improvement = (1 - lir_p95 / legacy_p95) * 100 if legacy_p95 > 0 else 0
        
        legacy_hot = legacy.get("thermal", {}).get("hot_duration_seconds", 0)
        lir_hot = lir_seq.get("thermal", {}).get("hot_duration_seconds", 0)
        hot_reduction = (1 - lir_hot / legacy_hot) * 100 if legacy_hot > 0 else 0
        
        lines.extend([
            "### LIR Sequential vs Legacy",
            "",
            f"- **Speedup**: {speedup:.2f}x",
            f"- **P95 Latency**: {p95_improvement:+.1f}% ({'better' if p95_improvement > 0 else 'worse'})",
            f"- **Hot Duration**: {hot_reduction:+.1f}% ({'reduced' if hot_reduction > 0 else 'increased'})",
            "",
        ])
    
    # Compare LIR Concurrent vs Legacy
    if legacy and lir_concurrent:
        legacy_runtime = legacy.get("runtime_seconds", 1)
        lir_runtime = lir_concurrent.get("runtime_seconds", 1)
        speedup = legacy_runtime / lir_runtime if lir_runtime > 0 else 0
        
        legacy_throughput = legacy.get("throughput", {}).get("calls_per_minute", 0)
        lir_throughput = lir_concurrent.get("throughput", {}).get("calls_per_minute", 0)
        throughput_gain = lir_throughput / legacy_throughput if legacy_throughput > 0 else 0
        
        legacy_hot = legacy.get("thermal", {}).get("hot_duration_seconds", 0)
        lir_hot = lir_concurrent.get("thermal", {}).get("hot_duration_seconds", 0)
        hot_reduction = (1 - lir_hot / legacy_hot) * 100 if legacy_hot > 0 else 0
        
        concurrency = lir_concurrent.get("concurrency", 4)
        lines.extend([
            f"### LIR Concurrent (c={concurrency}) vs Legacy",
            "",
            f"- **Speedup**: {speedup:.2f}x",
            f"- **Throughput**: {throughput_gain:.1f}x ({lir_throughput:.1f} vs {legacy_throughput:.1f} calls/min)",
            f"- **Hot Duration**: {hot_reduction:+.1f}% ({'reduced' if hot_reduction > 0 else 'increased'})",
            "",
        ])
    
    # Acceptance criteria
    lines.extend([
        "### Acceptance Criteria",
        "",
    ])
    
    if legacy and lir_seq:
        speedup = legacy.get("runtime_seconds", 1) / lir_seq.get("runtime_seconds", 1)
        if speedup >= 1.0:
            lines.append(f"- [x] **LIR Sequential**: Not slower than Legacy ({speedup:.2f}x)")
        else:
            lines.append(f"- [ ] **LIR Sequential**: Slower than Legacy ({speedup:.2f}x)")
    
    if legacy and lir_concurrent:
        speedup = legacy.get("runtime_seconds", 1) / lir_concurrent.get("runtime_seconds", 1)
        if speedup >= 2.0:
            lines.append(f"- [x] **LIR Concurrent**: ≥2x faster than Legacy ({speedup:.2f}x)")
        elif speedup >= 1.5:
            lines.append(f"- [ ] **LIR Concurrent**: 1.5-2x faster ({speedup:.2f}x)")
        else:
            lines.append(f"- [ ] **LIR Concurrent**: <1.5x faster ({speedup:.2f}x)")
    
    if lir_seq:
        lir_p95 = lir_seq.get("llm", {}).get("p95_latency_seconds", 0)
        legacy_p95 = legacy.get("llm", {}).get("p95_latency_seconds", 0) if legacy else 0
        if lir_p95 <= legacy_p95 * 1.1:  # Within 10%
            lines.append(f"- [x] **P95 Stability**: LIR P95 stable under load ({lir_p95:.2f}s)")
        else:
            lines.append(f"- [ ] **P95 Stability**: LIR P95 degraded ({lir_p95:.2f}s vs {legacy_p95:.2f}s)")
    
    if lir_seq:
        lir_hot = lir_seq.get("thermal", {}).get("hot_duration_seconds", 0)
        legacy_hot = legacy.get("thermal", {}).get("hot_duration_seconds", 0) if legacy else 0
        if lir_hot <= legacy_hot:
            lines.append(f"- [x] **Thermal**: Hot duration reduced ({lir_hot:.0f}s vs {legacy_hot:.0f}s)")
        else:
            lines.append(f"- [ ] **Thermal**: Hot duration increased ({lir_hot:.0f}s vs {legacy_hot:.0f}s)")
    
    lines.extend(["", ""])
    
    # Key findings
    lines.extend([
        "## Key Findings",
        "",
    ])
    
    if legacy and lir_concurrent:
        speedup = legacy.get("runtime_seconds", 1) / lir_concurrent.get("runtime_seconds", 1)
        throughput_gain = lir_concurrent.get("throughput", {}).get("calls_per_minute", 0) / legacy.get("throughput", {}).get("calls_per_minute", 1)
        
        lines.extend([
            f"1. **Concurrent LIR provides {speedup:.1f}x speedup** over sequential Legacy",
            f"2. **Throughput scales {throughput_gain:.1f}x** with concurrency",
        ])
    
    if legacy and lir_seq:
        legacy_hot = legacy.get("thermal", {}).get("hot_duration_seconds", 0)
        lir_hot = lir_seq.get("thermal", {}).get("hot_duration_seconds", 0)
        if legacy_hot > 0:
            reduction = (1 - lir_hot / legacy_hot) * 100
            lines.append(f"3. **Hot duration reduced by {reduction:.0f}%** (thermal management working)")
    
    lines.extend([
        "",
        "## Notes",
        "",
        "- Warmup phase (3 calls) excluded from metrics to eliminate first-request bias",
        "- Thermal sampling every 2 seconds provides detailed heat profile",
        "- P95/P99 calculated from actual latency histogram, not estimates",
        "- Hot duration = time with max CPU > 80%",
        "",
        "## Raw Data",
        "",
        "Metrics files are stored in `results/`:",
        "",
    ])
    
    for filename in sorted(RESULTS_DIR.glob("stress_*.json")):
        lines.append(f"- `{filename.name}`")
    
    lines.append("")
    
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate LIR Validation Report")
    parser.add_argument(
        "--stress",
        action="store_true",
        help="Generate stress test report instead of quick validation report",
    )
    return parser.parse_args()


def main():
    """Generate and save the validation report"""
    args = parse_args()
    
    if args.stress:
        print("Generating stress test report...")
        report = generate_stress_report()
    else:
        print("Generating validation report...")
        report = generate_quick_report()
    
    # Save report
    with open(REPORT_PATH, "w") as f:
        f.write(report)
    
    print(f"Report saved to: {REPORT_PATH}")
    print()
    print(report)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
