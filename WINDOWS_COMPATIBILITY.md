# Windows Onboarding & Multi-LLM Compatibility Audit

**Author**: Harsh Alreja  
**Status**: Resolved (Local Fixes) / Ready for Upstream PR  
**Date**: Feb 2026  
**Related**: [Hive #261](https://github.com/adenhq/hive/issues/261) - Lack of Native Windows Support



## My Approach
I set out to implement the `marketing_agent` template on my local Windows machine using a Groq Cloud API key. Along the way, I hit several "silent" blockers that weren't covered in the current docs. I’ve documented these to help other Windows devs get up and running without the same friction I faced.



1. **Hardcoded AnthropicProvider** in `agent.py` 
2. **Static model config** ignoring `.env` vars
3. **Missing TUI `__main__.py`** entrypoint
4. **PYTHONPATH colon delimiters** (Linux-only)
5. **HuggingFace tokenizer symlink warnings**



## 🔍 What I Found

### 1. Architecture Issues

| Issue | Location | Impact | Status |
|-------|----------|--------|---------|
| `agent.py` hardcoded to `AnthropicProvider()` | `exports/marketing_agent/agent.py` | Fails immediately for Groq/OpenAI/local models | ✅ Fixed locally |
| `config.py` static model string `"claude-haiku-4-5-20251001"` | `exports/marketing_agent/config.py` | Requires code edits to switch LLMs | ✅ Fixed locally |

**Root Cause**: Templates bypass `LiteLLMProvider` factory despite framework docs promising provider-agnostic execution via `GROQ_API_KEY`.

### 2. Windows-Specific Blockers

| Issue | Symptom | Windows Impact | Workaround |
|-------|---------|----------------|------------|
| No `framework.tui/__main__.py` | `python -m framework.tui` → "can't execute package" | Silent TUI failure in Git Bash/PowerShell | Direct `__init__.py` execution |
| Docs use `:` for PYTHONPATH | `core:exports` fails path resolution | Can't load both `core/` and `exports/` | Use `;` delimiters: `core;exports` |
| HF tokenizers need symlinks | `UserWarning: Symlinks disabled` | Degraded perf, disk bloat | Enable Developer Mode |

## 🛠️ Local Fixes Applied

### Provider Fix (Your Actual Code)
```python
# Before (broken)
from framework.llm.anthropic import AnthropicProvider
llm = AnthropicProvider(model=self.config.model)

# After (works - Provider Agnostic)
from framework.llm.litellm import LiteLLMProvider
llm = LiteLLMProvider(model=self.config.model)  # Dynamically handles Groq via .env

Dynamic Config
python
# Before
model = "claude-haiku-4-5-20251001"

# After  
model = os.getenv("LITELLM_MODEL", "llama3.1:8b")  # Groq default
Windows PYTHONPATH
bash
# Docs (Linux)
export PYTHONPATH="core:exports"

# Windows (fixed)
set PYTHONPATH=core;exports
# or in Git Bash
export PYTHONPATH="core;exports"
🚀 Recommended Upstream PR
Title: fix: Windows compatibility + provider-agnostic marketing_agent #261

Scope:

text
exports/marketing_agent/
├─ agent.py          (LiteLLMProvider import + usage)
├─config.py         (dynamic model from .env)
└─ README.md         (Windows setup instructions)
core/framework/tui/
└─__main__.py       (TUI entrypoint)
docs/
└─ windows-setup.md  (PYTHONPATH, symlinks)
Testing Matrix:

 Windows 11 + Git Bash + Groq ✅

 Windows 11 + PowerShell + Groq ✅

 Linux validation

 MacOS validation



Harsh Alreja
BCA | Product Engineering Enthusiast | India
https://www.linkedin.com/in/harsh-alrejaa/ | https://github.com/HarshAlreja