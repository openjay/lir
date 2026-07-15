# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2025-12-19

### Added

- Initial extraction from codewiki as standalone package
- Core scheduling engine with configurable concurrency control
- Micro-batching for throughput optimization (configurable time windows)
- Thermal-aware governor with CPU temperature monitoring
- Ollama provider adapter with connection pooling
- LM Studio provider adapter with connection pooling
- Provider router with automatic failover
- Three built-in policies: `silent`, `balanced`, `performance`
- Async client (`LIRClient`) with context manager support
- Sync client (`SyncLIRClient`) with proper event loop management
- Comprehensive test suite (41 unit tests, 100% pass rate)
- Stress validation benchmarks demonstrating 2.85× throughput improvement
- Complete README with benchmark evidence and usage examples
- MIT License

### Design Decisions

- **OpenAI-compatible interface** - Familiar API for easy adoption
- **No model hosting** - LIR is a client-side optimization layer, not a serving platform
- **No persistent daemon** - Pure Python library, no background processes
- **Drop-in optimization** - Can be removed by changing one import line
- **Thermal awareness** - First-class concern for laptop-based development
- **Evidence-based claims** - All performance claims backed by reproducible stress tests

### Performance Characteristics

Tested on Apple Silicon (M4 Max) with 50 LLM calls per scenario:

| Scenario | Runtime | Throughput | P50 Latency | Speedup |
|----------|---------|------------|-------------|---------|
| Legacy (sequential) | 412s | 7.3/min | 8.52s | baseline |
| LIR Sequential | 144s | 20.8/min | 0.96s | **2.85×** |
| LIR Concurrent (c=4) | 167s | 18.0/min | 0.80s | **2.46×** |

**Key findings**:
- 2.85× throughput improvement in sequential mode
- 8.9× better P50 latency (0.96s vs 8.52s)
- Thermal management prevents throttling under sustained load

### Known Limitations

- Quick tests (5 calls) show minimal improvement (~8%) because the system never reaches steady-state
- Stress testing (50+ calls) required to see true scaling behavior
- Currently supports Ollama and LM Studio only (more providers planned)
- Thermal monitoring tested primarily on macOS (Linux support exists but less validated)

### Dependencies

- Python ≥ 3.10
- aiohttp ≥ 3.9.0 (HTTP client with connection pooling)
- psutil ≥ 5.9.0 (CPU temperature monitoring)
- pyyaml ≥ 6.0 (policy configuration)

### Breaking Changes

N/A - Initial release

---

## [Unreleased]

### Changed

- Minimum supported Python raised from 3.10 to **3.11** (`requires-python = ">=3.11"`) as part of the 2026-07-15 server-wide version alignment; removed the 3.10 trove classifier and updated the README requirement line
- `.python-version` (pinned to 3.11) is now tracked — removed the ignore rule from `.gitignore`

### Planned for v0.2.0

- Enhanced observability (metrics export, tracing)
- Additional provider support (vLLM, llama.cpp)
- Improved thermal models for different hardware platforms
- Better error messages and debugging tools

### Under Consideration

- Streaming response support
- Custom policy definitions via YAML
- Provider health checking and circuit breakers
- Prometheus metrics exporter

**Note**: This is a capability roadmap, not a timeline commitment. Features will be added based on real-world usage and feedback.

---

## Version History

- **v0.1.0** (2025-12-19) - Initial public release

---

## Upgrade Guide

### From Embedded LIR (codewiki) to Standalone Package

If you were using LIR embedded in another project:

1. Install standalone LIR:
   ```bash
   pip install lir
   # or for development:
   pip install -e /path/to/lir
   ```

2. Remove sys.path hacks:
   ```python
   # Remove this:
   import sys
   sys.path.insert(0, "path/to/lir")
   
   # Use this:
   from lir import SyncLIRClient
   ```

3. Update dependencies:
   - Remove `aiohttp`, `psutil`, `pyyaml` from your project (now owned by LIR)
   - Add `lir` as a dependency

4. Verify tests still pass

**API compatibility**: 100% - No breaking changes from embedded version

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines on proposing changes.

**Important**: Changes to core behavior or boundaries require discussion. See [PHILOSOPHY.md](PHILOSOPHY.md) for LIR's design principles.

---

**Changelog maintained by**: LIR maintainers  
**Format**: [Keep a Changelog](https://keepachangelog.com/)  
**Versioning**: [Semantic Versioning](https://semver.org/)

