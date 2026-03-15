# Logistics Navigation Agent — Caitlyn

A dispatch agent that plans shipment routes, evaluates carriers, and generates complete dispatch manifests.

## What It Does

1. **Intake** — Gathers shipment details (origin, destination, cargo specs, deadline, special requirements) via interactive conversation.
2. **Route Planning** — Researches routing options and transit times, evaluates 2-3 carrier options (FedEx, UPS, regional freight, LTL), and calculates realistic ETAs.
3. **Dispatch & Manifest** — Generates a formatted HTML dispatch manifest, presents the carrier recommendation with cost and transit estimates, and confirms with the user.

## Example Use Cases

- **Last-mile delivery planning** — plan a courier route for same-day deliveries
- **Freight dispatch** — evaluate LTL vs FTL options for a pallet shipment
- **Cross-border shipping** — identify required permits and compliant carriers
- **Multi-stop routing** — plan a driver's daily delivery sequence

## Required Tools

| Tool | Used For |
|------|----------|
| `web_search` | Carrier research, routing, transit times |
| `web_scrape` | Carrier rate pages, permit requirements |
| `save_data` | Save dispatch manifest HTML |
| `serve_file_to_user` | Share manifest download link |
| `load_data` | Load saved manifest if needed |

No external API credentials are required for basic operation.

## Running the Agent

```bash
hive run examples/templates/logistics_nav_agent
```

Or open in the workspace and start with a message like:
> "I need to ship 500 kg of electronics from Chicago, IL to Atlanta, GA by Friday"

## Example Inputs

- `request`: Natural language description of the shipment
- `origin`: Full pickup address (optional — can be provided in conversation)
- `destination`: Full delivery address (optional — can be provided in conversation)

## Example Output

The agent produces:
- A **route plan** with waypoints and distance
- **Carrier options** with cost and transit time estimates
- An **estimated ETA** date
- A **dispatch manifest** HTML file with all shipment details
