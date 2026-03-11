# Draft Flowchart Graph — JSON Schema Reference

The draft graph is a lightweight, visual-only representation created during the queen agent's **planning phase**. It lets users see and explore their business process as a rendered ISO 5807 flowchart before any executable code is generated.

## Tool: `save_agent_draft`

### Input Schema

```json
{
  "type": "object",
  "required": ["agent_name", "goal", "nodes"],
  "properties": {
    "agent_name": {
      "type": "string",
      "description": "Snake_case name for the agent (e.g. 'lead_router_agent')"
    },
    "goal": {
      "type": "string",
      "description": "High-level goal description for the agent"
    },
    "description": {
      "type": "string",
      "description": "Brief description of what the agent does"
    },
    "nodes": {
      "type": "array",
      "description": "Graph nodes. Only 'id' is required; all other fields are optional hints.",
      "items": { "$ref": "#/$defs/DraftNode" }
    },
    "edges": {
      "type": "array",
      "description": "Connections between nodes. Auto-generated as linear if omitted.",
      "items": { "$ref": "#/$defs/DraftEdge" }
    },
    "terminal_nodes": {
      "type": "array",
      "items": { "type": "string" },
      "description": "Node IDs that are terminal (end) nodes. Auto-detected from edges if omitted."
    },
    "success_criteria": {
      "type": "array",
      "items": { "type": "string" },
      "description": "Agent-level success criteria"
    },
    "constraints": {
      "type": "array",
      "items": { "type": "string" },
      "description": "Agent-level constraints"
    }
  }
}
```

### Node Schema (`DraftNode`)

```json
{
  "type": "object",
  "required": ["id"],
  "properties": {
    "id": {
      "type": "string",
      "description": "Kebab-case node identifier (e.g. 'enrich-lead')"
    },
    "name": {
      "type": "string",
      "description": "Human-readable display name. Defaults to id if omitted."
    },
    "description": {
      "type": "string",
      "description": "What this node does (business logic). Used for auto-classification."
    },
    "node_type": {
      "type": "string",
      "enum": ["event_loop", "gcu"],
      "default": "event_loop",
      "description": "Runtime node type. 'gcu' maps to browser automation."
    },
    "flowchart_type": {
      "type": "string",
      "enum": [
        "start", "terminal", "process", "decision",
        "io", "document", "multi_document",
        "subprocess", "preparation",
        "manual_input", "manual_operation",
        "delay", "display",
        "database", "stored_data", "internal_storage",
        "connector", "offpage_connector",
        "merge", "extract", "sort", "collate",
        "summing_junction", "or",
        "browser", "comment", "alternate_process"
      ],
      "description": "ISO 5807 flowchart symbol. Auto-detected if omitted."
    },
    "tools": {
      "type": "array",
      "items": { "type": "string" },
      "description": "Planned tool names (hints for scaffolder, not validated)"
    },
    "input_keys": {
      "type": "array",
      "items": { "type": "string" },
      "description": "Expected input memory keys"
    },
    "output_keys": {
      "type": "array",
      "items": { "type": "string" },
      "description": "Expected output memory keys"
    },
    "success_criteria": {
      "type": "string",
      "description": "What success looks like for this node"
    }
  }
}
```

### Edge Schema (`DraftEdge`)

```json
{
  "type": "object",
  "required": ["source", "target"],
  "properties": {
    "source": {
      "type": "string",
      "description": "Source node ID"
    },
    "target": {
      "type": "string",
      "description": "Target node ID"
    },
    "condition": {
      "type": "string",
      "enum": ["always", "on_success", "on_failure", "conditional", "llm_decide"],
      "default": "on_success",
      "description": "Edge traversal condition"
    },
    "description": {
      "type": "string",
      "description": "Human-readable description of when this edge is taken"
    }
  }
}
```

---

## Output: Draft Graph Object

After `save_agent_draft` processes the input, it stores and emits a enriched draft with auto-classified flowchart metadata. This is the structure sent via the `draft_graph_updated` SSE event and returned by `GET /api/sessions/{id}/draft-graph`.

```json
{
  "agent_name": "lead_router_agent",
  "goal": "Enrich and route incoming leads",
  "description": "Automated lead enrichment and routing agent",
  "success_criteria": ["Lead score calculated", "Correct tier assigned"],
  "constraints": ["Apollo enrichment required before routing"],
  "entry_node": "intake",
  "terminal_nodes": ["route"],
  "nodes": [
    {
      "id": "intake",
      "name": "Intake",
      "description": "Fetch contact from HubSpot",
      "node_type": "event_loop",
      "tools": ["hubspot_get_contact"],
      "input_keys": ["contact_id"],
      "output_keys": ["contact_data", "domain"],
      "success_criteria": "Contact data retrieved",
      "sub_agents": [],
      "flowchart_type": "start",
      "flowchart_shape": "stadium",
      "flowchart_color": "#4CAF50"
    }
  ],
  "edges": [
    {
      "id": "edge-0",
      "source": "intake",
      "target": "enrich",
      "condition": "on_success",
      "description": ""
    }
  ],
  "flowchart_legend": {
    "start":    { "shape": "stadium",    "color": "#4CAF50" },
    "terminal": { "shape": "stadium",    "color": "#F44336" },
    "process":  { "shape": "rectangle",  "color": "#2196F3" }
  }
}
```

### Enriched Node Fields

These three fields are added by the backend to every node during classification:

