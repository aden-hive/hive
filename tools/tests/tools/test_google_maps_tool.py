"""Tests for Google Maps tool with FastMCP."""

from unittest.mock import MagicMock, patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.google_maps_tool import register_tools

# ── Fixtures ───────────────────────────────────────────────────────────


@pytest.fixture
def mcp():
    """Create a FastMCP instance for testing."""
    return FastMCP("test-server")


@pytest.fixture
def maps_geocode_fn(mcp: FastMCP):
    """Register and return the maps_geocode tool function."""
    register_tools(mcp)
    return mcp._tool_manager._tools["maps_geocode"].fn


@pytest.fixture
def maps_reverse_geocode_fn(mcp: FastMCP):
    """Register and return the maps_reverse_geocode tool function."""
    register_tools(mcp)
    return mcp._tool_manager._tools["maps_reverse_geocode"].fn


@pytest.fixture
def maps_directions_fn(mcp: FastMCP):
    """Register and return the maps_directions tool function."""
    register_tools(mcp)
    return mcp._tool_manager._tools["maps_directions"].fn


@pytest.fixture
def maps_distance_matrix_fn(mcp: FastMCP):
    """Register and return the maps_distance_matrix tool function."""
    register_tools(mcp)
    return mcp._tool_manager._tools["maps_distance_matrix"].fn


@pytest.fixture
def maps_place_details_fn(mcp: FastMCP):
    """Register and return the maps_place_details tool function."""
    register_tools(mcp)
    return mcp._tool_manager._tools["maps_place_details"].fn


@pytest.fixture
def maps_place_search_fn(mcp: FastMCP):
    """Register and return the maps_place_search tool function."""
    register_tools(mcp)
    return mcp._tool_manager._tools["maps_place_search"].fn


# ── Credential Tests ──────────────────────────────────────────────────


class TestGoogleMapsCredentials:
    """Test credential handling for all Google Maps tools."""

    def test_geocode_no_credentials_returns_error(self, maps_geocode_fn, monkeypatch):
        """Geocode without credentials returns helpful error."""
        monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)

        result = maps_geocode_fn(address="1600 Amphitheatre Parkway")

        assert "error" in result
        assert "not configured" in result["error"]
        assert "help" in result

    def test_reverse_geocode_no_credentials_returns_error(
        self, maps_reverse_geocode_fn, monkeypatch
    ):
        """Reverse geocode without credentials returns helpful error."""
        monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)

        result = maps_reverse_geocode_fn(latitude=37.42, longitude=-122.08)

        assert "error" in result
        assert "not configured" in result["error"]

    def test_directions_no_credentials_returns_error(self, maps_directions_fn, monkeypatch):
        """Directions without credentials returns helpful error."""
        monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)

        result = maps_directions_fn(origin="NYC", destination="Boston")

        assert "error" in result
        assert "not configured" in result["error"]

    def test_distance_matrix_no_credentials_returns_error(
        self, maps_distance_matrix_fn, monkeypatch
    ):
        """Distance matrix without credentials returns helpful error."""
        monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)

        result = maps_distance_matrix_fn(origins="NYC", destinations="Boston")

        assert "error" in result
        assert "not configured" in result["error"]

    def test_place_details_no_credentials_returns_error(self, maps_place_details_fn, monkeypatch):
        """Place details without credentials returns helpful error."""
        monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)

        result = maps_place_details_fn(place_id="ChIJN1t_tDeuEmsRUsoyG83frY4")

        assert "error" in result
        assert "not configured" in result["error"]

    def test_place_search_no_credentials_returns_error(self, maps_place_search_fn, monkeypatch):
        """Place search without credentials returns helpful error."""
        monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)

        result = maps_place_search_fn(query="restaurants in Sydney")

        assert "error" in result
        assert "not configured" in result["error"]


# ── Input Validation Tests ────────────────────────────────────────────


