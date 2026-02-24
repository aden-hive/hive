"""Tests for Google Cloud Vision tool."""

import base64
import os
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
from fastmcp import FastMCP

from aden_tools.tools.vision_tool import register_tools


@pytest.fixture
def mcp() -> FastMCP:
    """Create a fresh FastMCP instance for testing."""
    return FastMCP("test-server")


@pytest.fixture
def sample_image(tmp_path: Path) -> Path:
    """Create a small test image file."""
    # Create a minimal valid PNG (1x1 pixel)
    png_data = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
    )
    image_file = tmp_path / "test.png"
    image_file.write_bytes(png_data)
    return image_file


@pytest.fixture
def large_file(tmp_path: Path) -> Path:
    """Create a file larger than 10MB."""
    large_file = tmp_path / "large.png"
    large_file.write_bytes(b"x" * (11 * 1024 * 1024))  # 11MB
    return large_file


# --- Credential Tests ---


def test_missing_credentials(mcp: FastMCP):
    """Test error when API key not configured."""
    register_tools(mcp, credentials=None)
    tool_fn = mcp._tool_manager._tools["vision_detect_labels"].fn

    with patch.dict(os.environ, {}, clear=True):
        result = tool_fn(image_source="https://example.com/image.jpg")

    assert "error" in result
    assert "GOOGLE_CLOUD_VISION_API_KEY" in result["error"]
    assert "help" in result


def test_credentials_from_env(mcp: FastMCP):
    """Test that credentials are retrieved from environment."""
    register_tools(mcp, credentials=None)
    tool_fn = mcp._tool_manager._tools["vision_detect_labels"].fn

    mock_response = {"responses": [{"labelAnnotations": []}]}

    with patch.dict(os.environ, {"GOOGLE_CLOUD_VISION_API_KEY": "test-api-key"}):
        with patch("httpx.post") as mock_post:
            mock_post.return_value = httpx.Response(200, json=mock_response)
            result = tool_fn(image_source="https://example.com/image.jpg")

    assert "labels" in result


# --- Image Loading Tests ---


def test_file_not_found(mcp: FastMCP):
    """Test error when local file doesn't exist."""
    register_tools(mcp, credentials=None)
    tool_fn = mcp._tool_manager._tools["vision_detect_labels"].fn

    with patch.dict(os.environ, {"GOOGLE_CLOUD_VISION_API_KEY": "test-api-key"}):
        result = tool_fn(image_source="/nonexistent/path/image.jpg")

    assert "error" in result
    assert "File not found" in result["error"]


def test_file_too_large(mcp: FastMCP, large_file: Path):
    """Test error when file exceeds 10MB limit."""
    register_tools(mcp, credentials=None)
    tool_fn = mcp._tool_manager._tools["vision_detect_labels"].fn

    with patch.dict(os.environ, {"GOOGLE_CLOUD_VISION_API_KEY": "test-api-key"}):
        result = tool_fn(image_source=str(large_file))

    assert "error" in result
    assert "10MB" in result["error"]


def test_directory_not_file(mcp: FastMCP, tmp_path: Path):
    """Test error when path is a directory, not a file."""
    register_tools(mcp, credentials=None)
    tool_fn = mcp._tool_manager._tools["vision_detect_labels"].fn

    with patch.dict(os.environ, {"GOOGLE_CLOUD_VISION_API_KEY": "test-api-key"}):
        result = tool_fn(image_source=str(tmp_path))

    assert "error" in result
    assert "Not a file" in result["error"]


# --- API Response Tests ---


def test_detect_labels_success(mcp: FastMCP):
    """Test successful label detection."""
    register_tools(mcp, credentials=None)
    tool_fn = mcp._tool_manager._tools["vision_detect_labels"].fn

    mock_response = {
        "responses": [
            {
                "labelAnnotations": [
                    {"description": "Dog", "score": 0.97},
                    {"description": "Animal", "score": 0.95},
                ]
            }
        ]
    }

    with patch.dict(os.environ, {"GOOGLE_CLOUD_VISION_API_KEY": "test-api-key"}):
        with patch("httpx.post") as mock_post:
            mock_post.return_value = httpx.Response(200, json=mock_response)
            result = tool_fn(image_source="https://example.com/dog.jpg", max_labels=5)

    assert "labels" in result
    assert len(result["labels"]) == 2
    assert result["labels"][0]["description"] == "Dog"
    assert result["labels"][0]["score"] == 0.97


