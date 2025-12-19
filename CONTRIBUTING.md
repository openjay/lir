# Contributing to LIR

Thank you for considering contributing to LIR! This document provides guidelines for contributing.

## Before You Start

**Read [PHILOSOPHY.md](PHILOSOPHY.md) first.** It defines LIR's boundaries and design principles. Most rejected contributions violate these boundaries.

**Key principle**: LIR is infrastructure, not a framework. If your contribution adds application logic, prompt management, or model hosting features, it likely belongs in a separate project.

---

## Quick Start

### Development Setup

1. Clone the repository:
   ```bash
   git clone https://github.com/jay/lir.git
   cd lir
   ```

2. Install in editable mode with dev dependencies:
   ```bash
   pip install -e ".[dev]"
   ```

3. Verify installation:
   ```bash
   pytest
   ```

**Expected result**: All tests pass (currently 41 tests).

---

## Running Tests

### Unit Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=lir

# Run specific test file
pytest tests/test_scheduler.py

# Run with verbose output
pytest -v
```

### Stress Tests

Stress tests require a running LLM provider (Ollama or LM Studio):

```bash
# Ensure Ollama is running
ollama serve

# Run stress test
python benchmarks/stress_validation.py --scenario=lir --calls=50
```

**Note**: Stress tests take several minutes and are required for performance-related changes.

---

## Code Style

LIR uses standard Python formatting tools:

- **black** - Code formatting
- **ruff** - Linting

```bash
# Format code
black lir/ tests/

# Lint code
ruff check lir/ tests/
```

**Policy**: We prefer consistency, but won't block PRs on formatting. If your PR has style issues, maintainers will fix them during merge.

---

## Making Changes

### 1. Create an Issue First (for non-trivial changes)

Before starting work on a significant change:

1. Open an issue describing the problem or feature
2. Wait for feedback from maintainers
3. Discuss approach and design

**Why**: Avoids wasted effort on changes that won't be merged.

**Exception**: Bug fixes, typos, documentation improvements don't need issues.

### 2. Branch Naming

Use descriptive branch names:

- `fix/issue-description` - Bug fixes
- `feat/feature-description` - New features
- `docs/what-changed` - Documentation updates

### 3. Commit Messages

Write clear commit messages:

```
Short summary (50 chars or less)

Longer explanation if needed. Explain why the change
was made, not just what changed.

Fixes #123
```

### 4. Testing Requirements

**All PRs must**:

- Include tests for new functionality
- Maintain or improve test coverage
- Pass all existing tests
- Not introduce new warnings

**Performance-related changes must**:

- Include stress test results
- Show improvement in benchmark metrics
- Not degrade other scenarios

---

## Pull Request Process

1. **Fork the repository** (or create a branch if you have write access)

2. **Make your changes** following the guidelines above

3. **Run tests locally**:
   ```bash
   pytest
   ```

4. **Submit PR** with:
   - Clear description of what changed and why
   - Reference to related issue (if any)
   - Test results (especially for performance changes)

5. **Respond to feedback** - Maintainers may request changes

6. **Merge** - Once approved, maintainers will merge your PR

---

## What Makes a Good Contribution

### Good Contributions

✅ **Bug fixes** - Clear problem, clear solution, includes test  
✅ **Performance improvements** - Backed by benchmark evidence  
✅ **New provider adapters** - Follows existing pattern (see `providers/ollama.py`)  
✅ **Documentation improvements** - Clearer explanations, better examples  
✅ **Test coverage** - More comprehensive tests  
✅ **Error messages** - Better debugging information

### Contributions That Need Discussion

⚠️ **New dependencies** - Must justify the added complexity  
⚠️ **API changes** - Backward compatibility is important  
⚠️ **New policies** - Must be backed by real-world use cases  
⚠️ **Architectural changes** - Require strong rationale

### Contributions That Will Be Rejected

❌ **Prompt management features** - Violates LIR's boundaries  
❌ **Model hosting** - Use Ollama/LM Studio for this  
❌ **Output parsing** - Application logic, not infrastructure  
❌ **Agent frameworks** - Separate concern  
❌ **Web UI** - Separate project  
❌ **Feature creep** - Anything that makes LIR harder to explain

**See [PHILOSOPHY.md](PHILOSOPHY.md) for detailed boundary definitions.**

---

## Questions to Ask Before Contributing

1. **Does this change model behavior?** → If yes, it doesn't belong in LIR
2. **Does this add application logic?** → If yes, it doesn't belong in LIR
3. **Does this require new dependencies?** → Justify carefully
4. **Does this make LIR harder to explain?** → If yes, reconsider
5. **Could this be a separate package?** → If yes, make it separate

**If unsure, open an issue to discuss before starting work.**

---

## Provider Adapter Guidelines

If you're adding support for a new LLM provider:

1. **Follow the existing pattern** - See `providers/ollama.py` as reference
2. **Inherit from `BaseProvider`** - Implements required interface
3. **Support connection pooling** - Reuse HTTP sessions
4. **Handle errors gracefully** - Provider failures shouldn't crash LIR
5. **Include tests** - Mock the provider's API
6. **Document configuration** - Update README with usage examples

**Example structure**:

```python
from .base import BaseProvider

class NewProvider(BaseProvider):
    def __init__(self, base_url: str, model: str, priority: int = 1):
        super().__init__(priority)
        # Initialize provider
    
    async def generate(self, prompt: str, system_prompt: str = "") -> str:
        # Implement generation
    
    async def close(self):
        # Cleanup resources
```

---

## Documentation Guidelines

When updating documentation:

- **Be concise** - Developers are busy
- **Show examples** - Code speaks louder than words
- **Explain why** - Not just what or how
- **Link to related docs** - Help readers navigate
- **Test examples** - Ensure code samples actually work

---

## Release Process

(For maintainers)

1. Update version in `pyproject.toml`
2. Update `CHANGELOG.md` with changes
3. Create git tag: `git tag v0.x.0`
4. Push tag: `git push --tags`
5. GitHub Actions will handle the rest (when configured)

---

## Code of Conduct

**Be respectful and constructive.**

- Assume good intentions
- Focus on the technical merits
- Disagree without being disagreeable
- Help newcomers learn

**Unacceptable behavior**:

- Personal attacks
- Harassment
- Spam or self-promotion
- Anything that violates GitHub's Terms of Service

**Enforcement**: Maintainers may remove comments, close issues, or ban users who violate these guidelines.

---

## Getting Help

- **Questions about usage** - Open a GitHub issue with the "question" label
- **Bug reports** - Open a GitHub issue with the "bug" label
- **Feature requests** - Open a GitHub issue with the "enhancement" label (but read PHILOSOPHY.md first!)
- **Security issues** - Email maintainers directly (don't open public issues)

---

## Maintainer Notes

**Current maintainer**: jay  
**Maintenance model**: Individual maintainer, not a company  
**Response time**: Best effort, typically within a few days  
**Decision-making**: Maintainer has final say on scope and direction

**This is a side project.** Contributions are appreciated, but maintainers have limited time. Please be patient.

---

## License

By contributing to LIR, you agree that your contributions will be licensed under the MIT License.

---

## Final Note

LIR exists to solve **one problem well**: optimizing local LLM inference without changing behavior.

If your contribution helps with that goal while maintaining simplicity, it's likely a good fit.

If it adds complexity, scope, or violates boundaries, it's likely not.

**When in doubt, ask first.**

Thank you for contributing! 🚀

