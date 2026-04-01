# Local Business Extractor

Finds local businesses on Google Maps, scrapes their websites for contact details, and syncs everything to a Google Sheets spreadsheet.

## Nodes

| Node | Type | Description |
|------|------|-------------|
| `map-search-worker` | `gcu` (browser) | Searches Google Maps and extracts business names + website URLs |
| `extract-contacts` | `event_loop` | Scrapes business websites for emails, phone, hours, reviews, address |
| `sheets-sync` | `event_loop` | Appends extracted data to a Google Sheets spreadsheet |

## Flow

```
extract-contacts → sheets-sync → (loop back to extract-contacts)
       ↓
  map-search-worker (sub-agent)
```

## Tools used

- **Exa** — `exa_search`, `exa_get_contents` for web scraping
- **Google Sheets** — `google_sheets_create_spreadsheet`, `google_sheets_update_values`, `google_sheets_append_values`, `google_sheets_get_values`
- **Browser (GCU)** — automated Google Maps browsing

## Running

```bash
uv run python -m examples.templates.local_business_extractor run --query "bakeries in San Francisco"
```