def test_detect_text_success(mcp: FastMCP):
    """Test successful text detection (OCR)."""
    register_tools(mcp, credentials=None)
    tool_fn = mcp._tool_manager._tools["vision_detect_text"].fn

    mock_response = {
        "responses": [
            {
                "textAnnotations": [
                    {"description": "Hello World\nLine 2"},
                    {"description": "Hello", "boundingPoly": {"vertices": [{"x": 0, "y": 0}]}},
                    {"description": "World", "boundingPoly": {"vertices": [{"x": 50, "y": 0}]}},
                ]
            }
        ]
    }

    with patch.dict(os.environ, {"GOOGLE_CLOUD_VISION_API_KEY": "test-api-key"}):
        with patch("httpx.post") as mock_post:
            mock_post.return_value = httpx.Response(200, json=mock_response)
            result = tool_fn(image_source="https://example.com/text.jpg")

    assert "text" in result
    assert result["text"] == "Hello World\nLine 2"
    assert "blocks" in result
    assert len(result["blocks"]) == 2


def test_detect_faces_success(mcp: FastMCP):
    """Test successful face detection."""
    register_tools(mcp, credentials=None)
    tool_fn = mcp._tool_manager._tools["vision_detect_faces"].fn

    mock_response = {
        "responses": [
            {
                "faceAnnotations": [
                    {
                        "joyLikelihood": "VERY_LIKELY",
                        "sorrowLikelihood": "VERY_UNLIKELY",
                        "angerLikelihood": "VERY_UNLIKELY",
                        "surpriseLikelihood": "UNLIKELY",
                        "detectionConfidence": 0.98,
                        "boundingPoly": {"vertices": [{"x": 10, "y": 10}]},
                    }
                ]
            }
        ]
    }

    with patch.dict(os.environ, {"GOOGLE_CLOUD_VISION_API_KEY": "test-api-key"}):
        with patch("httpx.post") as mock_post:
            mock_post.return_value = httpx.Response(200, json=mock_response)
            result = tool_fn(image_source="https://example.com/face.jpg")

    assert "faces" in result
    assert len(result["faces"]) == 1
    assert result["faces"][0]["joy"] == "VERY_LIKELY"
    assert result["faces"][0]["confidence"] == 0.98


def test_localize_objects_success(mcp: FastMCP):
    """Test successful object localization."""
    register_tools(mcp, credentials=None)
    tool_fn = mcp._tool_manager._tools["vision_localize_objects"].fn

    mock_response = {
        "responses": [
            {
                "localizedObjectAnnotations": [
                    {
                        "name": "Cat",
                        "score": 0.92,
                        "boundingPoly": {
                            "normalizedVertices": [
                                {"x": 0.1, "y": 0.2},
                                {"x": 0.9, "y": 0.8},
                            ]
                        },
                    }
                ]
            }
        ]
    }

    with patch.dict(os.environ, {"GOOGLE_CLOUD_VISION_API_KEY": "test-api-key"}):
        with patch("httpx.post") as mock_post:
            mock_post.return_value = httpx.Response(200, json=mock_response)
            result = tool_fn(image_source="https://example.com/cat.jpg")

    assert "objects" in result
    assert len(result["objects"]) == 1
    assert result["objects"][0]["name"] == "Cat"


def test_detect_logos_success(mcp: FastMCP):
    """Test successful logo detection."""
    register_tools(mcp, credentials=None)
    tool_fn = mcp._tool_manager._tools["vision_detect_logos"].fn

    mock_response = {
        "responses": [
            {
                "logoAnnotations": [
                    {"description": "Apple", "score": 0.95},
                    {"description": "Nike", "score": 0.88},
                ]
            }
        ]
    }

    with patch.dict(os.environ, {"GOOGLE_CLOUD_VISION_API_KEY": "test-api-key"}):
        with patch("httpx.post") as mock_post:
            mock_post.return_value = httpx.Response(200, json=mock_response)
            result = tool_fn(image_source="https://example.com/logos.jpg")

    assert "logos" in result
    assert len(result["logos"]) == 2
    assert result["logos"][0]["description"] == "Apple"


def test_detect_landmarks_success(mcp: FastMCP):
    """Test successful landmark detection."""
    register_tools(mcp, credentials=None)
    tool_fn = mcp._tool_manager._tools["vision_detect_landmarks"].fn

    mock_response = {
        "responses": [
            {
                "landmarkAnnotations": [
                    {
                        "description": "Eiffel Tower",
                        "score": 0.96,
                        "locations": [{"latLng": {"latitude": 48.8584, "longitude": 2.2945}}],
                    }
                ]
            }
        ]
    }

    with patch.dict(os.environ, {"GOOGLE_CLOUD_VISION_API_KEY": "test-api-key"}):
        with patch("httpx.post") as mock_post:
            mock_post.return_value = httpx.Response(200, json=mock_response)
            result = tool_fn(image_source="https://example.com/paris.jpg")

    assert "landmarks" in result
    assert len(result["landmarks"]) == 1
    assert result["landmarks"][0]["description"] == "Eiffel Tower"
    assert result["landmarks"][0]["location"]["latitude"] == 48.8584