class TestInputValidation:
    """Test input validation across tools."""

    def test_geocode_no_address_or_components(self, maps_geocode_fn, monkeypatch):
        """Geocode with neither address nor components returns error."""
        monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key")

        result = maps_geocode_fn(address="", components="")

        assert "error" in result
        assert "required" in result["error"].lower()

    def test_reverse_geocode_invalid_latitude(self, maps_reverse_geocode_fn, monkeypatch):
        """Latitude out of range returns error."""
        monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key")

        result = maps_reverse_geocode_fn(latitude=91.0, longitude=0.0)

        assert "error" in result
        assert "Latitude" in result["error"]

    def test_reverse_geocode_invalid_longitude(self, maps_reverse_geocode_fn, monkeypatch):
        """Longitude out of range returns error."""
        monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key")

        result = maps_reverse_geocode_fn(latitude=0.0, longitude=181.0)

        assert "error" in result
        assert "Longitude" in result["error"]

    def test_directions_no_origin(self, maps_directions_fn, monkeypatch):
        """Directions without origin returns error."""
        monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key")

        result = maps_directions_fn(origin="", destination="Boston")

        assert "error" in result
        assert "Origin" in result["error"]

    def test_directions_no_destination(self, maps_directions_fn, monkeypatch):
        """Directions without destination returns error."""
        monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key")

        result = maps_directions_fn(origin="NYC", destination="")

        assert "error" in result
        assert "Destination" in result["error"]

    def test_distance_matrix_no_origins(self, maps_distance_matrix_fn, monkeypatch):
        """Distance matrix without origins returns error."""
        monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key")

        result = maps_distance_matrix_fn(origins="", destinations="Boston")

        assert "error" in result
        assert "Origins" in result["error"]

    def test_distance_matrix_no_destinations(self, maps_distance_matrix_fn, monkeypatch):
        """Distance matrix without destinations returns error."""
        monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key")

        result = maps_distance_matrix_fn(origins="NYC", destinations="")

        assert "error" in result
        assert "Destinations" in result["error"]

    def test_place_details_no_place_id(self, maps_place_details_fn, monkeypatch):
        """Place details without place_id returns error."""
        monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key")

        result = maps_place_details_fn(place_id="")

        assert "error" in result
        assert "place_id" in result["error"]

    def test_place_search_no_query_or_page_token(self, maps_place_search_fn, monkeypatch):
        """Place search without query or page_token returns error."""
        monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key")

        result = maps_place_search_fn(query="")

        assert "error" in result
        assert "required" in result["error"].lower()


# ── Geocode Tests ─────────────────────────────────────────────────────


class TestMapsGeocode:
    """Tests for maps_geocode tool."""

    def test_geocode_success(self, maps_geocode_fn, monkeypatch):
        """Successful geocode returns formatted results."""
        monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key")

        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "status": "OK",
                "results": [
                    {
                        "formatted_address": "1600 Amphitheatre Pkwy, Mountain View, CA 94043, USA",
                        "geometry": {
                            "location": {"lat": 37.4224764, "lng": -122.0842499},
                            "location_type": "ROOFTOP",
                        },
                        "place_id": "ChIJ2eUgeAK6j4ARbn5u_wAGqWA",
                        "types": ["street_address"],
                        "address_components": [
                            {
                                "long_name": "1600",
                                "short_name": "1600",
                                "types": ["street_number"],
                            }
                        ],
                    }
                ],
            }
            mock_get.return_value = mock_response

            result = maps_geocode_fn(address="1600 Amphitheatre Parkway")

        assert result["total"] == 1
        assert result["results"][0]["formatted_address"].startswith("1600 Amphitheatre")
        assert result["results"][0]["location"]["lat"] == 37.4224764
        assert result["results"][0]["place_id"] == "ChIJ2eUgeAK6j4ARbn5u_wAGqWA"

    def test_geocode_zero_results(self, maps_geocode_fn, monkeypatch):
        """Geocode with no matches returns empty results."""
        monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key")

        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "status": "ZERO_RESULTS",
                "results": [],
            }
            mock_get.return_value = mock_response

            result = maps_geocode_fn(address="xyznonexistent12345")

        assert result["total"] == 0
        assert result["results"] == []

    def test_geocode_request_denied(self, maps_geocode_fn, monkeypatch):
        """API denied request returns error."""
        monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "invalid-key")

        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "status": "REQUEST_DENIED",
                "results": [],
                "error_message": "The provided API key is invalid.",
            }
            mock_get.return_value = mock_response

            result = maps_geocode_fn(address="test")

        assert "error" in result
        assert "denied" in result["error"].lower()

    def test_geocode_with_components_filter(self, maps_geocode_fn, monkeypatch):
        """Geocode with component filter passes params correctly."""
        monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key")

        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"status": "OK", "results": []}
            mock_get.return_value = mock_response

            maps_geocode_fn(
                address="Main Street",
                components="country:US",
                language="en",
            )

            call_kwargs = mock_get.call_args
            params = call_kwargs.kwargs.get("params", call_kwargs[1].get("params", {}))
            assert params["address"] == "Main Street"
            assert params["components"] == "country:US"
            assert params["language"] == "en"


