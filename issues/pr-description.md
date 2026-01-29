## Description

Wrap inline `anthropic.Anthropic()` instantiations in context managers (`with` blocks) to ensure the underlying `httpx.Client` connection pool is closed after each use, preventing socket leaks.

## Type of Change

- [x] Bug fix (non-breaking change that fixes an issue)
- [ ] New feature (non-breaking change that adds functionality)
- [ ] Breaking change (fix or feature that would cause existing functionality to not work as expected)
- [ ] Documentation update
- [ ] Refactoring (no functional changes)

## Related Issues

Fixes #(issue number)

## Changes Made

- Wrapped `anthropic.Anthropic()` in a `with` block in `core/framework/graph/node.py:535` (summary generation)
- Wrapped `anthropic.Anthropic()` in a `with` block in `core/framework/graph/node.py:1345` (Haiku output formatting)
- Wrapped `anthropic.Anthropic()` in a `with` block in `core/framework/graph/hitl.py:198` (HITL response parsing)

## Testing

These calls are utility helpers that fire during node execution logging, output formatting, and HITL interaction. They are wrapped in try/except with fallbacks, so the change is low-risk.

- [ ] Unit tests pass (`cd core && pytest tests/`)
- [ ] Lint passes (`cd core && ruff check .`)
- [x] Manual testing performed
  - Verified syntax with `ast.parse()` on both changed files
  - Change is mechanical: only adds `with` wrapping and indentation, no logic change

## Checklist

- [x] My code follows the project's style guidelines
- [x] I have performed a self-review of my code
- [x] I have commented my code, particularly in hard-to-understand areas
- [ ] I have made corresponding changes to the documentation
- [ ] My changes generate no new warnings
- [ ] I have added tests that prove my fix is effective or that my feature works
- [ ] New and existing unit tests pass locally with my changes

## Screenshots (if applicable)

N/A