def test_image_properties_success(mcp: FastMCP):
    """Test successful image properties extraction."""
    register_tools(mcp, credentials=None)
    tool_fn = mcp._tool_manager._tools["vision_image_properties"].fn

    mock_response = {
        "responses": [
            {
                "imagePropertiesAnnotation": {
                    "dominantColors": {
                        "colors": [
                            {
                                "color": {"red": 255, "green": 0, "blue": 0},
                                "score": 0.5,
                                "pixelFraction": 0.3,
                            }
                        ]
                    }
                },
                "cropHintsAnnotation": {
                    "cropHints": [{"boundingPoly": {"vertices": []}, "confidence": 0.8}]
                },
            }
        ]
    }

    with patch.dict(os.environ, {"GOOGLE_CLOUD_VISION_API_KEY": "test-api-key"}):
        with patch("httpx.post") as mock_post:
            mock_post.return_value = httpx.Response(200, json=mock_response)
            result = tool_fn(image_source="https://example.com/colorful.jpg")

    assert "colors" in result
    assert len(result["colors"]) == 1
    assert result["colors"][0]["red"] == 255
    assert "crop_hints" in result


def test_web_detection_success(mcp: FastMCP):
    """Test successful web detection."""
    register_tools(mcp, credentials=None)
    tool_fn = mcp._tool_manager._tools["vision_web_detection"].fn

    mock_response = {
        "responses": [
            {
                "webDetection": {
                    "webEntities": [{"description": "Sunset", "score": 0.9}],
                    "visuallySimilarImages": [{"url": "https://similar.com/1.jpg"}],
                    "pagesWithMatchingImages": [
                        {"url": "https://page.com", "pageTitle": "Sunset Photos"}
                    ],
                }
            }
        ]
    }

    with patch.dict(os.environ, {"GOOGLE_CLOUD_VISION_API_KEY": "test-api-key"}):
        with patch("httpx.post") as mock_post:
            mock_post.return_value = httpx.Response(200, json=mock_response)
            result = tool_fn(image_source="https://example.com/sunset.jpg")

    assert "web_entities" in result
    assert "similar_images" in result
    assert "pages_with_image" in result
    assert result["web_entities"][0]["description"] == "Sunset"


def test_safe_search_success(mcp: FastMCP):
    """Test successful safe search detection."""
    register_tools(mcp, credentials=None)
    tool_fn = mcp._tool_manager._tools["vision_safe_search"].fn

    mock_response = {
        "responses": [
            {
                "safeSearchAnnotation": {
                    "adult": "VERY_UNLIKELY",
                    "spoof": "UNLIKELY",
                    "medical": "VERY_UNLIKELY",
                    "violence": "VERY_UNLIKELY",
                    "racy": "POSSIBLE",
                }
            }
        ]
    }

    with patch.dict(os.environ, {"GOOGLE_CLOUD_VISION_API_KEY": "test-api-key"}):
        with patch("httpx.post") as mock_post:
            mock_post.return_value = httpx.Response(200, json=mock_response)
            result = tool_fn(image_source="https://example.com/photo.jpg")

    assert result["adult"] == "VERY_UNLIKELY"
    assert result["violence"] == "VERY_UNLIKELY"
    assert result["racy"] == "POSSIBLE"


# --- Local File Tests ---


def test_local_file_success(mcp: FastMCP, sample_image: Path):
    """Test successful processing of local file."""
    register_tools(mcp, credentials=None)
    tool_fn = mcp._tool_manager._tools["vision_detect_labels"].fn

    mock_response = {"responses": [{"labelAnnotations": [{"description": "Image", "score": 0.9}]}]}

    with patch.dict(os.environ, {"GOOGLE_CLOUD_VISION_API_KEY": "test-api-key"}):
        with patch("httpx.post") as mock_post:
            mock_post.return_value = httpx.Response(200, json=mock_response)
            result = tool_fn(image_source=str(sample_image))

    assert "labels" in result
    # Verify base64 content was sent
    call_args = mock_post.call_args
    request_json = call_args.kwargs["json"]
    assert "content" in request_json["requests"][0]["image"]


# --- Error Handling Tests ---


def test_api_error_401(mcp: FastMCP):
    """Test handling of invalid API key error."""
    register_tools(mcp, credentials=None)
    tool_fn = mcp._tool_manager._tools["vision_detect_labels"].fn

    with patch.dict(os.environ, {"GOOGLE_CLOUD_VISION_API_KEY": "test-api-key"}):
        with patch("httpx.post") as mock_post:
            mock_post.return_value = httpx.Response(401)
            result = tool_fn(image_source="https://example.com/image.jpg")

    assert "error" in result
    assert "Invalid API key" in result["error"]


