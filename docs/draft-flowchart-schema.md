# Draft Flowchart System — Complete Reference

The draft flowchart system bridges user-facing workflow design (planning phase) and the runtime agent graph (execution phase). During planning, the queen agent creates an ISO 5807 flowchart that the user reviews. On approval, decision nodes are dissolved into runtime-compatible structures, and the original flowchart is preserved for live status overlay during execution.

---

## Architecture Overview

```
Planning Phase                    Build Gate                     Runtime Phase
─────────────────────────────────────────────────────────────────────────────

Queen LLM                      confirm_and_build()              Graph Executor
    │                                │                               │
    ▼                                ▼                               ▼
save_agent_draft()        ┌──────────────────────┐          Node execution
    │                     │ dissolve_decision_nodes│          with status
    ▼                     │                        │               │
DraftGraph (SSE) ────►    │  Decision diamonds     │               ▼
    │                     │  merged into           │          Flowchart Map
    ▼                     │  predecessor criteria   │          inverts to
Frontend renders          │                        │          overlay status
ISO 5807 flowchart        │  Original draft        │          on original
with diamond              │  preserved             │          flowchart
decisions                 │                        │
                          └──────────────────────┘
```

**Key files:**
- Backend: `core/framework/tools/queen_lifecycle_tools.py` — draft creation, classification, dissolution
- Backend: `core/framework/server/routes_graphs.py` — REST endpoints
- Frontend: `core/frontend/src/components/DraftGraph.tsx` — SVG flowchart renderer
- Frontend: `core/frontend/src/api/types.ts` — TypeScript interfaces
- Frontend: `core/frontend/src/pages/workspace.tsx` — state management and conditional rendering

---

## 1. JSON Schemas

### Tool: `save_agent_draft` — Input Schema

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
    },
    "decision_clause": {
      "type": "string",
      "description": "For decision nodes only: the yes/no question to evaluate (e.g. 'Is amount > $100?'). During dissolution, this becomes the predecessor node's success_criteria."
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
    },
    "label": {
      "type": "string",
      "description": "Short label shown on the flowchart edge (e.g. 'Yes', 'No', 'Retry')"
    }
  }
}
```

### Output: Enriched Draft Graph Object

After `save_agent_draft` processes the input, it stores and emits an enriched draft with auto-classified flowchart metadata. This is the structure sent via the `draft_graph_updated` SSE event and returned by `GET /api/sessions/{id}/draft-graph`.

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
      "decision_clause": "",
      "sub_agents": [],
      "flowchart_type": "start",
      "flowchart_shape": "stadium",
      "flowchart_color": "#4CAF50"
    },
    {
      "id": "check-tier",
      "name": "Check Tier",
      "description": "",
      "node_type": "event_loop",
      "decision_clause": "Is lead score > 80?",
      "flowchart_type": "decision",
      "flowchart_shape": "diamond",
      "flowchart_color": "#FF9800"
    }
  ],
  "edges": [
    {
      "id": "edge-0",
      "source": "intake",
      "target": "check-tier",
      "condition": "on_success",
      "description": "",
      "label": ""
    },
    {
      "id": "edge-1",
      "source": "check-tier",
      "target": "enrich",
      "condition": "on_success",
      "description": "",
      "label": "Yes"
    },
    {
      "id": "edge-2",
      "source": "check-tier",
      "target": "route",
      "condition": "on_failure",
      "description": "",
      "label": "No"
    }
  ],
  "flowchart_legend": {
    "start":    { "shape": "stadium",    "color": "#4CAF50" },
    "terminal": { "shape": "stadium",    "color": "#F44336" },
    "process":  { "shape": "rectangle",  "color": "#2196F3" },
    "decision": { "shape": "diamond",    "color": "#FF9800" }
  }
}
```

**Enriched fields** (added by backend to every node during classification):

| Field | Type | Description |
|---|---|---|
| `flowchart_type` | `string` | The resolved ISO 5807 symbol type |
| `flowchart_shape` | `string` | SVG shape identifier for the frontend renderer |
| `flowchart_color` | `string` | Hex color code for the symbol |

### Flowchart Map Object

Returned by `GET /api/sessions/{id}/flowchart-map` after `confirm_and_build()` dissolves decision nodes:

```json
{
  "map": {
    "intake": ["intake", "check-tier"],
    "enrich": ["enrich"],
    "route": ["route"]
  },
  "original_draft": { "...original draft graph before dissolution..." }
}
```