| Field | Type | Description |
|---|---|---|
| `flowchart_type` | `string` | The resolved ISO 5807 symbol type |
| `flowchart_shape` | `string` | SVG shape identifier for the frontend renderer |
| `flowchart_color` | `string` | Hex color code for the symbol |

---

## ISO 5807 Flowchart Types

### Core Symbols

| Type | Shape | Color | Description |
|---|---|---|---|
| `start` | stadium | `#4CAF50` green | Entry point / start terminator |
| `terminal` | stadium | `#F44336` red | End point / stop terminator |
| `process` | rectangle | `#2196F3` blue | General processing step |
| `decision` | diamond | `#FF9800` amber | Branching / conditional logic |
| `io` | parallelogram | `#9C27B0` purple | Data input or output |
| `document` | document | `#607D8B` blue-grey | Single document output |
| `multi_document` | multi_document | `#78909C` blue-grey light | Multiple documents |
| `subprocess` | subroutine | `#009688` teal | Predefined process / sub-agent |
| `preparation` | hexagon | `#795548` brown | Setup / initialization step |
| `manual_input` | manual_input | `#E91E63` pink | Manual data entry |
| `manual_operation` | trapezoid | `#AD1457` dark pink | Human-in-the-loop / approval |
| `delay` | delay | `#FF5722` deep orange | Wait / pause / cooldown |
| `display` | display | `#00BCD4` cyan | Display / render output |

### Data Storage Symbols

| Type | Shape | Color | Description |
|---|---|---|---|
| `database` | cylinder | `#8BC34A` light green | Database / direct access storage |
| `stored_data` | stored_data | `#CDDC39` lime | Generic data store |
| `internal_storage` | internal_storage | `#FFC107` amber light | Internal memory / cache |

### Connectors

| Type | Shape | Color | Description |
|---|---|---|---|
| `connector` | circle | `#9E9E9E` grey | On-page connector |
| `offpage_connector` | pentagon | `#757575` dark grey | Off-page connector |

### Flow Operations

| Type | Shape | Color | Description |
|---|---|---|---|
| `merge` | triangle_inv | `#3F51B5` indigo | Merge multiple flows |
| `extract` | triangle | `#5C6BC0` indigo light | Extract / split flow |
| `sort` | hourglass | `#7986CB` indigo lighter | Sort operation |
| `collate` | hourglass_inv | `#9FA8DA` indigo lightest | Collate operation |
| `summing_junction` | circle_cross | `#F06292` pink light | Summing junction |
| `or` | circle_bar | `#CE93D8` purple light | Logical OR |

### Domain-Specific (Hive)

| Type | Shape | Color | Description |
|---|---|---|---|
| `browser` | hexagon | `#1A237E` dark indigo | Browser automation (GCU node) |
| `comment` | flag | `#BDBDBD` light grey | Annotation / comment |
| `alternate_process` | rounded_rect | `#42A5F5` light blue | Alternate process variant |

---

## Auto-Classification Priority

When `flowchart_type` is omitted from a node, the system classifies it automatically using this priority:

1. **Explicit override** — if `flowchart_type` is set and valid, use it
2. **Node type** — `gcu` nodes become `browser`
3. **Position** — first node becomes `start`
4. **Terminal detection** — nodes in `terminal_nodes` (or with no outgoing edges) become `terminal`
5. **Branching structure** — nodes with 2+ outgoing edges with different conditions become `decision`
6. **Sub-agents** — nodes with `sub_agents` become `subprocess`
7. **Tool heuristics** — tool names match known patterns:
   - DB tools (`query_database`, `sql_query`, `read_table`, etc.) → `database`
   - Doc tools (`generate_report`, `create_document`, etc.) → `document`
   - I/O tools (`send_email`, `post_to_slack`, `fetch_url`, etc.) → `io`
   - Display tools (`serve_file_to_user`, `display_results`) → `display`
8. **Description keyword heuristics**:
   - `"manual"`, `"approval"`, `"human review"` → `manual_operation`
   - `"setup"`, `"prepare"`, `"configure"` → `preparation`
   - `"wait"`, `"delay"`, `"pause"` → `delay`
   - `"merge"`, `"combine"`, `"aggregate"` → `merge`
   - `"display"`, `"show"`, `"render"` → `display`
   - `"database"`, `"data store"`, `"persist"` → `database`
   - `"report"`, `"document"`, `"summary"` → `document`
   - `"deliver"`, `"send"`, `"notify"` → `io`
9. **Default** — `process` (blue rectangle)

---

## Events & API

### SSE Event: `draft_graph_updated`

Emitted when `save_agent_draft` completes. The full draft graph object is the event `data` payload.

```
event: message
data: {"type": "draft_graph_updated", "stream_id": "queen", "data": { ...draft graph object... }, ...}
```

### REST Endpoint

```
GET /api/sessions/{session_id}/draft-graph
```

Returns `{"draft": <draft graph object>}` or `{"draft": null}` if no draft exists.

---

## Phase Gate

The draft graph is part of a two-step gate controlling the planning → building transition:

1. **`save_agent_draft()`** — creates the draft, emits `draft_graph_updated`
2. User reviews the rendered flowchart
3. **`confirm_and_build()`** — sets `build_confirmed = true`
4. **`initialize_and_build_agent()`** — checks `build_confirmed` before proceeding; passes draft metadata to the scaffolder for pre-population