# ── Reverse Geocode Tests ────────────────────────────────────────────


class TestMapsReverseGeocode:
    """Tests for maps_reverse_geocode tool."""

    def test_reverse_geocode_success(self, maps_reverse_geocode_fn, monkeypatch):
        """Successful reverse geocode returns address results."""
        monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key")

        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "status": "OK",
                "results": [
                    {
                        "formatted_address": "277 Bedford Ave, Brooklyn, NY 11211, USA",
                        "geometry": {
                            "location": {"lat": 40.714224, "lng": -73.961452},
                            "location_type": "ROOFTOP",
                        },
                        "place_id": "ChIJd8BlQ2BZwokRAFUEcm_qrcA",
                        "types": ["street_address"],
                        "address_components": [],
                    }
                ],
            }
            mock_get.return_value = mock_response

            result = maps_reverse_geocode_fn(latitude=40.714224, longitude=-73.961452)

        assert result["total"] == 1
        assert result["coordinates"]["lat"] == 40.714224
        assert "Bedford Ave" in result["results"][0]["formatted_address"]

    def test_reverse_geocode_passes_latlng_param(self, maps_reverse_geocode_fn, monkeypatch):
        """Reverse geocode sends correct latlng parameter."""
        monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key")

        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"status": "OK", "results": []}
            mock_get.return_value = mock_response

            maps_reverse_geocode_fn(latitude=37.42, longitude=-122.08, result_type="street_address")

            call_kwargs = mock_get.call_args
            params = call_kwargs.kwargs.get("params", call_kwargs[1].get("params", {}))
            assert params["latlng"] == "37.42,-122.08"
            assert params["result_type"] == "street_address"


# ── Directions Tests ──────────────────────────────────────────────────


class TestMapsDirections:
    """Tests for maps_directions tool."""

    def test_directions_success(self, maps_directions_fn, monkeypatch):
        """Successful directions returns route data."""
        monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key")

        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "status": "OK",
                "routes": [
                    {
                        "summary": "I-95 N",
                        "legs": [
                            {
                                "start_address": "New York, NY, USA",
                                "end_address": "Boston, MA, USA",
                                "distance": {"value": 346000, "text": "346 km"},
                                "duration": {"value": 14400, "text": "4 hours"},
                                "steps": [
                                    {
                                        "html_instructions": "Head north on I-95",
                                        "distance": {"value": 5000, "text": "5 km"},
                                        "duration": {"value": 300, "text": "5 mins"},
                                        "travel_mode": "DRIVING",
                                    }
                                ],
                            }
                        ],
                        "overview_polyline": {"points": "abc123"},
                        "warnings": [],
                        "waypoint_order": [],
                    }
                ],
            }
            mock_get.return_value = mock_response

            result = maps_directions_fn(origin="New York, NY", destination="Boston, MA")

        assert result["total_routes"] == 1
        assert result["routes"][0]["summary"] == "I-95 N"
        assert result["routes"][0]["legs"][0]["distance"]["text"] == "346 km"
        assert len(result["routes"][0]["legs"][0]["steps"]) == 1

    def test_directions_with_waypoints(self, maps_directions_fn, monkeypatch):
        """Directions with waypoints passes params correctly."""
        monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key")

        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"status": "OK", "routes": []}
            mock_get.return_value = mock_response

            maps_directions_fn(
                origin="NYC",
                destination="Boston",
                mode="driving",
                waypoints="Philadelphia,PA|Hartford,CT",
                alternatives=True,
                avoid="tolls|highways",
            )

            call_kwargs = mock_get.call_args
            params = call_kwargs.kwargs.get("params", call_kwargs[1].get("params", {}))
            assert params["waypoints"] == "Philadelphia,PA|Hartford,CT"
            assert params["alternatives"] == "true"
            assert params["avoid"] == "tolls|highways"
            assert params["mode"] == "driving"

    def test_directions_not_found(self, maps_directions_fn, monkeypatch):
        """Directions with invalid location returns error."""
        monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key")

        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "status": "NOT_FOUND",
                "routes": [],
                "geocoded_waypoints": [{"geocoder_status": "ZERO_RESULTS"}],
            }
            mock_get.return_value = mock_response

            result = maps_directions_fn(origin="xyznonexistent", destination="Boston")

        assert "error" in result
        assert "not be found" in result["error"].lower()


