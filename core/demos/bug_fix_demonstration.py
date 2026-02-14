"""
DEMONSTRATION: LLM Routing Bug Fix - Success vs Failure Testing

This shows exactly what happens when:
1. LLM succeeds (returns valid decision)
2. LLM fails (API error, invalid JSON, unavailable)

And how the three modes (PROCEED, SKIP, RAISE) handle each scenario.
"""

print("=" * 80)
print("  LLM ROUTING BUG FIX - SUCCESS vs FAILURE DEMONSTRATION")
print("=" * 80)

# ============================================================================
# PART 1: WHEN LLM SUCCEEDS ✅
# ============================================================================
print("\n" + "=" * 80)
print("  PART 1: WHEN LLM SUCCEEDS")
print("=" * 80)

print("""
When the LLM responds successfully with valid JSON:
  {{"proceed": true, "reasoning": "...valid reason..."}}

BEHAVIOR: All three modes (PROCEED/SKIP/RAISE) behave IDENTICALLY
The on_llm_failure setting is IGNORED because there's no failure!

┌────────────────┬─────────────────────────┐
│ Failure Mode   │ Result                  │
├────────────────┼─────────────────────────┤
│ PROCEED        │ ✓ True  (LLM said yes)  │
│ SKIP           │ ✓ True  (LLM said yes)  │
│ RAISE          │ ✓ True  (LLM said yes)  │
└────────────────┴─────────────────────────┘

If LLM says {"proceed": false}, all modes return False.
""")

# ============================================================================
# PART 2: WHEN LLM FAILS ❌ 
# ============================================================================
print("=" * 80)
print("  PART 2: WHEN LLM FAILS (This is where the bug fix matters!)")
print("=" * 80)

print("""
Failure scenarios:
  • LLM is None (not configured/unavailable)
  • LLM API throws exception (timeout, rate limit, auth error)
  • LLM returns invalid JSON (plain text instead of JSON)

⚠️  BEFORE BUG FIX:
   ALL failures → Always proceeded if source succeeded (FAIL-OPEN)
   Security vulnerability!

✅ AFTER BUG FIX:
   Three different behaviors based on on_llm_failure setting:
""")

# Scenario 1: LLM Unavailable (llm=None)
print("\n" + "-" * 80)
print("Failure Scenario 1: LLM Unavailable (llm=None)")
print("-" * 80)

print("""
Source node succeeded: True
LLM: None (service down, not configured, etc.)

┌────────────────┬──────────┬────────────────────────────────────────┐
│ Failure Mode   │ Result   │ Explanation                            │
├────────────────┼──────────┼────────────────────────────────────────┤
│ PROCEED        │ ✓ True   │ Fail-open: uses source_success         │
│ (default)      │          │ Logs: WARNING                          │
├────────────────┼──────────┼────────────────────────────────────────┤
│ SKIP           │ ✗ False  │ Fail-closed: denies access             │
│                │          │ Logs: ERROR                            │
├────────────────┼──────────┼────────────────────────────────────────┤
│ RAISE          │ 💥 Error │ Raises RuntimeError, halts execution   │
│                │          │ Logs: ERROR                            │
└────────────────┴──────────┴────────────────────────────────────────┘
""")

# Scenario 2: LLM API Exception
print("-" * 80)
print("Failure Scenario 2: LLM API Exception")
print("-" * 80)

print("""
Source node succeeded: True
LLM call raises: Exception("API connection timeout")

┌────────────────┬──────────┬────────────────────────────────────────┐
│ Failure Mode   │ Result   │ Explanation                            │
├────────────────┼──────────┼────────────────────────────────────────┤
│ PROCEED        │ ✓ True   │ Fail-open: proceeds anyway             │
│ (default)      │          │ Log: "⚠ LLM routing failed, proceeding"│
├────────────────┼──────────┼────────────────────────────────────────┤
│ SKIP           │ ✗ False  │ Fail-closed: does not proceed          │
│                │          │ Log: "✗ LLM routing failed, skipping"  │
├────────────────┼──────────┼────────────────────────────────────────┤
│ RAISE          │ 💥 Error │ RuntimeError with edge context         │
│                │          │ Chained from original exception        │
└────────────────┴──────────┴────────────────────────────────────────┘
""")

