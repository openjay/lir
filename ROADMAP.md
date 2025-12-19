# LIR Roadmap

This document outlines planned capabilities for future versions of LIR.

**Important**: This is a **capability roadmap**, not a timeline commitment. Features will be added based on real-world usage, feedback, and maintainer availability.

---

## Version Strategy

LIR follows [Semantic Versioning](https://semver.org/):

- **MAJOR** (1.0.0) - Breaking API changes
- **MINOR** (0.x.0) - New features, backward compatible
- **PATCH** (0.0.x) - Bug fixes, backward compatible

---

## v0.1.0 (Current - Released 2025-12-19)

**Status**: ✅ Released

### Core Functionality

- Request scheduling with configurable concurrency
- Micro-batching for throughput optimization
- Thermal-aware governance
- Ollama and LM Studio provider support
- Three built-in policies (silent, balanced, performance)
- Comprehensive test suite (41 tests)
- Stress test validation (2.85× improvement)

### Validation

- Extracted from production use in codewiki
- Benchmark evidence provided
- Clean boundaries established

---

## v0.2.0 (Future)

**Status**: 🔮 Planned

**Theme**: Enhanced Observability & Reliability

### Potential Features

- **Metrics export** - Expose request latency, throughput, thermal state
- **Structured logging** - Better debugging information
- **Provider health checking** - Detect and avoid unhealthy providers
- **Circuit breakers** - Prevent cascading failures
- **Retry policies** - Configurable retry behavior
- **Request tracing** - Track requests through the system

### Success Criteria

- Users can debug performance issues without reading source code
- Failures are transparent and actionable
- No new dependencies for core functionality (observability is opt-in)

**Timeline**: When needed (not before)

---

## v0.3.0 (Future)

**Status**: 🔮 Planned

**Theme**: Provider Ecosystem Expansion

### Potential Features

- **vLLM provider adapter** - Support for vLLM inference server
- **llama.cpp provider adapter** - Direct llama.cpp integration
- **OpenAI-compatible endpoint adapter** - Generic adapter for any OpenAI-compatible API
- **Custom provider interface** - Allow users to implement their own providers

### Success Criteria

- LIR works with major local inference runtimes
- Provider adapters follow consistent patterns
- Adding a new provider requires < 100 lines of code

**Timeline**: Based on user demand

---

## v1.0.0 (Future)

**Status**: 🎯 Goal

**Theme**: Production Stability

### Requirements for 1.0

- [ ] API is stable (no breaking changes expected)
- [ ] Comprehensive documentation
- [ ] Battle-tested in multiple production environments
- [ ] Performance characteristics well-understood
- [ ] Error handling is robust
- [ ] Test coverage > 90%
- [ ] No known critical bugs

### What 1.0 Does NOT Mean

- ❌ Feature complete (features will continue to be added)
- ❌ Perfect (bugs will still exist)
- ❌ Enterprise support (still maintained by individuals)

**Timeline**: When ready (months, not weeks)

---

## Under Consideration

These features are **under consideration** but not committed:

### Streaming Support

**Status**: Investigating

**Challenge**: Streaming responses complicate batching and scheduling  
**Benefit**: Better UX for long-running requests  
**Decision**: Need real-world use cases to validate approach

### Custom Policy Definitions

**Status**: Possible

**Current**: Three built-in policies  
**Proposed**: Allow users to define custom policies via YAML  
**Decision**: Only if built-in policies prove insufficient

### Distributed Scheduling

**Status**: Out of scope for now

**Proposed**: Schedule requests across multiple machines  
**Challenge**: Adds significant complexity  
**Decision**: Separate project if needed

### Prompt Caching

**Status**: Investigating

**Proposed**: Cache responses for identical prompts  
**Challenge**: Cache invalidation, memory management  
**Concern**: May violate boundary (application logic vs. infrastructure)  
**Decision**: Needs careful design to avoid scope creep

---

## Explicitly NOT Planned

These features will **not** be added to LIR (see [PHILOSOPHY.md](PHILOSOPHY.md)):

- ❌ Model hosting or serving
- ❌ Prompt management or templates
- ❌ Output parsing or validation
- ❌ Agent frameworks or orchestration
- ❌ Vector databases or embeddings
- ❌ RAG (Retrieval-Augmented Generation)
- ❌ Web UI or dashboard
- ❌ Fine-tuning or training

**Rationale**: These features violate LIR's boundaries. They belong in separate projects.

---

## How to Influence the Roadmap

### What We're Looking For

1. **Real-world use cases** - "I tried to use LIR for X and couldn't because Y"
2. **Performance data** - "LIR improved our throughput by X% but we need Y"
3. **Integration challenges** - "LIR doesn't work with Z provider"

### What We're NOT Looking For

1. **Feature requests without use cases** - "It would be cool if LIR did X"
2. **Scope expansion** - "LIR should also handle prompt management"
3. **Timeline pressure** - "When will feature X be ready?"

### How to Contribute

1. **Open an issue** describing your use case
2. **Provide evidence** (benchmarks, examples, error messages)
3. **Discuss approach** before implementing
4. **Submit PR** if you're willing to implement it yourself

**See [CONTRIBUTING.md](CONTRIBUTING.md) for detailed guidelines.**

---

## Maintenance Philosophy

LIR is maintained by individuals, not a company. This means:

- **Quality over speed** - Features are added when they're ready
- **Simplicity over features** - Saying "no" is often the right answer
- **Evidence over intuition** - Changes are backed by data
- **Sustainability over growth** - Maintainer burnout helps no one

**If you need enterprise support or guaranteed timelines, LIR may not be the right choice.**

---

## Version History

- **v0.1.0** (2025-12-19) - Initial public release

---

## Questions?

- **"When will feature X be released?"** - When it's ready and validated
- **"Can you prioritize feature Y?"** - Provide a compelling use case
- **"Will LIR support Z?"** - Check PHILOSOPHY.md for boundaries
- **"How can I help?"** - See CONTRIBUTING.md

---

## Final Note

This roadmap is **intentionally minimal**.

LIR's strength is its focus. Every feature added is a maintenance burden and a complexity tax.

**The best feature is often the one we don't add.**

If you need capabilities beyond this roadmap, consider:

1. **Composing LIR with other tools** - LIR plays well with others
2. **Building a separate package** - Extend LIR without changing it
3. **Forking** - MIT license allows it

**LIR will remain simple, focused, and trustworthy.**

---

**Roadmap version**: 1.0  
**Last updated**: 2025-12-19  
**Maintained by**: LIR maintainers