- `map`: Keys are runtime node IDs, values are lists of original draft node IDs that the runtime node absorbed.
- `original_draft`: The complete draft graph as it existed before dissolution, preserved for flowchart display.
- Both fields are `null` if no dissolution has occurred yet.

---

## 2. ISO 5807 Flowchart Types

### Core Symbols

| Type | Shape | Color | SVG Primitive | Description |
|---|---|---|---|---|
| `start` | stadium | `#4CAF50` green | `<rect rx={h/2}>` | Entry point / start terminator |
| `terminal` | stadium | `#F44336` red | `<rect rx={h/2}>` | End point / stop terminator |
| `process` | rectangle | `#2196F3` blue | `<rect rx={4}>` | General processing step |
| `decision` | diamond | `#FF9800` amber | `<polygon>` 4-point | Branching / conditional logic |
| `io` | parallelogram | `#9C27B0` purple | `<polygon>` skewed | Data input or output |
| `document` | document | `#607D8B` blue-grey | `<path>` wavy bottom | Single document output |
| `multi_document` | multi_document | `#78909C` blue-grey | stacked `<rect>` + `<path>` | Multiple documents |
| `subprocess` | subroutine | `#009688` teal | `<rect>` + inner `<line>` | Predefined process / sub-agent |
| `preparation` | hexagon | `#795548` brown | `<polygon>` 6-point | Setup / initialization step |
| `manual_input` | manual_input | `#E91E63` pink | `<polygon>` sloped top | Manual data entry |
| `manual_operation` | trapezoid | `#AD1457` dark pink | `<polygon>` tapered bottom | Human-in-the-loop / approval |
| `delay` | delay | `#FF5722` deep orange | `<path>` D-shape | Wait / pause / cooldown |
| `display` | display | `#00BCD4` cyan | `<path>` pointed left | Display / render output |

### Data Storage Symbols

| Type | Shape | Color | SVG Primitive | Description |
|---|---|---|---|---|
| `database` | cylinder | `#8BC34A` light green | `<path>` + `<ellipse>` top/bottom | Database / direct access storage |
| `stored_data` | stored_data | `#CDDC39` lime | `<path>` curved left | Generic data store |
| `internal_storage` | internal_storage | `#FFC107` amber | `<rect>` + internal `<line>` grid | Internal memory / cache |

### Connectors

| Type | Shape | Color | SVG Primitive | Description |
|---|---|---|---|---|
| `connector` | circle | `#9E9E9E` grey | `<circle>` | On-page connector |
| `offpage_connector` | pentagon | `#757575` dark grey | `<polygon>` 5-point | Off-page connector |

### Flow Operations

| Type | Shape | Color | SVG Primitive | Description |
|---|---|---|---|---|
| `merge` | triangle_inv | `#3F51B5` indigo | `<polygon>` inverted | Merge multiple flows |
| `extract` | triangle | `#5C6BC0` indigo light | `<polygon>` upward | Extract / split flow |
| `sort` | hourglass | `#7986CB` indigo lighter | `<polygon>` X-shape | Sort operation |
| `collate` | hourglass_inv | `#9FA8DA` indigo lightest | `<polygon>` X-shape inv | Collate operation |
| `summing_junction` | circle_cross | `#F06292` pink light | `<circle>` + cross `<line>` | Summing junction |
| `or` | circle_bar | `#CE93D8` purple light | `<circle>` + plus `<line>` | Logical OR |

### Domain-Specific (Hive)

| Type | Shape | Color | SVG Primitive | Description |
|---|---|---|---|---|
| `browser` | hexagon | `#1A237E` dark indigo | `<polygon>` 6-point | Browser automation (GCU node) |
| `comment` | flag | `#BDBDBD` light grey | `<path>` notched right | Annotation / comment |
| `alternate_process` | rounded_rect | `#42A5F5` light blue | `<rect rx={12}>` | Alternate process variant |

---

## 3. Auto-Classification Priority

When `flowchart_type` is omitted from a node, the backend classifies it automatically using this priority (function `_classify_flowchart_node` in `queen_lifecycle_tools.py`):

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

## 4. Decision Node Dissolution

When `confirm_and_build()` is called, decision nodes (flowchart diamonds) are dissolved into runtime-compatible structures by `_dissolve_decision_nodes()`. Decision nodes are a **planning-only** concept — they don't exist in the runtime graph.

