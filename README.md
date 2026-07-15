# LIR - Local Inference Runtime

A lightweight, OpenAI-compatible optimization layer for local LLM inference (Ollama / LM Studio).

## Why LIR?

Local LLM inference is powerful but often underutilized:

- **Single-thread blocking kills throughput** - Sequential requests waste potential
- **Thermal throttling kills sustained performance** - Fans spin up, CPU throttles down
- **Connection overhead adds up** - New connections for every request

LIR solves these by providing intelligent scheduling, batching, and thermal management.

## What LIR Does (and Does NOT)

**LIR Does:**
- Request scheduling and concurrency control
- Micro-batching for throughput optimization
- Thermal-aware governance (reduces fan noise)
- Connection pooling and reuse
- Automatic provider failover

**LIR Does NOT:**
- Host or run models (uses Ollama / LM Studio)
- Replace your existing LLM runtime
- Require a separate server process
- Add cloud dependencies

## Benchmark Results

Tested on Apple Silicon (M4 Max) with 50 LLM calls per scenario:

| Scenario | Runtime | Throughput | P50 Latency | Speedup |
|----------|---------|------------|-------------|---------|
| Legacy (sequential) | 412s | 7.3/min | 8.52s | baseline |
| LIR Sequential | 144s | 20.8/min | 0.96s | **2.85x** |
| LIR Concurrent (c=4) | 167s | 18.0/min | 0.80s | **2.46x** |

**Key findings:**
- **2.85x throughput improvement** in sequential mode
- **8.9x better P50 latency** (0.96s vs 8.52s)
- **Hot duration reduced** (thermal management working)

> **Note:** Quick tests (5 calls) show only ~8% improvement because the system never reaches steady-state. Stress testing reveals true scaling behavior.

## Installation

```bash
# From source
pip install -e .

# Or with dev dependencies
pip install -e ".[dev]"
```

## Quick Start

### Async Usage (Recommended)

```python
from lir import LIRClient

async def main():
    async with LIRClient(policy="balanced") as client:
        result = await client.generate(
            prompt="Explain quantum computing in simple terms",
            system_prompt="You are a helpful assistant",
        )
        print(result)

import asyncio
asyncio.run(main())
```

### Sync Usage (For Existing Code)

```python
from lir import SyncLIRClient

# Context manager ensures cleanup
with SyncLIRClient(policy="balanced") as client:
    result = client.generate("Hello, world!")
    print(result)
```

### Batch Processing

```python
async with LIRClient(policy="performance") as client:
    results = await client.generate_batch(
        prompts=["Question 1", "Question 2", "Question 3"],
        system_prompts=["You are helpful"] * 3,
    )
```

## Policies

LIR supports three built-in policies:

| Policy | Concurrency | Batching | Use Case |
|--------|-------------|----------|----------|
| `silent` | 1 | 100ms window | Minimize fan noise |
| `balanced` | 3 | 40ms window | General use (default) |
| `performance` | 6 | 20ms window | Maximum throughput |

```python
# Use silent policy for quiet operation
client = LIRClient(policy="silent")

# Switch policy at runtime
client.set_policy("performance")
```

## Configuration

### Provider URLs

```python
client = LIRClient(
    policy="balanced",
    ollama_url="http://localhost:11434",
    lmstudio_url="http://localhost:1234",
    ollama_model="qwen3:8b",
    lmstudio_model="llama-3.2-3b-instruct",
)
```

### Custom Providers

```python
from lir import LIRClient, OllamaProvider, LMStudioProvider

providers = [
    OllamaProvider(base_url="http://server1:11434", priority=1),
    LMStudioProvider(base_url="http://server2:1234", priority=2),
]

client = LIRClient(providers=providers)
```

## Architecture

```
Business Code
     │
     ▼
┌─────────────┐
│  LIRClient  │  ← OpenAI-compatible interface
└─────────────┘
     │
     ▼
┌─────────────┐
│  Scheduler  │  ← Concurrency control, token budget
└─────────────┘
     │
     ▼
┌─────────────┐
│  Batching   │  ← Micro-batching for throughput
└─────────────┘
     │
     ▼
┌─────────────┐
│  Governor   │  ← Thermal-aware throttling
└─────────────┘
     │
     ▼
┌─────────────┐
│   Router    │  ← Provider selection & failover
└─────────────┘
     │
     ▼
┌─────────────┐
│  Providers  │  ← Ollama, LM Studio adapters
└─────────────┘
     │
     ▼
  Local LLM
```

## Requirements

- Python 3.11+
- aiohttp >= 3.9.0
- psutil >= 5.9.0
- PyYAML >= 6.0

## Running Tests

```bash
# Unit tests
pytest tests/

# With coverage
pytest tests/ --cov=lir

# Stress test (requires running LLM provider)
python benchmarks/stress_validation.py --scenario=lir --calls=50
```

## Comparison: LIR vs Direct Calls

| Feature | Direct Calls | LIR |
|---------|--------------|-----|
| Connection pooling | ❌ New each time | ✅ Reused |
| Batching | ❌ Manual | ✅ Automatic |
| Thermal management | ❌ None | ✅ Built-in |
| Failover | ❌ Manual | ✅ Automatic |
| Metrics | ❌ None | ✅ Comprehensive |

## License

MIT

## Contributing

Contributions welcome! Please ensure:
- Tests pass (`pytest`)
- Code is formatted (`black`, `ruff`)
- No new warnings in stress tests

