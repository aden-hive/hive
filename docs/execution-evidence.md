# Execution Evidence Model

## Problem

In distributed or external tool interactions, execution does not imply confirmation:

- **Timeouts** may hide partial success
- **Retries** may succeed outside observation window  
- **External APIs** may have eventual consistency
- **Async operations** may complete after timeout

## Solution

The Execution Evidence model separates:

1. **Execution attempt** - what we tried to do
2. **Observed result** - what we saw happen
3. **Evidence quality** - how confident we are

## Evidence Types

| Type | Meaning | Example |
|------|---------|---------|
| `CONFIRMED` | Verified the effect | API returned 200 + verified in DB |
| `OBSERVED` | Saw the result | API returned 200 |
| `ASSUMED` | Inferred from context | Timeout but likely succeeded |
| `UNKNOWN` | No evidence | Network error |

## Usage

```python
from framework.runtime.evidence import ExecutionAttempt, EvidenceType
from datetime import datetime

# Before execution
attempt = ExecutionAttempt(
    attempt_id="node_1_attempt_2",
    node_id="api_caller",
    started_at=datetime.now(),
)

# Execute
result = await call_external_api()

# Classify evidence
attempt.finished_at = datetime.now()
attempt.observed_result = str(result)

if result.verified:
    attempt.evidence_type = EvidenceType.CONFIRMED
elif result.success:
    attempt.evidence_type = EvidenceType.OBSERVED
else:
    attempt.evidence_type = EvidenceType.UNKNOWN
```

## Integration with Runtime Logging

The `NodeStepLog` model now includes an optional `execution_attempt` field:

```python
from framework.runtime.runtime_log_schemas import NodeStepLog

step_log = NodeStepLog(
    node_id="api_caller",
    execution_attempt=attempt,
    evidence_quality=attempt.evidence_type.value,
)
```

## Future Work

- **Reconciliation service** - verify assumed successes
- **Evidence-based retry policies** - retry on low confidence
- **Guardrails** - block actions with insufficient evidence
- **Adaptive learning** - improve evidence classification over time

## Design Principles

1. **Backward compatible** - all fields optional
2. **Zero behavior change** - purely observational
3. **Minimal overhead** - lightweight dataclass
4. **Future-proof** - enables reconciliation layer