### Algorithm

```
For each decision node D (in topological order):
  1. Find predecessors P via incoming edges
  2. Find yes-target and no-target via outgoing edges
     - Yes: edge with label "Yes"/"True"/"Pass" or condition "on_success"
     - No:  edge with label "No"/"False"/"Fail" or condition "on_failure"
     - Fallback: first outgoing = yes, second = no
  3. Get decision clause: D.decision_clause || D.description || D.name
  4. For each predecessor P:
     - Append clause to P.success_criteria
     - Remove edge P → D
     - Add edge P → yes_target (on_success)
     - Add edge P → no_target (on_failure)
  5. Remove D and all its edges from the graph
  6. Record absorption: flowchart_map[P.id] = [P.id, D.id]
```

### Edge Cases

| Case | Behavior |
|---|---|
| **Decision at start** (no predecessor) | Converted to a process node with `success_criteria` = clause; outgoing edges rewired to `on_success`/`on_failure` |
| **Chained decisions** (A → D1 → D2 → B) | Processed in order. D1 dissolves into A. D2's predecessor is now A, so D2 also dissolves into A. Map: `A → [A, D1, D2]` |
| **Multiple predecessors** | Each predecessor gets its own copy of the yes/no edges |
| **Existing success_criteria on predecessor** | Appended with `"; then evaluate: <clause>"` |
| **Decision with >2 outgoing edges** | First classified yes/no pair is used; remaining edges are preserved |

### Example

**Input (planning flowchart):**
```
[Fetch Billing Data] → <Amount > $100?> → Yes → [Generate PDF Receipt]
                                         → No  → [Draft Email Receipt]
```

**Output (runtime graph):**
```
[Fetch Billing Data] → on_success → [Generate PDF Receipt]
                     → on_failure → [Draft Email Receipt]
  success_criteria: "Amount > $100?"
```

**Flowchart map:**
```json
{
  "fetch-billing-data": ["fetch-billing-data", "amount-gt-100"],
  "generate-pdf-receipt": ["generate-pdf-receipt"],
  "draft-email-receipt": ["draft-email-receipt"]
}
```

The runtime Level 2 judge evaluates the decision clause against the node's conversation. `NodeResult.success = true` routes via `on_success` (yes), `false` routes via `on_failure` (no).

---

## 5. Frontend Rendering

### Component: `DraftGraph.tsx`

An SVG-based flowchart renderer that operates in two modes:

1. **Planning mode** — renders the draft graph with ISO 5807 shapes during the planning phase
2. **Runtime overlay mode** — renders the original (pre-dissolution) draft with live execution status when `flowchartMap` and `runtimeNodes` props are provided

#### Props

```typescript
interface DraftGraphProps {
  draft: DraftGraphData;                          // The draft graph to render
  onNodeClick?: (node: DraftNode) => void;        // Node click handler
  flowchartMap?: Record<string, string[]>;         // Runtime → draft node mapping
  runtimeNodes?: GraphNode[];                      // Live runtime graph nodes with status
}
```

#### Layout Engine

The layout algorithm arranges nodes in layers based on graph topology:

1. **Layer assignment**: Each node's layer = max(parent layers) + 1. Root nodes are layer 0.
2. **Column assignment**: Within each layer, nodes are sorted by parent column average and centered.
3. **Node sizing**: `nodeW = min(360, availableWidth / maxColumns)` — nodes fill available space up to 360px.
4. **Container measurement**: A `ResizeObserver` measures the actual container width so SVG viewBox coordinates match CSS pixels 1:1.

```
Constants:
  NODE_H   = 52px    (node height)
  GAP_Y    = 48px    (vertical gap between layers)
  GAP_X    = 16px    (horizontal gap between columns)
  MARGIN_X = 16px    (left/right margin)
  TOP_Y    = 28px    (top padding)
```

#### Shape Rendering

The `FlowchartShape` component renders each ISO 5807 shape as SVG primitives. Each shape receives:
- `x, y, w, h` — bounding box in SVG units
- `color` — the hex color from the flowchart type
- `selected` — hover state (increases fill opacity from 18% to 28%, brightens stroke)

All shapes use `strokeWidth={1.2}` to prevent overflow on hover.

#### Edge Rendering

