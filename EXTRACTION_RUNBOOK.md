# LIR Extraction & Open Source Runbook

This document describes the **exact, reproducible steps** used to extract LIR (Local Inference Runtime) from its original host project (`codewiki`) and prepare it for public open-source release.

**This is a runbook, not a proposal.**

---

## 0. Purpose

Why this document exists:

- Enable clean extraction of LIR as a standalone library
- Ensure no hidden coupling to the original host project
- Provide confidence for open-source users and contributors
- Serve as a reference for future extractions or forks

---

## 1. Pre-conditions

Before starting extraction, the following conditions were verified:

- ✅ LIR functionality is **production-validated** in codewiki
- ✅ Stress tests demonstrate **steady-state performance benefits** (2.85× speedup)
- ✅ LIR does **not modify model behavior or outputs**
- ✅ Host project can run **with and without** LIR
- ✅ 41/41 LIR unit tests passing
- ✅ No API surface exposed beyond Python SDK

**Key validation**: Quick tests (5 calls) show only ~8% improvement because the system never reaches steady-state. Stress testing (50+ calls) reveals true scaling behavior with 2.85× throughput improvement.

---

## 2. Extraction Strategy

### Design Principle

> LIR is **not** a service.  
> LIR is **not** a framework.  
> LIR is a **drop-in runtime optimization layer**.

Therefore:

- No HTTP server
- No persistent daemon
- No config-heavy system
- No model lifecycle ownership

### What This Means

LIR sits **between** your business logic and the local LLM provider (Ollama / LM Studio). It optimizes the runtime behavior without changing:

- Model outputs
- Prompt semantics
- Business logic
- API contracts

---

## 3. Repository Creation

Created a new repository at `/Users/jay/code/lir/` with the following structure:

```
/lir
├── lir/                # Core package
│   ├── __init__.py
│   ├── client.py       # LIRClient, SyncLIRClient
│   ├── scheduler.py    # Request scheduling
│   ├── batching.py     # Micro-batching
│   ├── governor.py     # Thermal management
│   ├── policies.yaml   # Policy configurations
│   └── providers/      # Provider adapters
│       ├── __init__.py
│       ├── base.py
│       ├── ollama.py
│       ├── lmstudio.py
│       └── router.py
├── tests/              # 41 unit tests
├── benchmarks/         # Stress validation scripts
├── README.md
├── LICENSE             # MIT
└── pyproject.toml
```

**Key rules enforced**:

- ❌ No `sys.path` hacks
- ❌ No imports from host project
- ❌ No hidden side effects on import
- ✅ Clean package installable via `pip install -e .`

---

## 4. Dependency Boundaries

### LIR Owns

- Request scheduling and concurrency control
- Micro-batching for throughput optimization
- Thermal-aware governance (CPU temperature monitoring)
- Provider routing and automatic failover
- Connection pooling and reuse

### LIR Does NOT Own

- Model hosting or runtime (uses Ollama / LM Studio)
- Model lifecycle management
- Prompt engineering or semantics
- Output parsing or post-processing
- Business logic or application state

**Boundary enforcement**: If a feature violates this boundary → **reject it**.

---

## 5. Host Project Decoupling

In the host project (`codewiki`), the integration was changed from embedded to external dependency.

### Before Extraction

```python
# codewiki/llm_client_lir.py
import sys
sys.path.insert(0, str(Path(__file__).parent / "lir"))
from lir import SyncLIRClient
```

### After Extraction

```python
# codewiki/llm_client_lir.py
from lir import SyncLIRClient
```

**Verification steps**:

1. Installed LIR as editable package: `pip install -e /Users/jay/code/lir`
2. Removed `sys.path` hack from codewiki
3. Verified codewiki tests still pass (40/41, 1 pre-existing failure unrelated to LIR)
4. Verified stress test works with external LIR
5. Removed embedded `codewiki/lir/` directory
6. Removed LIR-specific dependencies from codewiki (aiohttp, psutil now owned by LIR)

**Rules**:

- Host treats LIR like any third-party dependency
- LIR can be disabled via environment flag (if needed)
- Host remains functional without LIR

---

## 6. Verification Checklist

After extraction, the following were verified:

- [x] `pip install -e /Users/jay/code/lir` works
- [x] `pytest` passes in LIR repo (41/41 tests)
- [x] Host project imports LIR cleanly (no sys.path hacks)
- [x] Stress test works via external LIR (2.85× improvement maintained)
- [x] No duplicated code remains in host project
- [x] Async shutdown is clean (no warnings about unclosed sessions)
- [x] README includes benchmark evidence
- [x] MIT LICENSE is present