def test_api_error_403(mcp: FastMCP):
    """Test handling of unauthorized API key error."""
    register_tools(mcp, credentials=None)
    tool_fn = mcp._tool_manager._tools["vision_detect_labels"].fn

    with patch.dict(os.environ, {"GOOGLE_CLOUD_VISION_API_KEY": "test-api-key"}):
        with patch("httpx.post") as mock_post:
            mock_post.return_value = httpx.Response(403)
            result = tool_fn(image_source="https://example.com/image.jpg")

    assert "error" in result
    assert "not authorized" in result["error"]


def test_api_error_429(mcp: FastMCP):
    """Test handling of rate limit error."""
    register_tools(mcp, credentials=None)
    tool_fn = mcp._tool_manager._tools["vision_detect_labels"].fn

    with patch.dict(os.environ, {"GOOGLE_CLOUD_VISION_API_KEY": "test-api-key"}):
        with patch("httpx.post") as mock_post:
            mock_post.return_value = httpx.Response(429)
            result = tool_fn(image_source="https://example.com/image.jpg")

    assert "error" in result
    assert "Rate limit" in result["error"]


def test_timeout_error(mcp: FastMCP):
    """Test handling of request timeout."""
    register_tools(mcp, credentials=None)
    tool_fn = mcp._tool_manager._tools["vision_detect_labels"].fn

    with patch.dict(os.environ, {"GOOGLE_CLOUD_VISION_API_KEY": "test-api-key"}):
        with patch("httpx.post") as mock_post:
            mock_post.side_effect = httpx.TimeoutException("Timeout")
            result = tool_fn(image_source="https://example.com/image.jpg")

    assert "error" in result
    assert "timed out" in result["error"]


def test_network_error(mcp: FastMCP):
    """Test handling of network error."""
    register_tools(mcp, credentials=None)
    tool_fn = mcp._tool_manager._tools["vision_detect_labels"].fn

    with patch.dict(os.environ, {"GOOGLE_CLOUD_VISION_API_KEY": "test-api-key"}):
        with patch("httpx.post") as mock_post:
            mock_post.side_effect = httpx.RequestError("Network error")
            result = tool_fn(image_source="https://example.com/image.jpg")

    assert "error" in result
    assert "Network error" in result["error"]


def test_empty_response(mcp: FastMCP):
    """Test handling of empty API response."""
    register_tools(mcp, credentials=None)
    tool_fn = mcp._tool_manager._tools["vision_detect_labels"].fn

    with patch.dict(os.environ, {"GOOGLE_CLOUD_VISION_API_KEY": "test-api-key"}):
        with patch("httpx.post") as mock_post:
            mock_post.return_value = httpx.Response(200, json={"responses": []})
            result = tool_fn(image_source="https://example.com/image.jpg")

    assert "error" in result
    assert "Empty response" in result["error"]


def test_api_error_in_response(mcp: FastMCP):
    """Test handling of error in API response body."""
    register_tools(mcp, credentials=None)
    tool_fn = mcp._tool_manager._tools["vision_detect_labels"].fn

    mock_response = {"responses": [{"error": {"message": "Image too small"}}]}

    with patch.dict(os.environ, {"GOOGLE_CLOUD_VISION_API_KEY": "test-api-key"}):
        with patch("httpx.post") as mock_post:
            mock_post.return_value = httpx.Response(200, json=mock_response)
            result = tool_fn(image_source="https://example.com/image.jpg")

    assert "error" in result
    assert "Image too small" in result["error"]


# --- Parameter Validation Tests ---


def test_max_labels_clamped(mcp: FastMCP):
    """Test that max_labels is clamped to valid range."""
    register_tools(mcp, credentials=None)
    tool_fn = mcp._tool_manager._tools["vision_detect_labels"].fn

    mock_response = {"responses": [{"labelAnnotations": []}]}

    with patch.dict(os.environ, {"GOOGLE_CLOUD_VISION_API_KEY": "test-api-key"}):
        with patch("httpx.post") as mock_post:
            mock_post.return_value = httpx.Response(200, json=mock_response)
            # Test with value > 100
            tool_fn(image_source="https://example.com/image.jpg", max_labels=200)

    # Verify maxResults was clamped to 100
    call_args = mock_post.call_args
    features = call_args.kwargs["json"]["requests"][0]["features"]
    assert features[0]["maxResults"] == 100


def test_detect_text_no_text_found(mcp: FastMCP):
    """Test text detection when no text is found."""
    register_tools(mcp, credentials=None)
    tool_fn = mcp._tool_manager._tools["vision_detect_text"].fn

    mock_response = {"responses": [{"textAnnotations": []}]}

    with patch.dict(os.environ, {"GOOGLE_CLOUD_VISION_API_KEY": "test-api-key"}):
        with patch("httpx.post") as mock_post:
            mock_post.return_value = httpx.Response(200, json=mock_response)
            result = tool_fn(image_source="https://example.com/image.jpg")

    assert result["text"] == ""
    assert result["blocks"] == []
