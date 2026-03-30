"""Node definitions for Logistics Navigation Agent (Caitlyn)."""

from framework.graph import NodeSpec

# Node 1: Intake (client-facing)
intake_node: NodeSpec = NodeSpec(
    id="intake",
    name="Navigation Intake",
    description="Collect origin, destination, and intermediate stops from the user.",
    node_type="event_loop",
    client_facing=True,
    input_keys=["navigation_input"],
    output_keys=[
        "origin",
        "destination",
        "stops_requested",
        "is_ready"
    ],
    system_prompt="""\
You are Caitlyn, the voice of the navigation app. Your job is to understand where the user wants to go.

**STEP 1 — Identify input:**
- Destination (e.g., "Casa", "Trabajo", or an address).
- Origin (defaults to "current location" if not specified).
- Intermediate stops (e.g., "farmacia", "Cajero").

**STEP 2 — Use tools:**
- Use 'get_my_favorite_places' to resolve names like 'casa' or 'trabajo'.

**STEP 3 — Finalize:**
Once you have the destination and origin, call set_output for:
- origin: the coordinate string or 'current'
- destination: the coordinate string or favorite name
- stops_requested: list of strings (e.g. ["farmacia"])
- is_ready: "true"

Talk in a friendly Spanish tone.
""",
    tools=["get_my_favorite_places"],
)

# Node 2: POI Search
poi_search_node: NodeSpec = NodeSpec(
    id="poi-search",
    name="POI Coordinator",
    description="Search for coordinates of requested stops (pharmacies, gas stations, etc.)",
    node_type="event_loop",
    input_keys=["origin", "destination", "stops_requested"],
    output_keys=["resolved_locations"],
    system_prompt="""\
You are a logistics coordinator. For each stop in 'stops_requested', find the best location nearby the route.

**Process:**
1. For each item in 'stops_requested':
   - Use 'search_nearby_places' near the origin or destination.
   - Extract the 'lat' and 'lng' of the best result.
2. Compile a list including origin (if resolved), stops (resolved), and destination.

When done, call set_output("resolved_locations", <List of {lat, lng} objects>).
""",
    tools=["search_nearby_places", "get_my_favorite_places"],
)

# Node 3: Navigation
navigation_node: NodeSpec = NodeSpec(
    id="navigation",
    name="Map Synchronizer",
    description="Set the final route in the app and confirm to the user.",
    node_type="event_loop",
    client_facing=True,
    input_keys=["resolved_locations"],
    output_keys=["nav_status"],
    system_prompt="""\
You are the Map Synchronizer. Your final task is to trigger the navigation on the user's screen.

**Step:**
1. Call 'set_active_navigation' with the full JSON list of 'resolved_locations'.
2. Confirm to the user in a friendly Spanish tone: "¡Listo! He configurado tu ruta pasando por [paradas]. ¡Buen viaje!"

Set output "nav_status" to "active".
""",
    tools=["set_active_navigation"],
)

__all__ = [
    "intake_node",
    "poi_search_node",
    "navigation_node",
]