**Forward edges** (source layer < target layer):
- Rendered as cubic bezier curves from source bottom-center to target top-center
- Fan-out: when a node has multiple outgoing edges, start points spread across 40% of node width
- Labels shown at the midpoint (from `edge.label`, or condition/description fallback)

**Back edges** (source layer >= target layer):
- Rendered as dashed arcs that loop right of the graph
- Each back edge gets a unique offset to prevent overlap

#### Node Labels

Each node displays two lines of text:
- **Primary**: Node name (font size 13, truncated to fit `nodeW - 28px`)
- **Secondary**: Node description or flowchart type (font size 9.5, truncated to fit `nodeW - 24px`)

Truncation uses `avgCharWidth = fontSize * 0.58` to estimate available characters.

#### Tooltip

An HTML overlay (not SVG) positioned below hovered nodes, showing:
- Node description
- Tools list (`Tools: tool_a, tool_b`)
- Success criteria (`Criteria: ...`)

#### Legend

A dynamic legend at the bottom of the SVG listing all flowchart types used in the current draft, with their shape and color.

### Runtime Status Overlay

When `flowchartMap` and `runtimeNodes` are provided, the component computes per-node statuses:

1. **Invert the map**: `flowchartMap` maps `runtime_id → [draft_ids]`; inversion gives `draft_id → runtime_id`
2. **Map runtime status**: For each runtime node, classify status as `running` (amber), `complete` (green), `error` (red), or `pending` (no overlay)
3. **Render overlays**:
   - **Glow ring**: A pulsing amber `<rect>` around running nodes, solid green/red for complete/error
   - **Status dot**: A small `<circle>` in the top-right corner with animated radius for running nodes
4. **Header**: Changes from "Draft / planning" to "Flowchart / live"

```typescript
// Status color mapping
const STATUS_COLORS = {
  running:  "#F59E0B",  // amber — pulsing glow
  complete: "#22C55E",  // green — solid ring
  error:    "#EF4444",  // red   — solid ring
  pending:  "",         // no overlay
};
```

### Workspace Integration (`workspace.tsx`)

The workspace conditionally renders `DraftGraph` in three scenarios:

| Condition | Renders | Panel Width |
|---|---|---|
| `queenPhase === "planning"` and `draftGraph` exists | `<DraftGraph draft={draftGraph} />` | 500px |
| `originalDraft` exists (post-planning) | `<DraftGraph draft={originalDraft} flowchartMap={...} runtimeNodes={...} />` | 500px |
| Neither | `<AgentGraph ... />` (runtime pipeline view) | 300px |

**State management:**
- `draftGraph`: Set by `draft_graph_updated` SSE event during planning; cleared on phase change
- `originalDraft` + `flowchartMap`: Fetched from `GET /api/sessions/{id}/flowchart-map` when phase transitions away from planning

---

## 6. Events & API

### SSE Event: `draft_graph_updated`

Emitted when `save_agent_draft` completes. The full draft graph object is the event `data` payload.

```
event: message
data: {"type": "draft_graph_updated", "stream_id": "queen", "data": { ...draft graph object... }, ...}
```

### REST Endpoints

**`GET /api/sessions/{session_id}/draft-graph`**

Returns the current draft graph from planning phase.
```json
{"draft": <DraftGraph object>}
// or
{"draft": null}
```

**`GET /api/sessions/{session_id}/flowchart-map`**

Returns the flowchart-to-runtime mapping and original draft (available after `confirm_and_build()`).
```json
{
  "map": { "runtime-node-id": ["draft-node-a", "draft-node-b"], ... },
  "original_draft": { ...original DraftGraph before dissolution... }
}
// or
{"map": null, "original_draft": null}
```

---

## 7. Phase Gate

The draft graph is part of a two-step gate controlling the planning → building transition:

1. **`save_agent_draft()`** — creates the draft, classifies nodes, emits `draft_graph_updated`
2. User reviews the rendered flowchart (with decision diamonds, edge labels, color-coded shapes)
3. **`confirm_and_build()`** — dissolves decision nodes, preserves original draft, builds flowchart map, sets `build_confirmed = true`
4. **`initialize_and_build_agent()`** — checks `build_confirmed` before proceeding; passes the dissolved (decision-free) draft to the scaffolder for pre-population

The scaffolder never sees decision nodes — it receives a clean graph with only runtime-compatible node types where branching is expressed through `success_criteria` + `on_success`/`on_failure` edges.