# Scenario 3: Invalid JSON Response
print("-" * 80)
print("Failure Scenario 3: Invalid JSON Response")
print("-" * 80)

print("""
Source node succeeded: True
LLM returns: "I cannot help with that request." (plain text, not JSON)

┌────────────────┬──────────┬────────────────────────────────────────┐
│ Failure Mode   │ Result   │ Explanation                            │
├────────────────┼──────────┼────────────────────────────────────────┤
│ PROCEED        │ ✓ True   │ Parse fails → fall back to proceed     │
│ (default)      │          │ Log: "⚠ Failed to parse JSON, proceed" │
├────────────────┼──────────┼────────────────────────────────────────┤
│ SKIP           │ ✗ False  │ Parse fails → deny access              │
│                │          │ Log: "✗ Failed to parse JSON, skip"    │
├────────────────┼──────────┼────────────────────────────────────────┤
│ RAISE          │ 💥 Error │ Parse fails → halt execution           │
│                │          │ Error: "LLM routing failed for edge X" │
└────────────────┴──────────┴────────────────────────────────────────┘
""")

# ============================================================================
# PART 3: SECURITY EXAMPLE
# ============================================================================
print("\n" + "=" * 80)
print("  PART 3: REAL-WORLD SECURITY EXAMPLE")
print("=" * 80)

print("""
🔒 SCENARIO: Authorization Gate for Protected API

Flow:
  1. validate_token node → ✓ Token is valid
  2. auth_check edge (LLM_DECIDE) → Should user access protected data?
  3. protected_resource node → Sensitive customer data

QUESTION: What happens if the LLM fails during authorization check?
""")

print("\n❌ BEFORE BUG FIX (Vulnerable):")
print("""
EdgeSpec(
    id="auth-check",
    condition=EdgeCondition.LLM_DECIDE,
    # No on_llm_failure specified
)

Result when LLM fails: ✓ PROCEEDS (because token was valid)
Impact: SECURITY VULNERABILITY - unauthorized access on LLM failure!
Attack: Attacker could trigger LLM failures to bypass authorization
""")

print("✅ AFTER BUG FIX (Secure):")
print("""
EdgeSpec(
    id="auth-check",
    condition=EdgeCondition.LLM_DECIDE,
    on_llm_failure=LLMFailureMode.SKIP,  # ← Explicit fail-closed
    description="Authorization gate - deny access on LLM failures"
)

Result when LLM fails: ✗ DOES NOT PROCEED (fail-closed)
Impact: SECURE - access denied, user sees "Authorization service unavailable"
Defense: Even if attacker causes LLM failure, they cannot access data
""")

# ============================================================================
# SUMMARY
# ============================================================================
print("\n" + "=" * 80)
print("  SUMMARY: MODE SELECTION GUIDE")
print("=" * 80)

print("""
┌──────────────┬────────────────────┬─────────────────────────────────────┐
│ Mode         │ When LLM Fails     │ Use Cases                           │
├──────────────┼────────────────────┼─────────────────────────────────────┤
│ PROCEED      │ Returns True/False │ • Non-critical routing              │
│ (default)    │ based on source    │ • Best-effort optimization          │
│              │                    │ • High availability requirement     │
│              │                    │ • Backward compatible               │
├──────────────┼────────────────────┼─────────────────────────────────────┤
│ SKIP         │ Always returns     │ • Authorization gates 🔒            │
│              │ False              │ • Access control                    │
│              │                    │ • Sensitive data routing            │
│              │                    │ • Security-critical decisions       │
├──────────────┼────────────────────┼─────────────────────────────────────┤
│ RAISE        │ Raises Runtime     │ • LLM decision is mandatory         │
│              │ Error              │ • Cannot proceed without LLM        │
│              │                    │ • Critical business logic           │
│              │                    │ • Requires human intervention       │
└──────────────┴────────────────────┴─────────────────────────────────────┘

KEY INSIGHT:
  When LLM succeeds → All modes behave the same ✅
  When LLM fails   → Choose mode based on your security/business needs ⚙️
""")

print("=" * 80)
print("  End of Demonstration")
print("=" * 80)
print("\nTo see actual code implementation:")
print("  • Tests: /core/tests/test_llm_routing_failure_modes.py")
print("  • Implementation: /core/framework/graph/edge.py")
print("  • Demo script: /core/demos/llm_routing_failure_modes_demo.py")
