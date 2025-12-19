# LIR Open Source Launch Checklist

This checklist guides you through making LIR public on GitHub.

**Status**: Ready for launch ✅

---

## Pre-Launch Verification

- [x] All tests pass (41/41)
- [x] Package builds successfully (`python3 -m build`)
- [x] Documentation complete:
  - [x] `README.md` with benchmark evidence
  - [x] `EXTRACTION_RUNBOOK.md` documenting the extraction
  - [x] `PHILOSOPHY.md` defining boundaries
  - [x] `CHANGELOG.md` with v0.1.0 entry
  - [x] `CONTRIBUTING.md` for contributors
  - [x] `ROADMAP.md` for future direction
  - [x] `LICENSE` (MIT)
- [x] `.gitignore` configured
- [x] GitHub Actions workflow ready (`.github/workflows/test.yml`)
- [x] `pyproject.toml` metadata complete
- [x] Git tag `v0.1.0` created locally

---

## Launch Steps

### 1. Create GitHub Repository

Go to https://github.com/new and create:

- **Repository name**: `lir`
- **Description**: "Local Inference Runtime - OpenAI-compatible optimization layer for local LLMs"
- **Visibility**: **Public** (immediate open source)
- **Initialize**: Do NOT initialize with README (we already have one)

### 2. Push Code to GitHub

```bash
cd /Users/jay/code/lir

# Add remote (replace 'jay' with your actual GitHub username if different)
git remote add origin git@github.com:jay/lir.git

# Push main branch
git push -u origin main

# Push tags
git push --tags
```

### 3. Verify GitHub Actions

After pushing:

1. Go to https://github.com/jay/lir/actions
2. Verify the test workflow runs automatically
3. Confirm all tests pass on GitHub

**Expected**: Green checkmark on Python 3.10, 3.11, 3.12

### 4. Configure Repository Settings

On GitHub, go to Settings:

#### General
- [x] Enable Issues
- [x] Enable Discussions (optional, but recommended)
- [ ] Disable Wiki (not needed yet)
- [ ] Disable Projects (not needed yet)

#### Topics
Add topics for discoverability:
- `llm`
- `inference`
- `local-llm`
- `ollama`
- `lm-studio`
- `optimization`
- `python`

### 5. Create Initial GitHub Release

Go to https://github.com/jay/lir/releases/new:

- **Tag**: `v0.1.0` (select existing tag)
- **Title**: `v0.1.0 - Initial Public Release`
- **Description**:

```markdown
# LIR v0.1.0 - Initial Public Release

First public release of LIR (Local Inference Runtime), extracted from production use in codewiki.

## What is LIR?

A lightweight, OpenAI-compatible optimization layer for local LLM inference (Ollama / LM Studio).

## Key Features

- Request scheduling and concurrency control
- Micro-batching for throughput optimization
- Thermal-aware governance (reduces fan noise)
- Connection pooling and reuse
- Automatic provider failover

## Performance

Tested on Apple Silicon (M4 Max) with 50 LLM calls:

- **2.85× throughput improvement** (7.3/min → 20.8/min)
- **8.9× better P50 latency** (8.52s → 0.96s)
- Sustained performance under load

## Installation

```bash
pip install git+https://github.com/jay/lir.git
```

## Quick Start

```python
from lir import SyncLIRClient

with SyncLIRClient(policy="balanced") as client:
    result = client.generate("Explain quantum computing")
    print(result)
```

See [README.md](README.md) for full documentation.

## What's Next

See [ROADMAP.md](ROADMAP.md) for planned features.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.
```

- **Attach files**: Upload `dist/lir-0.1.0.tar.gz` and `dist/lir-0.1.0-py3-none-any.whl`

### 6. Post-Launch Verification

After making the repository public:

- [ ] Repository is accessible at https://github.com/jay/lir
- [ ] GitHub Actions badge shows passing tests
- [ ] README renders correctly
- [ ] Installation works: `pip install git+https://github.com/jay/lir.git`
- [ ] Import works: `python3 -c "from lir import SyncLIRClient; print('Success')"`

---

## Optional Post-Launch Steps

### Add Badges to README

Add to the top of `README.md`:

```markdown
[![Tests](https://github.com/jay/lir/actions/workflows/test.yml/badge.svg)](https://github.com/jay/lir/actions/workflows/test.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
```

### Announce (When Ready)

Consider announcing on:

- [ ] Your personal blog/website
- [ ] Twitter/X
- [ ] Hacker News (Show HN)
- [ ] Reddit (r/LocalLLaMA, r/Python)
- [ ] Dev.to

**Important**: Only announce when you're comfortable with potential attention. No rush.

### PyPI Publishing (Future)

When ready to publish to PyPI:

1. Create account on https://pypi.org
2. Generate API token
3. Add token to GitHub Secrets as `PYPI_API_TOKEN`
4. Create `.github/workflows/publish.yml` (see ROADMAP.md)
5. Push a new tag to trigger publishing

**Not required now** - GitHub installation works fine for early users.

---

## Rollback Plan

If something goes wrong:

### Option 1: Archive Repository
1. Go to Settings → General → Danger Zone
2. Click "Archive this repository"
3. Repository becomes read-only but stays accessible

### Option 2: Make Private
1. Go to Settings → General → Danger Zone
2. Click "Change visibility" → "Make private"
3. Fix issues privately
4. Make public again when ready

### Option 3: Delete (Last Resort)
1. Go to Settings → General → Danger Zone
2. Click "Delete this repository"
3. **Warning**: This is permanent after 90 days

**Recommended**: Option 1 (Archive) if you need to pause.

---

## Success Metrics

After 1 week:

- [ ] No critical bugs reported
- [ ] GitHub Actions still passing
- [ ] At least 1 star (even if it's just you)
- [ ] Installation instructions work for others

After 1 month:

- [ ] Some community engagement (stars, issues, or discussions)
- [ ] No major design regrets
- [ ] Still simple and focused

---

## What NOT to Do

❌ **Don't** announce before you're comfortable with attention  
❌ **Don't** promise features or timelines  
❌ **Don't** feel pressured to respond immediately to issues  
❌ **Don't** accept PRs that violate PHILOSOPHY.md  
❌ **Don't** let scope creep in

✅ **Do** stay focused on LIR's core mission  
✅ **Do** be transparent about maintenance capacity  
✅ **Do** protect the boundaries defined in PHILOSOPHY.md  
✅ **Do** say "no" when appropriate

---

## Final Note

**You're ready to launch.**

LIR is:
- Production-validated ✅
- Well-tested ✅
- Clearly documented ✅
- Properly licensed ✅
- Simple and focused ✅

The extraction was successful. The documentation is complete. The boundaries are clear.

**Just push to GitHub and make it public.**

Good luck! 🚀

---

**Checklist version**: 1.0  
**Last updated**: 2025-12-19  
**Next review**: After launch

