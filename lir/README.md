# Local Inference Runtime (LIR)

A lightweight, OpenAI API-compatible local LLM inference optimization framework.

## Overview

LIR solves structural problems with local LLM inference:
- **Sequential blocking calls** → Async batching and concurrency
- **Thermal management** → Adaptive throttling based on CPU state
- **Single provider** → Multi-provider with automatic failover

## Features

- **Micro-batching**: Aggregate requests for efficient processing
- **Token-aware concurrency**: Limit concurrent requests by token budget
- **Thermal governor**: Adaptive throttling based on CPU temperature/frequency
- **Multi-provider**: Ollama + LM Studio with automatic failover
- **Three policies**: Silent, Balanced, Performance

## Quick Start

### Async Usage (Recommended)

```python
from lir import LIRClient

async with LIRClient(policy="balanced") as client:
    result = await client.generate(
        prompt="Analyze this code...",
        system_prompt="You are a code reviewer."
    )
    print(result)
```

### Sync Usage (For Existing Code)

```python
from lir import SyncLIRClient

client = SyncLIRClient(policy="balanced")
result = client.generate("Hello, world!")
client.close()
```

### With CodeWiki

LIR is automatically used by the lifecycle classifier:

```bash
# Install dependencies
pip install -e .

# Run with LIR (automatic)
python -m codewiki.orchestrator --mode lifecycle
```

## Policies

| Policy | Concurrency | Batch Window | Use Case |
|--------|-------------|--------------|----------|
| `silent` | 1 | 100ms | Quiet environment, battery mode |
| `balanced` | 3 | 40ms | Daily development (default) |
| `performance` | 6 | 20ms | CI/CD, batch processing |

```python
# Change policy at runtime
client.set_policy("silent")
```

## Architecture

```
Business Code → LIRClient → Scheduler → Batching → Governor → Router → Providers → LLM
                    │           │           │           │          │
                    │           │           │           │          ├── Ollama
                    │           │           │           │          └── LM Studio
                    │           │           │           │
                    │           │           │           └── Thermal-aware routing
                    │           │           │
                    │           │           └── CPU monitoring (psutil)
                    │           │
                    │           └── Request aggregation (20-100ms window)
                    │
                    └── Token-aware concurrency control
```

## Components

### Scheduler (`scheduler.py`)
- Request queue with FIFO ordering
- Token-aware concurrency control
- Backpressure handling

### Batching (`batching.py`)
- Configurable batching window
- Automatic batch formation
- Result distribution

### Governor (`governor.py`)
- CPU monitoring via psutil
- Adaptive concurrency adjustment
- Automatic cooldown insertion

### Providers (`providers/`)
- Ollama adapter
- LM Studio adapter (OpenAI-compatible)
- Automatic failover router

## Configuration

### policies.yaml

```yaml
policies:
  balanced:
    max_concurrent_requests: 3
    max_tokens_inflight: 8192
    batch_window_ms: 40
    max_batch_size: 10
    thermal_policy: normal
```

### Provider URLs

```python
client = LIRClient(
    policy="balanced",
    ollama_url="http://localhost:11434",
    lmstudio_url="http://localhost:1234",
    ollama_model="qwen3:8b",
    lmstudio_model="local-model",
)
```

## Thermal Management

LIR monitors CPU state and automatically adjusts:

| State | CPU Max | Action |
|-------|---------|--------|
| COOL | <50% | Normal operation |
| WARM | 50-70% | Monitor closely |
| HOT | 70-85% | Reduce concurrency, add cooldown |
| CRITICAL | >85% | Pause processing |

## Metrics

```python
metrics = client.get_metrics()
print(metrics["client"]["total_requests"])
print(metrics["governor"]["current_state"])
print(metrics["router"]["active_provider"])
```

## Requirements

- Python 3.10+
- aiohttp >= 3.9.0
- psutil >= 5.9.0
- pyyaml >= 6.0

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest tests/lir/

# Run benchmarks
python -m lir.benchmarks.benchmark
```

## License

MIT License - see LICENSE file.

