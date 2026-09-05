# Logistics Navigation Agent (Caitlyn)

This agent demonstrates how to use the Hive framework to coordinate real-world logistics processes. It integrates with a custom Maps API via MCP to provide a smart navigation experience.

## The Journey: Hybrid Architecture

This project isn't just a stand-alone agent; it's a **Bridge between Local AI and Hive's Reasoning Power**. Here is how the integration was built:

1.  **Environment Sync**: Cloned the Hive repository and initialized the standard workspace.
2.  **MCP Creation**: Developed a custom MCP server (`ionic-notif`) in a separate FastAPI backend to expose domain-specific tools (Navigation, Weather, Favorites).
3.  **Cross-Backend Connection**: Linked Hive to this local MCP server, allowing Hive to prioritize and use my custom parameters over generic tools.
4.  **Delegation Logic (The "Caitlyn" Tier)**: 
    - My local AI engine (**Caitlyn**) acts as the primary gatekeeper.
    - When Caitlyn detects a complex navigation or logistics request, she seamlessly delegates the reasoning to **Hive**.
    - **Hive** uses Gemini Flash to orchestrate the multi-step tools (resolving coordinates, calculating metrics).
5.  **Output Digestion**: Hive returns a structured response; Caitlyn "digests" this reasoning and presents it to the user in a friendly, conversational way.
6.  **Action Execution**: The final response triggers real actions in the frontend, such as plotting multi-stop routes, checking weather along a specific path, or synchronizing the map state.

## Workflow
1. **Intake**: Parses user intent (origin, destination, stops) in natural language via Hive's structured nodes.
2. **POI Coordinator**: Resolves vague stops (e.g., "pharmacy") to precise coordinates using the connected MCP tools.
3. **Map Synchronizer**: Finalizes the route and triggers the visual map in the active Ionic application.

## Key Features
- **MCP Integration**: Directly communicates with a FastAPI-based map backend.
- **Smart Favorites**: Resolves logical names like "home" or "work" using favorite place tools.
- **Multi-stop Optimization**: Handles any number of intermediate waypoints.

## Technical Feedback & Insights (for Core Contributors)

While building this agent and integrating it into an existing maps infrastructure, I've identified several areas where the Hive framework could be strengthened for enterprise production:

### 1. Stateless MCP Context (Critical)
Currently, MCP servers are "blind" to the agent's state. To sync the navigation, our tool had to rely on scanning the `.hive/parts/` directory to find the active `session_id`.
- **Proposed Solution**: Implement a standardized **Context Payload** in every MCP tool call, including `session_id`, `user_metadata`, and `parent_node_id`.

### 2. Node Schema Enforcement (Strict Typing)
Passing data between nodes (`input_keys`/`output_keys`) via plain strings is error-prone. In logistics, a mismatch between `lat`/`lng` and `latitude`/`longitude` can break the entire graph.
- **Proposed Solution**: Enable **Pydantic Model** support for Node inputs and outputs to ensure strict data contracts and provide better validation before execution.

### 3. Real-time Event Streaming
Relying on JSON polling from the `parts/` directory for frontend synchronization is inefficient for high-volume apps.
- **Proposed Solution**: Introduce an official **WebSocket or Webhook event bus** that allows external systems to subscribe to "node_completed" or "tool_called" events in real-time.

### 4. Granular Degradation Policies (Self-Healing)
The "self-healing" loop lacks clear "back-off" or "manual escalation" policies. If a critical tool (like a Geocoder) fails multiple times, there's no native way to force a human-in-the-loop intervention specifically for that failure.
- **Proposed Solution**: Add `retry_strategy` and `escalation_policy` configuration per Node to allow the agent to gracefullly degrade or ask for help.

### 5. Dependency Isolation in UV Workspace
The strict separation in the `uv` layout sometimes creates friction when sharing business logic between the `core` and custom `tools`. 
- **Pros**: Blazing fast environment setup.
- **Cons**: Difficult to maintain a shared "domain layer" without creating circular dependencies.