# ── Distance Matrix Tests ────────────────────────────────────────────


class TestMapsDistanceMatrix:
    """Tests for maps_distance_matrix tool."""

    def test_distance_matrix_success(self, maps_distance_matrix_fn, monkeypatch):
        """Successful distance matrix returns rows and elements."""
        monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key")

        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "status": "OK",
                "origin_addresses": ["New York, NY, USA"],
                "destination_addresses": [
                    "Philadelphia, PA, USA",
                    "Washington, DC, USA",
                ],
                "rows": [
                    {
                        "elements": [
                            {
                                "status": "OK",
                                "distance": {"value": 160000, "text": "160 km"},
                                "duration": {"value": 7200, "text": "2 hours"},
                            },
                            {
                                "status": "OK",
                                "distance": {"value": 360000, "text": "360 km"},
                                "duration": {"value": 14400, "text": "4 hours"},
                            },
                        ]
                    }
                ],
            }
            mock_get.return_value = mock_response

            result = maps_distance_matrix_fn(
                origins="New York,NY",
                destinations="Philadelphia,PA|Washington,DC",
            )

        assert len(result["origin_addresses"]) == 1
        assert len(result["destination_addresses"]) == 2
        assert len(result["rows"]) == 1
        assert len(result["rows"][0]["elements"]) == 2
        assert result["rows"][0]["elements"][0]["distance"]["text"] == "160 km"

    def test_distance_matrix_with_traffic(self, maps_distance_matrix_fn, monkeypatch):
        """Distance matrix with departure_time includes traffic data."""
        monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key")

        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "status": "OK",
                "origin_addresses": ["A"],
                "destination_addresses": ["B"],
                "rows": [
                    {
                        "elements": [
                            {
                                "status": "OK",
                                "distance": {"value": 50000, "text": "50 km"},
                                "duration": {"value": 3600, "text": "1 hour"},
                                "duration_in_traffic": {
                                    "value": 4200,
                                    "text": "1 hour 10 mins",
                                },
                            }
                        ]
                    }
                ],
            }
            mock_get.return_value = mock_response

            result = maps_distance_matrix_fn(origins="A", destinations="B", departure_time="now")

        elem = result["rows"][0]["elements"][0]
        assert "duration_in_traffic" in elem
        assert elem["duration_in_traffic"]["text"] == "1 hour 10 mins"

    def test_distance_matrix_passes_mode(self, maps_distance_matrix_fn, monkeypatch):
        """Distance matrix sends the correct mode parameter."""
        monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key")

        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "status": "OK",
                "origin_addresses": [],
                "destination_addresses": [],
                "rows": [],
            }
            mock_get.return_value = mock_response

            maps_distance_matrix_fn(origins="A", destinations="B", mode="walking", units="imperial")

            call_kwargs = mock_get.call_args
            params = call_kwargs.kwargs.get("params", call_kwargs[1].get("params", {}))
            assert params["mode"] == "walking"
            assert params["units"] == "imperial"


# ── Place Details Tests ──────────────────────────────────────────────


class TestMapsPlaceDetails:
    """Tests for maps_place_details tool."""

    def test_place_details_success(self, maps_place_details_fn, monkeypatch):
        """Successful place details returns result."""
        monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key")

        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "status": "OK",
                "result": {
                    "name": "Google Sydney",
                    "formatted_address": "48 Pirrama Rd, Pyrmont NSW 2009, Australia",
                    "rating": 4.2,
                    "formatted_phone_number": "(02) 9374 4000",
                    "website": "https://about.google/intl/ALL_au/",
                    "geometry": {"location": {"lat": -33.866489, "lng": 151.195677}},
                },
            }
            mock_get.return_value = mock_response

            result = maps_place_details_fn(place_id="ChIJN1t_tDeuEmsRUsoyG83frY4")

        assert result["place_id"] == "ChIJN1t_tDeuEmsRUsoyG83frY4"
        assert result["result"]["name"] == "Google Sydney"
        assert result["result"]["rating"] == 4.2

    def test_place_details_not_found(self, maps_place_details_fn, monkeypatch):
        """Invalid place_id returns not found error."""
        monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key")

        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "status": "NOT_FOUND",
                "html_attributions": [],
            }
            mock_get.return_value = mock_response

            result = maps_place_details_fn(place_id="invalid_id")

        assert "error" in result

    def test_place_details_custom_fields(self, maps_place_details_fn, monkeypatch):
        """Place details passes custom fields parameter."""
        monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key")

        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "status": "OK",
                "result": {"name": "Test"},
            }
            mock_get.return_value = mock_response

            maps_place_details_fn(
                place_id="ChIJ123",
                fields="name,rating",
                reviews_sort="newest",
            )

            call_kwargs = mock_get.call_args
            params = call_kwargs.kwargs.get("params", call_kwargs[1].get("params", {}))
            assert params["fields"] == "name,rating"
            assert params["reviews_sort"] == "newest"


