"""Stage 1: Offline conformance tests for tool modules.

Runs in CI on every PR. No credentials, no network.
Verifies that tool modules follow codebase conventions:
- 1a: Spec conformance (structure, signatures, credential specs)
- 1b: Registration (register_tools doesn't raise, tools exist)
- 1c: Input validation (credential errors, required params)
"""
