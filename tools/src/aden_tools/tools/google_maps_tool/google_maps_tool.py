"""
Google Maps Platform Tool - Geocoding, Routing & Location Intelligence.

Provides six MCP tools for interacting with Google Maps Platform Web Services:
- maps_geocode: Address to coordinates
- maps_reverse_geocode: Coordinates to address
- maps_directions: Route calculation
- maps_distance_matrix: Multi-origin/destination distances
- maps_place_details: Place information lookup
- maps_place_search: Text-based place search

All endpoints use API key authentication via GOOGLE_MAPS_API_KEY.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Literal

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

# Google Maps API base URLs
_GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
_DIRECTIONS_URL = "https://maps.googleapis.com/maps/api/directions/json"
_DISTANCE_MATRIX_URL = "https://maps.googleapis.com/maps/api/distancematrix/json"
_PLACE_DETAILS_URL = "https://maps.googleapis.com/maps/api/place/details/json"
_PLACE_SEARCH_URL = "https://maps.googleapis.com/maps/api/place/textsearch/json"

_MISSING_KEY_ERROR = {
    "error": "Google Maps API key not configured",
    "help": (
        "Set GOOGLE_MAPS_API_KEY environment variable. "
        "Get a key at https://console.cloud.google.com/apis/credentials "
        "and enable the Geocoding, Directions, Distance Matrix, and Places APIs."
    ),
}

_REQUEST_TIMEOUT = 30.0


class _GoogleMapsClient:
    """Internal HTTP client for Google Maps Platform API calls."""

    def __init__(self, api_key: str):
        self._api_key = api_key

    def get(self, url: str, params: dict) -> httpx.Response:
        """Execute a GET request with API key authentication."""
        params["key"] = self._api_key
        return httpx.get(url, params=params, timeout=_REQUEST_TIMEOUT)

    def handle_status(self, api_status: str, error_message: str = "") -> dict | None:
        """Check API-level status and return error dict if not OK.

        Returns None if the status is OK or ZERO_RESULTS (valid responses).
        Returns an error dict for all other statuses.
        """
        if api_status in ("OK", "ZERO_RESULTS"):
            return None

        status_messages = {
            "OVER_DAILY_LIMIT": "API key invalid, billing not enabled, or daily limit exceeded",
            "OVER_QUERY_LIMIT": "Too many requests. Try again later",
            "REQUEST_DENIED": "Request denied — check that the API is enabled and the key is valid",
            "INVALID_REQUEST": "Invalid request — check required parameters",
            "MAX_ELEMENTS_EXCEEDED": "Too many origins × destinations (max 625 elements)",
            "MAX_DIMENSIONS_EXCEEDED": "Too many origins or destinations (max 25 each)",
            "MAX_WAYPOINTS_EXCEEDED": "Too many waypoints (max 25)",
            "NOT_FOUND": "One or more locations could not be found",
            "UNKNOWN_ERROR": "Server error — please retry",
        }

        message = status_messages.get(api_status, f"API error: {api_status}")
        if error_message:
            message = f"{message}. {error_message}"

        return {"error": message}


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register Google Maps tools with the MCP server."""

    def _get_api_key() -> str | None:
        """Get the Google Maps API key from credentials or environment."""
        if credentials is not None:
            return credentials.get("google_maps")
        return os.getenv("GOOGLE_MAPS_API_KEY")

    def _make_client() -> _GoogleMapsClient | None:
        """Create a client if API key is available, otherwise return None."""
        api_key = _get_api_key()
        if not api_key:
            return None
        return _GoogleMapsClient(api_key)

    # ── Tool 1: Geocoding ──────────────────────────────────────────────

    @mcp.tool()
    def maps_geocode(
        address: str,
        components: str = "",
        bounds: str = "",
        region: str = "",
        language: str = "",
    ) -> dict:
        """
        Convert an address to geographic coordinates (latitude/longitude).

        Use this when you need to get the coordinates for a street address,
        city name, landmark, or any location string.

        Args:
            address: The street address or location to geocode
                (e.g., "1600 Amphitheatre Parkway, Mountain View, CA")
            components: Filter by component types separated by pipes
                (e.g., "country:US|postal_code:94043")
            bounds: Bounding box to bias results (format: "south,west|north,east"
                e.g., "34.0,-118.5|34.1,-118.4")
            region: Region bias as ccTLD code (e.g., "us", "uk", "de")
            language: Language code for results (e.g., "en", "es", "fr")

        Returns:
            Dict with geocoding results including formatted_address,
            coordinates (lat/lng), place_id, and address components
        """
        if not address and not components:
            return {"error": "Either address or components is required"}

        client = _make_client()
        if client is None:
            return _MISSING_KEY_ERROR

        params: dict[str, str] = {}
        if address:
            params["address"] = address
        if components:
            params["components"] = components
        if bounds:
            params["bounds"] = bounds
        if region:
            params["region"] = region
        if language:
            params["language"] = language

        try:
            response = client.get(_GEOCODE_URL, params)

            if response.status_code != 200:
                return {"error": f"HTTP {response.status_code}: {response.text[:200]}"}

            data = response.json()
            status_error = client.handle_status(
                data.get("status", "UNKNOWN_ERROR"),
                data.get("error_message", ""),
            )
            if status_error:
                return status_error

            results = []
            for item in data.get("results", []):
                results.append(
                    {
                        "formatted_address": item.get("formatted_address", ""),
                        "location": item.get("geometry", {}).get("location", {}),
                        "location_type": item.get("geometry", {}).get("location_type", ""),
                        "place_id": item.get("place_id", ""),
                        "types": item.get("types", []),
                        "address_components": item.get("address_components", []),
                    }
                )

            return {
                "query": address or components,
                "results": results,
                "total": len(results),
            }

        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {str(e)}"}
        except Exception as e:
            return {"error": f"Geocoding failed: {str(e)}"}

    # ── Tool 2: Reverse Geocoding ──────────────────────────────────────

    @mcp.tool()
    def maps_reverse_geocode(
        latitude: float,
        longitude: float,
        result_type: str = "",
        location_type: str = "",
        language: str = "",
    ) -> dict:
        """
        Convert geographic coordinates to a human-readable address.

        Use this when you have latitude/longitude and need the street address
        or place name at that location.

        Args:
            latitude: Latitude coordinate (e.g., 40.714224)
            longitude: Longitude coordinate (e.g., -73.961452)
            result_type: Filter by address type, pipe-separated
                (e.g., "street_address|route|locality")
            location_type: Filter by location precision, pipe-separated
                (e.g., "ROOFTOP|RANGE_INTERPOLATED|GEOMETRIC_CENTER|APPROXIMATE")
            language: Language code for results (e.g., "en", "es", "fr")

        Returns:
            Dict with reverse geocoding results including formatted_address,
            place_id, and address components
        """
        if not (-90 <= latitude <= 90):
            return {"error": "Latitude must be between -90 and 90"}
        if not (-180 <= longitude <= 180):
            return {"error": "Longitude must be between -180 and 180"}

        client = _make_client()
        if client is None:
            return _MISSING_KEY_ERROR

        params: dict[str, str] = {"latlng": f"{latitude},{longitude}"}
        if result_type:
            params["result_type"] = result_type
        if location_type:
            params["location_type"] = location_type
        if language:
            params["language"] = language

        try:
            response = client.get(_GEOCODE_URL, params)

            if response.status_code != 200:
                return {"error": f"HTTP {response.status_code}: {response.text[:200]}"}

            data = response.json()
            status_error = client.handle_status(
                data.get("status", "UNKNOWN_ERROR"),
                data.get("error_message", ""),
            )
            if status_error:
                return status_error

            results = []
            for item in data.get("results", []):
                results.append(
                    {
                        "formatted_address": item.get("formatted_address", ""),
                        "location": item.get("geometry", {}).get("location", {}),
                        "location_type": item.get("geometry", {}).get("location_type", ""),
                        "place_id": item.get("place_id", ""),
                        "types": item.get("types", []),
                        "address_components": item.get("address_components", []),
                    }
                )

            return {
                "coordinates": {"lat": latitude, "lng": longitude},
                "results": results,
                "total": len(results),
            }

        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {str(e)}"}
        except Exception as e:
            return {"error": f"Reverse geocoding failed: {str(e)}"}

    # ── Tool 3: Directions ─────────────────────────────────────────────

    @mcp.tool()
    def maps_directions(
        origin: str,
        destination: str,
        mode: Literal["driving", "walking", "bicycling", "transit"] = "driving",
        waypoints: str = "",
        alternatives: bool = False,
        units: Literal["metric", "imperial"] = "metric",
        avoid: str = "",
        departure_time: str = "",
        language: str = "",
    ) -> dict:
        """
        Calculate routes between two or more locations.

        Use this for route planning, navigation, and trip optimization.
        Supports driving, walking, bicycling, and transit modes.

        Args:
            origin: Starting point — address, place name, or "lat,lng"
                (e.g., "New York, NY" or "40.7128,-74.0060")
            destination: End point — address, place name, or "lat,lng"
            mode: Travel mode: "driving", "walking", "bicycling", or "transit"
            waypoints: Intermediate stops separated by pipes
                (e.g., "Philadelphia,PA|Baltimore,MD"). Prefix with "optimize:true|"
                to let Google optimize the order.
            alternatives: If true, request alternative routes
            units: Unit system: "metric" or "imperial"
            avoid: Route restrictions separated by pipes
                (e.g., "tolls|highways|ferries")
            departure_time: Unix timestamp or "now" for traffic-aware routing
                (driving mode only)
            language: Language code for instructions (e.g., "en", "es")

        Returns:
            Dict with route(s) including distance, duration, steps, and polyline
        """
        if not origin:
            return {"error": "Origin is required"}
        if not destination:
            return {"error": "Destination is required"}

        client = _make_client()
        if client is None:
            return _MISSING_KEY_ERROR

        params: dict[str, str] = {
            "origin": origin,
            "destination": destination,
            "mode": mode,
            "units": units,
        }
        if waypoints:
            params["waypoints"] = waypoints
        if alternatives:
            params["alternatives"] = "true"
        if avoid:
            params["avoid"] = avoid
        if departure_time:
            params["departure_time"] = departure_time
        if language:
            params["language"] = language

        try:
            response = client.get(_DIRECTIONS_URL, params)

            if response.status_code != 200:
                return {"error": f"HTTP {response.status_code}: {response.text[:200]}"}

            data = response.json()
            status_error = client.handle_status(
                data.get("status", "UNKNOWN_ERROR"),
                data.get("error_message", ""),
            )
            if status_error:
                return status_error

            routes = []
            for route in data.get("routes", []):
                legs = []
                for leg in route.get("legs", []):
                    steps = []
                    for step in leg.get("steps", []):
                        steps.append(
                            {
                                "instruction": step.get("html_instructions", ""),
                                "distance": step.get("distance", {}),
                                "duration": step.get("duration", {}),
                                "travel_mode": step.get("travel_mode", ""),
                            }
                        )

                    legs.append(
                        {
                            "start_address": leg.get("start_address", ""),
                            "end_address": leg.get("end_address", ""),
                            "distance": leg.get("distance", {}),
                            "duration": leg.get("duration", {}),
                            "duration_in_traffic": leg.get("duration_in_traffic"),
                            "steps": steps,
                        }
                    )

                routes.append(
                    {
                        "summary": route.get("summary", ""),
                        "legs": legs,
                        "overview_polyline": route.get("overview_polyline", {}).get("points", ""),
                        "warnings": route.get("warnings", []),
                        "waypoint_order": route.get("waypoint_order", []),
                    }
                )

            return {
                "origin": origin,
                "destination": destination,
                "mode": mode,
                "routes": routes,
                "total_routes": len(routes),
            }

        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {str(e)}"}
        except Exception as e:
            return {"error": f"Directions request failed: {str(e)}"}

    # ── Tool 4: Distance Matrix ────────────────────────────────────────

    @mcp.tool()
    def maps_distance_matrix(
        origins: str,
        destinations: str,
        mode: Literal["driving", "walking", "bicycling", "transit"] = "driving",
        units: Literal["metric", "imperial"] = "metric",
        avoid: str = "",
        departure_time: str = "",
        language: str = "",
    ) -> dict:
        """
        Calculate travel distance and time for multiple origins and destinations.

        Use this for fleet management, delivery optimization, or comparing travel
        times between many location pairs simultaneously.

        Args:
            origins: One or more starting points separated by pipes
                (e.g., "New York,NY|Boston,MA" or "40.71,-74.01|42.36,-71.06")
            destinations: One or more end points separated by pipes
                (e.g., "Philadelphia,PA|Washington,DC")
            mode: Travel mode: "driving", "walking", "bicycling", or "transit"
            units: Unit system: "metric" or "imperial"
            avoid: Route restrictions separated by pipes
                (e.g., "tolls|highways|ferries")
            departure_time: Unix timestamp or "now" for traffic-aware estimates
                (driving mode only)
            language: Language code for results

        Returns:
            Dict with distance/duration matrix for every origin-destination pair
        """
        if not origins:
            return {"error": "Origins is required"}
        if not destinations:
            return {"error": "Destinations is required"}

        client = _make_client()
        if client is None:
            return _MISSING_KEY_ERROR

        params: dict[str, str] = {
            "origins": origins,
            "destinations": destinations,
            "mode": mode,
            "units": units,
        }
        if avoid:
            params["avoid"] = avoid
        if departure_time:
            params["departure_time"] = departure_time
        if language:
            params["language"] = language

        try:
            response = client.get(_DISTANCE_MATRIX_URL, params)

            if response.status_code != 200:
                return {"error": f"HTTP {response.status_code}: {response.text[:200]}"}

            data = response.json()
            status_error = client.handle_status(
                data.get("status", "UNKNOWN_ERROR"),
                data.get("error_message", ""),
            )
            if status_error:
                return status_error

            rows = []
            for row in data.get("rows", []):
                elements = []
                for element in row.get("elements", []):
                    elem = {
                        "status": element.get("status", ""),
                        "distance": element.get("distance", {}),
                        "duration": element.get("duration", {}),
                    }
                    if "duration_in_traffic" in element:
                        elem["duration_in_traffic"] = element["duration_in_traffic"]
                    elements.append(elem)
                rows.append({"elements": elements})

            return {
                "origin_addresses": data.get("origin_addresses", []),
                "destination_addresses": data.get("destination_addresses", []),
                "rows": rows,
            }

        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {str(e)}"}
        except Exception as e:
            return {"error": f"Distance matrix request failed: {str(e)}"}

    # ── Tool 5: Place Details ──────────────────────────────────────────

    @mcp.tool()
    def maps_place_details(
        place_id: str,
        fields: str = (
            "name,formatted_address,geometry,rating,"
            "formatted_phone_number,website,opening_hours,"
            "reviews,price_level,types"
        ),
        language: str = "",
        reviews_sort: Literal["most_relevant", "newest"] = "most_relevant",
    ) -> dict:
        """
        Get detailed information about a specific place.

        Use this when you have a place_id (from geocoding or place search) and
        need detailed information like reviews, phone number, website, hours, etc.

        Args:
            place_id: The Google place ID (e.g., "ChIJN1t_tDeuEmsRUsoyG83frY4")
            fields: Comma-separated list of place data fields to return.
                Basic: name, formatted_address, geometry, place_id, types, photos,
                    rating, user_ratings_total, business_status
                Contact: formatted_phone_number, international_phone_number,
                    website, opening_hours, url
                Atmosphere: price_level, reviews, serves_breakfast, takeout, dine_in
            language: Language code for results (e.g., "en", "es")
            reviews_sort: Sort reviews by "most_relevant" or "newest"

        Returns:
            Dict with place details for the requested fields
        """
        if not place_id:
            return {"error": "place_id is required"}

        client = _make_client()
        if client is None:
            return _MISSING_KEY_ERROR

        params: dict[str, str] = {
            "place_id": place_id,
            "fields": fields,
            "reviews_sort": reviews_sort,
        }
        if language:
            params["language"] = language

        try:
            response = client.get(_PLACE_DETAILS_URL, params)

            if response.status_code != 200:
                return {"error": f"HTTP {response.status_code}: {response.text[:200]}"}

            data = response.json()
            status_error = client.handle_status(
                data.get("status", "UNKNOWN_ERROR"),
                data.get("error_message", ""),
            )
            if status_error:
                return status_error

            result = data.get("result", {})

            return {
                "place_id": place_id,
                "result": result,
            }

        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {str(e)}"}
        except Exception as e:
            return {"error": f"Place details request failed: {str(e)}"}

    # ── Tool 6: Place Search ───────────────────────────────────────────

    @mcp.tool()
    def maps_place_search(
        query: str,
        location: str = "",
        radius: int = 0,
        type: str = "",
        language: str = "",
        opennow: bool = False,
        minprice: int = -1,
        maxprice: int = -1,
        region: str = "",
        page_token: str = "",
    ) -> dict:
        """
        Search for places by text query (name, address, or type of place).

        Use this to find businesses, landmarks, or any point of interest.
        Combines Text Search functionality for broad queries.

        Args:
            query: Search text (e.g., "restaurants in Sydney", "123 Main St",
                "dentist near me")
            location: Center point for search as "latitude,longitude"
                (e.g., "33.8688,151.2093")
            radius: Search radius in meters (max 50000). Only used with location.
            type: Restrict to a place type (e.g., "restaurant", "hospital",
                "gas_station"). See Google's supported types list.
            language: Language code for results (e.g., "en", "es")
            opennow: If true, only return places that are currently open
            minprice: Minimum price level (0-4, where 0 is most affordable)
            maxprice: Maximum price level (0-4, where 4 is most expensive)
            region: Region bias as ccTLD code (e.g., "us", "au")
            page_token: Token from a previous response's next_page_token field
                to fetch the next page of results. When provided, all other
                parameters except query are ignored by the API.

        Returns:
            Dict with matching places including name, address, location,
            rating, and place_id. Includes next_page_token if more results exist.
        """
        if not query and not page_token:
            return {"error": "Query or page_token is required"}

        client = _make_client()
        if client is None:
            return _MISSING_KEY_ERROR

        params: dict[str, str] = {}
        if page_token:
            params["pagetoken"] = page_token
        if query:
            params["query"] = query
        if location:
            params["location"] = location
        if radius > 0:
            params["radius"] = str(min(radius, 50000))
        if type:
            params["type"] = type
        if language:
            params["language"] = language
        if opennow:
            params["opennow"] = "true"
        if 0 <= minprice <= 4:
            params["minprice"] = str(minprice)
        if 0 <= maxprice <= 4:
            params["maxprice"] = str(maxprice)
        if region:
            params["region"] = region

        try:
            response = client.get(_PLACE_SEARCH_URL, params)

            if response.status_code != 200:
                return {"error": f"HTTP {response.status_code}: {response.text[:200]}"}

            data = response.json()
            status_error = client.handle_status(
                data.get("status", "UNKNOWN_ERROR"),
                data.get("error_message", ""),
            )
            if status_error:
                return status_error

            results = []
            for item in data.get("results", []):
                place = {
                    "name": item.get("name", ""),
                    "formatted_address": item.get("formatted_address", ""),
                    "location": item.get("geometry", {}).get("location", {}),
                    "place_id": item.get("place_id", ""),
                    "types": item.get("types", []),
                    "rating": item.get("rating"),
                    "user_ratings_total": item.get("user_ratings_total"),
                    "price_level": item.get("price_level"),
                    "business_status": item.get("business_status", ""),
                }
                if "opening_hours" in item:
                    place["open_now"] = item["opening_hours"].get("open_now")
                results.append(place)

            response_data: dict = {
                "query": query,
                "results": results,
                "total": len(results),
            }
            if data.get("next_page_token"):
                response_data["next_page_token"] = data["next_page_token"]

            return response_data

        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {str(e)}"}
        except Exception as e:
            return {"error": f"Place search failed: {str(e)}"}