---

## 7. Open Source Release Steps

The following steps were taken to prepare for public release:

1. ✅ Initialized git repository at `/Users/jay/code/lir/`
2. ✅ Created `pyproject.toml` with proper metadata and dependencies
3. ✅ Created comprehensive `README.md` with:
   - Clear problem statement
   - Benchmark results (2.85× speedup)
   - Quick start examples
   - Policy documentation
4. ✅ Added MIT `LICENSE`
5. ✅ Fixed graceful shutdown in `SyncLIRClient.close()` to properly cancel tasks
6. ✅ Tagged `v0.1.0` locally
7. ✅ Committed initial release: `git commit -m "v0.1.0: extract LIR as standalone package"`

**Next steps** (to be done when ready):

- Create GitHub repository under personal account (jay)
- Push code: `git push -u origin main`
- Push tags: `git push --tags`
- Make repository public immediately (no private preview needed)

---

## 8. What This Runbook Intentionally Avoids

This document does NOT cover:

- PyPI publishing (future consideration, not a prerequisite)
- CI/CD pipelines (minimal GitHub Actions is sufficient)
- Contributor governance (add when needed)
- Long-term roadmap (separate document)
- Issue templates (add when issues arrive)
- PR templates (keep it simple initially)

**Rationale**: These are **optional enhancements**, not prerequisites for a successful open-source launch. Add them as needed, not preemptively.

---

## 9. Rollback Plan

If anything goes wrong during the extraction or release:

### Rollback from External LIR

1. Uninstall LIR: `pip uninstall lir`
2. Restore `codewiki/lir/` from git history
3. Restore `sys.path` hack in `codewiki/llm_client_lir.py`
4. Revert dependency changes in `codewiki/pyproject.toml`

**Rollback cost**: < 5 minutes

### Rollback from Public Release

If the public release causes issues:

1. Archive the GitHub repository (don't delete - preserves links)
2. Create a new private fork if needed
3. Address issues before re-releasing

**Note**: Given LIR's stability and test coverage, rollback is unlikely to be needed.

---

## 10. Success Metrics

The extraction is considered successful based on:

| Metric | Target | Actual |
|--------|--------|--------|
| LIR tests passing | 100% | ✅ 41/41 (100%) |
| Host project tests | No regression | ✅ 40/41 (1 pre-existing failure) |
| Stress test speedup | ≥2× | ✅ 2.85× |
| Import cleanliness | No sys.path hacks | ✅ Clean import |
| Async shutdown | No warnings | ✅ Clean shutdown |
| Documentation | Complete README | ✅ With benchmarks |

---

## 11. Key Technical Decisions

### Why Editable Install?

Using `pip install -e .` during development allows:

- Real-time code changes without reinstalling
- Easy debugging across LIR and host project
- Smooth transition to published package later

### Why MIT License?

- Maximum permissiveness for infrastructure libraries
- No copyleft requirements
- Compatible with commercial use
- Standard choice for Python tooling

### Why Personal GitHub Account?

- No overhead of organization management
- Faster iteration and decision-making
- Can migrate to org later if needed
- More authentic for individual maintainer

### Why Public Immediately?

- LIR is production-ready, not experimental
- Has clear boundaries and test coverage
- Benchmark evidence provides credibility
- "Private preview" adds unnecessary friction

---

## 12. Lessons Learned

### What Worked Well

1. **Stress testing first** - Validated performance claims before extraction
2. **Clean boundaries** - LIR never owned model lifecycle, making extraction clean
3. **Comprehensive tests** - 41 tests gave confidence during extraction
4. **Async context managers** - Made cleanup and shutdown straightforward

### What Could Be Improved

1. **Earlier extraction** - Could have been done sooner once boundaries were clear
2. **Documentation** - README could have been written during development

### Advice for Future Extractions

- Validate boundaries early (what does the module own vs. not own?)
- Write stress tests to prove value before extraction
- Keep imports clean from day one (no sys.path hacks)
- Document design principles before extracting

---

## 13. Final Note

LIR exists because:

> Local inference performance problems repeat across projects,  
> and should be solved **once**, not N times.

The extraction was successful because LIR was designed from the start as **infrastructure, not a feature**. It never tried to own model behavior, prompt semantics, or business logic.

**If LIR stops being simple, it has failed.**

---

**End of runbook.**

**Document version**: 1.0  
**Last updated**: 2025-12-19  
**Status**: Extraction complete, ready for public release

