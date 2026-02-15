# Google Maps Tool

Geocoding, routing, and location intelligence via Google Maps Platform Web Services.

## Setup

### 1. Create a Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project (or select existing)

### 2. Enable Required APIs

Enable the following APIs from the [API Library](https://console.cloud.google.com/apis/library):

- **Geocoding API** — address ↔ coordinates
- **Directions API** — route calculation
- **Distance Matrix API** — multi-origin/destination distances
- **Places API** — place search and details

### 3. Create an API Key

1. Go to [Credentials](https://console.cloud.google.com/apis/credentials)
2. Click **Create Credentials > API Key**
3. (Recommended) Click **Restrict Key** and limit to the above APIs
4. Copy the key

### 4. Configure

```bash
export GOOGLE_MAPS_API_KEY=your_api_key_here
```

Or add to your `.env` file:

```
GOOGLE_MAPS_API_KEY=your_api_key_here
```

### Pricing

Google provides **$200/month in free credits** (~40,000 geocoding requests).
See [Google Maps pricing](https://developers.google.com/maps/billing-and-pricing/pricing).

## Available Tools

| Tool | Description |
|------|-------------|
| `maps_geocode` | Convert address to coordinates (lat/lng) |
| `maps_reverse_geocode` | Convert coordinates to address |
| `maps_directions` | Calculate routes between locations |
| `maps_distance_matrix` | Distance/time for multiple origin-destination pairs |
| `maps_place_details` | Get detailed info about a place by place_id |
| `maps_place_search` | Search for places by text query |

## Tool Details

### maps_geocode

Convert an address to geographic coordinates.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `address` | str | Yes* | Address to geocode |
| `components` | str | No | Component filter (e.g., `"country:US"`) |
| `bounds` | str | No | Bounding box bias (`"south,west\|north,east"`) |
| `region` | str | No | Region bias (ccTLD code) |
| `language` | str | No | Response language |

*Either `address` or `components` is required.

### maps_reverse_geocode

Convert coordinates to a human-readable address.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `latitude` | float | Yes | Latitude (-90 to 90) |
| `longitude` | float | Yes | Longitude (-180 to 180) |
| `result_type` | str | No | Filter by type (pipe-separated) |
| `location_type` | str | No | Filter by precision |
| `language` | str | No | Response language |

### maps_directions

Calculate routes between locations.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `origin` | str | Yes | Start point (address or "lat,lng") |
| `destination` | str | Yes | End point |
| `mode` | str | No | `driving`, `walking`, `bicycling`, `transit` |
| `waypoints` | str | No | Intermediate stops (pipe-separated) |
| `alternatives` | bool | No | Request alternative routes |
| `units` | str | No | `metric` or `imperial` |
| `avoid` | str | No | `tolls\|highways\|ferries` |
| `departure_time` | str | No | Unix timestamp or `"now"` |
| `language` | str | No | Instruction language |

### maps_distance_matrix

Calculate distances and travel times for multiple origins and destinations.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `origins` | str | Yes | Origin locations (pipe-separated) |
| `destinations` | str | Yes | Destination locations (pipe-separated) |
| `mode` | str | No | Travel mode |
| `units` | str | No | Unit system |
| `avoid` | str | No | Route restrictions |
| `departure_time` | str | No | For traffic-aware estimates |
| `language` | str | No | Response language |

### maps_place_details

Get detailed information about a specific place.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `place_id` | str | Yes | Google Place ID |
| `fields` | str | No | Comma-separated field list |
| `language` | str | No | Response language |
| `reviews_sort` | str | No | `most_relevant` or `newest` |

### maps_place_search

Search for places by text query.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `query` | str | Yes | Search text |
| `location` | str | No | Center point `"lat,lng"` |
| `radius` | int | No | Search radius in meters (max 50000) |
| `type` | str | No | Place type filter |
| `language` | str | No | Response language |
| `opennow` | bool | No | Only open businesses |
| `minprice` | int | No | Price level 0-4 |
| `maxprice` | int | No | Price level 0-4 |
| `region` | str | No | Region bias (ccTLD) |

## Example Usage

```python
# Geocode an address
maps_geocode(address="1600 Amphitheatre Parkway, Mountain View, CA")

# Reverse geocode coordinates
maps_reverse_geocode(latitude=37.4224764, longitude=-122.0842499)

# Get directions
maps_directions(
    origin="New York, NY",
    destination="Boston, MA",
    mode="driving",
    alternatives=True,
)

# Calculate distance matrix
maps_distance_matrix(
    origins="New York,NY|Boston,MA",
    destinations="Philadelphia,PA|Washington,DC",
    mode="driving",
)

# Look up place details
maps_place_details(place_id="ChIJN1t_tDeuEmsRUsoyG83frY4")

# Search for places
maps_place_search(query="restaurants in Sydney", opennow=True)
```

## Error Handling

All tools return error dicts instead of raising exceptions:

```python
{"error": "Google Maps API key not configured", "help": "Set GOOGLE_MAPS_API_KEY..."}
{"error": "Request denied — check that the API is enabled and the key is valid"}
{"error": "Too many requests. Try again later"}
```
