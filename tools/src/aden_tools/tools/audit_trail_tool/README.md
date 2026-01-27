# Audit Trail Tool

Track and record all decisions made by AI agents over time for debugging, compliance, and observability.

## Description

The Audit Trail Tool creates a complete timeline of agent decisions, including:
- **What** decisions were made
- **When** they were made (timestamps)
- **Why** they were made (context/reasoning)
- **What** the outcomes were

This is essential for:
- **Production debugging** - Understand why agents failed
- **Compliance** - Maintain records for audits (GDPR, SOX, etc.)
- **Observability** - Analyze agent behavior patterns
- **Trust** - Provide transparency in agent decision-making

## Tools

### `record_decision`

Record a decision made by an agent.

**Arguments:**

| Argument | Type | Required | Default | Description |
|----------|------|----------|---------|-------------|
| `agent_id` | str | Yes | - | Unique identifier for the agent |
| `decision_type` | str | Yes | - | Type of decision (e.g., "action", "retry", "escalate", "accept") |
| `decision` | str | Yes | - | Description of the decision made |
| `context` | str | No | `None` | Optional context or reasoning |
| `outcome` | str | No | `None` | Optional outcome or result |
| `metadata` | dict | No | `None` | Optional additional metadata |
| `audit_dir` | str | No | `~/.aden/audit_trails` | Custom directory for audit files |

**Returns:**
- Success status with decision ID and timestamp
- Error dict if validation fails

**Example:**
```python
record_decision(
    agent_id="support_agent_001",
    decision_type="action",
    decision="Escalate ticket to senior support",
    context="Customer requested manager",
    outcome="Ticket assigned to manager",
    metadata={"ticket_id": "TKT-123", "priority": "high"}
)
```

### `get_audit_trail`

Retrieve audit trail for an agent with optional filtering.

**Arguments:**

| Argument | Type | Required | Default | Description |
|----------|------|----------|---------|-------------|
| `agent_id` | str | Yes | - | Unique identifier for the agent |
| `start_date` | str | No | `None` | Start date filter (ISO format) |
| `end_date` | str | No | `None` | End date filter (ISO format) |
| `decision_type` | str | No | `None` | Filter by decision type |
| `limit` | int | No | `100` | Maximum decisions to return (1-1000) |
| `audit_dir` | str | No | `~/.aden/audit_trails` | Custom directory for audit files |

**Returns:**
- Dict with filtered decisions, total count, and metadata
- Error dict if query fails

**Example:**
```python
get_audit_trail(
    agent_id="support_agent_001",
    start_date="2025-01-01",
    end_date="2025-01-31",
    decision_type="escalate",
    limit=50
)
```

### `export_audit_trail`

Export audit trail to a file in JSON or CSV format.

**Arguments:**

| Argument | Type | Required | Default | Description |
|----------|------|----------|---------|-------------|
| `agent_id` | str | Yes | - | Unique identifier for the agent |
| `output_format` | str | No | `"json"` | Export format: "json" or "csv" |
| `output_path` | str | No | Auto-generated | Custom output file path |
| `start_date` | str | No | `None` | Start date filter (ISO format) |
| `end_date` | str | No | `None` | End date filter (ISO format) |
| `decision_type` | str | No | `None` | Filter by decision type |
| `audit_dir` | str | No | `~/.aden/audit_trails` | Custom directory for audit files |

**Returns:**
- Success status with output file path
- Error dict if export fails

**Example:**
```python
export_audit_trail(
    agent_id="support_agent_001",
    output_format="csv",
    output_path="./reports/audit_jan_2025.csv",
    start_date="2025-01-01",
    end_date="2025-01-31"
)
```

## Storage

Audit trails are stored as JSON files in:
- **Default location:** `~/.aden/audit_trails/`
- **File naming:** `{agent_id}_audit.json`
- **Format:** JSON array of decision records

Each decision record contains:
```json
{
  "timestamp": "2025-01-26T10:30:00Z",
  "agent_id": "support_agent_001",
  "decision_type": "action",
  "decision": "Escalate ticket to senior support",
  "context": "Customer requested manager",
  "outcome": "Ticket assigned to manager",
  "metadata": {
    "ticket_id": "TKT-123",
    "priority": "high"
  }
}
```

## Environment Variables

This tool does not require any environment variables. Audit files are stored locally by default.

To use a custom storage location, pass `audit_dir` parameter to each tool call, or set:
```bash
export ADEN_AUDIT_DIR="/custom/path/to/audits"
```

## Error Handling

All tools return error dicts for common issues:
- `"agent_id is required"` - Missing agent identifier
- `"decision_type is required"` - Missing decision type
- `"Invalid start_date format"` - Date format error
- `"Failed to record decision"` - Storage error

## Use Cases

1. **Debugging Agent Failures**
   ```python
   # Record when agent decides to retry
   record_decision(
       agent_id="my_agent",
       decision_type="retry",
       decision="Retrying API call after timeout",
       context="Previous attempt failed with timeout error",
       metadata={"attempt": 2, "max_attempts": 3}
   )
   ```

2. **Compliance Reporting**
   ```python
   # Export monthly audit trail for compliance
   export_audit_trail(
       agent_id="financial_agent",
       output_format="csv",
       start_date="2025-01-01",
       end_date="2025-01-31"
   )
   ```

3. **Behavior Analysis**
   ```python
   # Get all escalation decisions
   get_audit_trail(
       agent_id="support_agent",
       decision_type="escalate",
       limit=100
   )
   ```

## Notes

- Audit trails are stored locally by default
- Files are automatically created if they don't exist
- Decisions are appended chronologically
- Large audit trails (>10,000 decisions) may impact query performance
- For production use, consider database storage (future enhancement)

## Future Enhancements

- Database storage backend (PostgreSQL, MongoDB)
- Real-time streaming of decisions
- Integration with agent runtime for automatic recording
- Advanced querying (full-text search, aggregation)
- Retention policies and automatic cleanup