# ── Place Search Tests ───────────────────────────────────────────────


class TestMapsPlaceSearch:
    """Tests for maps_place_search tool."""

    def test_place_search_success(self, maps_place_search_fn, monkeypatch):
        """Successful place search returns structured results."""
        monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key")

        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "status": "OK",
                "results": [
                    {
                        "name": "Opera Bar",
                        "formatted_address": "Bennelong Point, Sydney NSW 2000",
                        "geometry": {"location": {"lat": -33.8568, "lng": 151.2153}},
                        "place_id": "ChIJ123",
                        "types": ["bar", "restaurant"],
                        "rating": 4.1,
                        "user_ratings_total": 2345,
                        "price_level": 2,
                        "business_status": "OPERATIONAL",
                        "opening_hours": {"open_now": True},
                    },
                    {
                        "name": "The Rocks Cafe",
                        "formatted_address": "10 Argyle St, The Rocks NSW 2000",
                        "geometry": {"location": {"lat": -33.8590, "lng": 151.2080}},
                        "place_id": "ChIJ456",
                        "types": ["cafe"],
                        "rating": 4.5,
                        "user_ratings_total": 800,
                        "business_status": "OPERATIONAL",
                    },
                ],
                "next_page_token": "abc123token",
            }
            mock_get.return_value = mock_response

            result = maps_place_search_fn(query="restaurants in Sydney")

        assert result["total"] == 2
        assert result["results"][0]["name"] == "Opera Bar"
        assert result["results"][0]["rating"] == 4.1
        assert result["results"][0]["open_now"] is True
        assert result["results"][1]["name"] == "The Rocks Cafe"
        assert "open_now" not in result["results"][1]
        assert result["next_page_token"] == "abc123token"

    def test_place_search_with_location_and_type(self, maps_place_search_fn, monkeypatch):
        """Place search passes location, radius, and type params."""
        monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key")

        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "status": "OK",
                "results": [],
            }
            mock_get.return_value = mock_response

            maps_place_search_fn(
                query="pizza",
                location="40.71,-74.01",
                radius=5000,
                type="restaurant",
                opennow=True,
                minprice=1,
                maxprice=3,
            )

            call_kwargs = mock_get.call_args
            params = call_kwargs.kwargs.get("params", call_kwargs[1].get("params", {}))
            assert params["query"] == "pizza"
            assert params["location"] == "40.71,-74.01"
            assert params["radius"] == "5000"
            assert params["type"] == "restaurant"
            assert params["opennow"] == "true"
            assert params["minprice"] == "1"
            assert params["maxprice"] == "3"

    def test_place_search_zero_results(self, maps_place_search_fn, monkeypatch):
        """Place search with no matches returns empty results."""
        monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key")

        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "status": "ZERO_RESULTS",
                "results": [],
            }
            mock_get.return_value = mock_response

            result = maps_place_search_fn(query="xyznonexistent place")

        assert result["total"] == 0
        assert result["results"] == []

    def test_place_search_radius_capped(self, maps_place_search_fn, monkeypatch):
        """Place search caps radius at 50000."""
        monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key")

        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"status": "OK", "results": []}
            mock_get.return_value = mock_response

            maps_place_search_fn(query="test", location="0,0", radius=100000)

            call_kwargs = mock_get.call_args
            params = call_kwargs.kwargs.get("params", call_kwargs[1].get("params", {}))
            assert params["radius"] == "50000"

    def test_place_search_with_page_token(self, maps_place_search_fn, monkeypatch):
        """Place search with page_token sends pagetoken parameter."""
        monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key")

        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "status": "OK",
                "results": [
                    {
                        "name": "Page 2 Result",
                        "formatted_address": "123 Test St",
                        "geometry": {"location": {"lat": 0.0, "lng": 0.0}},
                        "place_id": "ChIJ789",
                        "types": ["restaurant"],
                        "business_status": "OPERATIONAL",
                    }
                ],
            }
            mock_get.return_value = mock_response

            result = maps_place_search_fn(query="restaurants", page_token="abc123token")

        assert result["total"] == 1
        assert result["results"][0]["name"] == "Page 2 Result"
        call_kwargs = mock_get.call_args
        params = call_kwargs.kwargs.get("params", call_kwargs[1].get("params", {}))
        assert params["pagetoken"] == "abc123token"

    def test_place_search_page_token_without_query(self, maps_place_search_fn, monkeypatch):
        """Place search with only page_token (no query) still works."""
        monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key")

        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "status": "OK",
                "results": [],
            }
            mock_get.return_value = mock_response

            result = maps_place_search_fn(query="", page_token="abc123token")

        assert "error" not in result
        call_kwargs = mock_get.call_args
        params = call_kwargs.kwargs.get("params", call_kwargs[1].get("params", {}))
        assert params["pagetoken"] == "abc123token"
        assert "query" not in params


