# Field Service Dispatch Agent

AI-powered field service dispatch agent that handles the complete dispatch workflow:
service request intake, priority triage, technician matching, and coordinated
notification with human-in-the-loop dispatcher approval.

## Use Cases

- **HVAC/Plumbing/Electrical service companies** dispatching technicians to customer sites
- **Property management** coordinating maintenance crews across multiple properties
- **Emergency repair services** with SLA-driven priority routing
- **Fleet management** optimizing technician routes and workload balance

## Graph Flow

```
intake (client_facing) → triage_and_plan → dispatch → notify (client_facing)
                              ↑                |
                              └── reassign ────┘  (if no suitable tech)
```

### Nodes

| Node | Type | Description |
|------|------|-------------|
| `intake` | Client-facing | Collects service request details from customer/dispatcher |
| `triage_and_plan` | Autonomous | Classifies priority (P1-P4), determines skills, calculates SLA |
| `dispatch` | Autonomous | Matches best technician by skills, proximity, availability |
| `notify` | Client-facing | Presents plan for dispatcher approval, coordinates notifications |

### Priority Levels

| Priority | Label | SLA | Examples |
|----------|-------|-----|----------|
| P1 | Emergency | 1 hour | Gas leak, flooding, electrical hazard |
| P2 | Urgent | 4 hours | No hot water, HVAC down, security failure |
| P3 | Standard | 24 hours | Equipment malfunction, performance issues |
| P4 | Low | 72 hours | Scheduled maintenance, minor adjustments |

## Setup

```bash
# From the hive repository root
cd examples/templates/field_service_dispatch

# Run the agent
uv run python -m examples.templates.field_service_dispatch run \
  --request "AC unit not cooling at 123 Main St, Phoenix AZ"

# Validate the agent structure
uv run python -m examples.templates.field_service_dispatch validate

# Show agent info
uv run python -m examples.templates.field_service_dispatch info

# Interactive TUI mode
uv run python -m examples.templates.field_service_dispatch tui
```

## Tools Used

| Tool | Node | Purpose |
|------|------|---------|
| `get_current_time` | triage, dispatch | SLA deadline calculation, scheduling |
| `web_search` | triage, dispatch | Equipment specs, known issues lookup |
| `send_email` | notify | Customer/technician notifications |

## Customization

To adapt this template for your organization:

1. **Technician database** — Replace the simulated dispatch logic in the `dispatch` node
   with queries to your fleet management system or technician API
2. **Priority rules** — Adjust the SLA windows and classification criteria in `triage_and_plan`
   to match your service level agreements
3. **Notification channels** — Extend the `notify` node to use SMS, push notifications,
   or your preferred communication platform
4. **Skill taxonomy** — Update the skill categories in `triage_and_plan` to match your
   team's certifications and specializations