# ── API Error Handling Tests ─────────────────────────────────────────


class TestAPIErrorHandling:
    """Test API-level error handling across tools."""

    def test_over_query_limit(self, maps_geocode_fn, monkeypatch):
        """Over query limit returns appropriate error."""
        monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key")

        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "status": "OVER_QUERY_LIMIT",
                "results": [],
            }
            mock_get.return_value = mock_response

            result = maps_geocode_fn(address="test")

        assert "error" in result
        assert "too many" in result["error"].lower()

    def test_http_error(self, maps_geocode_fn, monkeypatch):
        """Non-200 HTTP status returns error."""
        monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key")

        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 500
            mock_response.text = "Internal Server Error"
            mock_get.return_value = mock_response

            result = maps_geocode_fn(address="test")

        assert "error" in result
        assert "500" in result["error"]

    def test_timeout_error(self, maps_geocode_fn, monkeypatch):
        """Timeout returns appropriate error."""
        monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key")

        with patch("httpx.get") as mock_get:
            import httpx

            mock_get.side_effect = httpx.TimeoutException("Connection timed out")

            result = maps_geocode_fn(address="test")

        assert "error" in result
        assert "timed out" in result["error"].lower()

    def test_network_error(self, maps_geocode_fn, monkeypatch):
        """Network error returns appropriate error."""
        monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key")

        with patch("httpx.get") as mock_get:
            import httpx

            mock_get.side_effect = httpx.ConnectError("Connection refused")

            result = maps_geocode_fn(address="test")

        assert "error" in result
        assert "Network error" in result["error"]


# ── Credential Adapter Tests ─────────────────────────────────────────


class TestCredentialAdapter:
    """Test that tools work with CredentialStoreAdapter."""

    def test_geocode_with_credential_adapter(self, mcp):
        """Geocode works with CredentialStoreAdapter."""
        from aden_tools.credentials import CredentialStoreAdapter

        creds = CredentialStoreAdapter.for_testing({"google_maps": "test-key"})
        register_tools(mcp, credentials=creds)
        fn = mcp._tool_manager._tools["maps_geocode"].fn

        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "status": "OK",
                "results": [
                    {
                        "formatted_address": "Test Address",
                        "geometry": {
                            "location": {"lat": 0.0, "lng": 0.0},
                            "location_type": "APPROXIMATE",
                        },
                        "place_id": "test_id",
                        "types": [],
                        "address_components": [],
                    }
                ],
            }
            mock_get.return_value = mock_response

            result = fn(address="test")

        assert result["total"] == 1
        # Verify the API key was passed
        call_kwargs = mock_get.call_args
        params = call_kwargs.kwargs.get("params", call_kwargs[1].get("params", {}))
        assert params["key"] == "test-key"


# ── Tool Registration Tests ──────────────────────────────────────────


class TestToolRegistration:
    """Test that all tools are properly registered."""

    def test_all_tools_registered(self, mcp):
        """All six Google Maps tools are registered."""
        register_tools(mcp)

        expected_tools = [
            "maps_geocode",
            "maps_reverse_geocode",
            "maps_directions",
            "maps_distance_matrix",
            "maps_place_details",
            "maps_place_search",
        ]

        registered = set(mcp._tool_manager._tools.keys())
        for tool_name in expected_tools:
            assert tool_name in registered, f"{tool_name} not registered"
