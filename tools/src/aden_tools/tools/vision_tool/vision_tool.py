"""
Google Cloud Vision Tool - Image analysis using Google Cloud Vision API.

Supports:
- Label detection (objects, scenes, activities)
- Text detection (OCR)
- Face detection (emotions)
- Object localization (bounding boxes)
- Logo detection
- Landmark detection
- Image properties (colors, crop hints)
- Web detection (similar images)
- Safe search (content moderation)

API Reference: https://cloud.google.com/vision/docs
"""

from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

VISION_API_URL = "https://vision.googleapis.com/v1/images:annotate"
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB


class _VisionClient:
    """Internal client for Google Cloud Vision API."""

    def __init__(self, api_key: str):
        self._api_key = api_key

    def _load_image(self, image_source: str) -> dict[str, Any] | dict[str, str]:
        """
        Load image from URL or local file.

        Returns:
            Image dict for API request, or error dict if failed.
        """
        # Check if URL
        if image_source.startswith(("http://", "https://")):
            return {"source": {"imageUri": image_source}}

        # Local file
        file_path = Path(image_source)
        if not file_path.exists():
            return {"error": f"File not found: {image_source}"}

        if not file_path.is_file():
            return {"error": f"Not a file: {image_source}"}

        # Check file size
        file_size = file_path.stat().st_size
        if file_size > MAX_FILE_SIZE:
            size_mb = file_size / (1024 * 1024)
            return {"error": f"File exceeds 10MB limit ({size_mb:.1f}MB)"}

        # Read and encode
        try:
            content = file_path.read_bytes()
            encoded = base64.b64encode(content).decode("utf-8")
            return {"content": encoded}
        except Exception as e:
            return {"error": f"Failed to read file: {str(e)}"}

    def _call_api(
        self, image_data: dict[str, Any], features: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Make request to Vision API."""
        try:
            response = httpx.post(
                VISION_API_URL,
                params={"key": self._api_key},
                json={"requests": [{"image": image_data, "features": features}]},
                timeout=30.0,
            )
            return self._handle_response(response)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {str(e)}"}

    def _handle_response(self, response: httpx.Response) -> dict[str, Any]:
        """Handle API response and errors."""
        if response.status_code == 400:
            return {"error": "Invalid request. Check image format and size."}
        if response.status_code == 401:
            return {"error": "Invalid API key"}
        if response.status_code == 403:
            return {"error": "API key not authorized. Enable Vision API in Google Cloud Console."}
        if response.status_code == 429:
            return {"error": "Rate limit exceeded. Try again later."}
        if response.status_code != 200:
            return {"error": f"Vision API error (HTTP {response.status_code})"}

        data = response.json()
        responses = data.get("responses", [])
        if not responses:
            return {"error": "Empty response from API"}

        result = responses[0]
        if "error" in result:
            return {"error": result["error"].get("message", "Unknown API error")}

        return result

    def detect_labels(self, image_source: str, max_results: int = 10) -> dict[str, Any]:
        """Detect labels in image."""
        image_data = self._load_image(image_source)
        if "error" in image_data:
            return image_data

        result = self._call_api(
            image_data, [{"type": "LABEL_DETECTION", "maxResults": max_results}]
        )
        if "error" in result:
            return result

        labels = [
            {"description": label["description"], "score": round(label["score"], 3)}
            for label in result.get("labelAnnotations", [])
        ]
        return {"labels": labels}

    def detect_text(self, image_source: str) -> dict[str, Any]:
        """Detect text in image (OCR)."""
        image_data = self._load_image(image_source)
        if "error" in image_data:
            return image_data

        result = self._call_api(image_data, [{"type": "TEXT_DETECTION"}])
        if "error" in result:
            return result

        annotations = result.get("textAnnotations", [])
        if not annotations:
            return {"text": "", "blocks": []}

        # First annotation is full text
        full_text = annotations[0].get("description", "")
        blocks = [
            {
                "text": ann.get("description", ""),
                "bounds": ann.get("boundingPoly", {}).get("vertices", []),
            }
            for ann in annotations[1:]
        ]
        return {"text": full_text, "blocks": blocks}

    def detect_faces(self, image_source: str, max_results: int = 10) -> dict[str, Any]:
        """Detect faces and emotions in image."""
        image_data = self._load_image(image_source)
        if "error" in image_data:
            return image_data

        result = self._call_api(image_data, [{"type": "FACE_DETECTION", "maxResults": max_results}])
        if "error" in result:
            return result

        faces = []
        for face in result.get("faceAnnotations", []):
            faces.append(
                {
                    "joy": face.get("joyLikelihood", "UNKNOWN"),
                    "sorrow": face.get("sorrowLikelihood", "UNKNOWN"),
                    "anger": face.get("angerLikelihood", "UNKNOWN"),
                    "surprise": face.get("surpriseLikelihood", "UNKNOWN"),
                    "confidence": round(face.get("detectionConfidence", 0), 3),
                    "bounds": face.get("boundingPoly", {}).get("vertices", []),
                }
            )
        return {"faces": faces}

    def localize_objects(self, image_source: str, max_results: int = 10) -> dict[str, Any]:
        """Detect objects with bounding boxes."""
        image_data = self._load_image(image_source)
        if "error" in image_data:
            return image_data

        result = self._call_api(
            image_data, [{"type": "OBJECT_LOCALIZATION", "maxResults": max_results}]
        )
        if "error" in result:
            return result

        objects = [
            {
                "name": obj.get("name", ""),
                "score": round(obj.get("score", 0), 3),
                "bounds": obj.get("boundingPoly", {}).get("normalizedVertices", []),
            }
            for obj in result.get("localizedObjectAnnotations", [])
        ]
        return {"objects": objects}

    def detect_logos(self, image_source: str, max_results: int = 5) -> dict[str, Any]:
        """Detect logos in image."""
        image_data = self._load_image(image_source)
        if "error" in image_data:
            return image_data

        result = self._call_api(image_data, [{"type": "LOGO_DETECTION", "maxResults": max_results}])
        if "error" in result:
            return result

        logos = [
            {
                "description": logo.get("description", ""),
                "score": round(logo.get("score", 0), 3),
            }
            for logo in result.get("logoAnnotations", [])
        ]
        return {"logos": logos}

    def detect_landmarks(self, image_source: str, max_results: int = 5) -> dict[str, Any]:
        """Detect landmarks in image."""
        image_data = self._load_image(image_source)
        if "error" in image_data:
            return image_data

        result = self._call_api(
            image_data, [{"type": "LANDMARK_DETECTION", "maxResults": max_results}]
        )
        if "error" in result:
            return result

        landmarks = []
        for lm in result.get("landmarkAnnotations", []):
            location = {}
            locations = lm.get("locations", [])
            if locations:
                lat_lng = locations[0].get("latLng", {})
                location = {
                    "latitude": lat_lng.get("latitude"),
                    "longitude": lat_lng.get("longitude"),
                }
            landmarks.append(
                {
                    "description": lm.get("description", ""),
                    "score": round(lm.get("score", 0), 3),
                    "location": location,
                }
            )
        return {"landmarks": landmarks}

    def get_image_properties(self, image_source: str) -> dict[str, Any]:
        """Get image properties (colors, crop hints)."""
        image_data = self._load_image(image_source)
        if "error" in image_data:
            return image_data

        result = self._call_api(
            image_data,
            [{"type": "IMAGE_PROPERTIES"}, {"type": "CROP_HINTS"}],
        )
        if "error" in result:
            return result

        # Extract colors
        colors = []
        color_info = result.get("imagePropertiesAnnotation", {})
        dominant_colors = color_info.get("dominantColors", {}).get("colors", [])
        for color in dominant_colors[:5]:
            rgb = color.get("color", {})
            colors.append(
                {
                    "red": int(rgb.get("red", 0)),
                    "green": int(rgb.get("green", 0)),
                    "blue": int(rgb.get("blue", 0)),
                    "score": round(color.get("score", 0), 3),
                    "pixel_fraction": round(color.get("pixelFraction", 0), 3),
                }
            )

        # Extract crop hints
        crop_hints = []
        hints_annotation = result.get("cropHintsAnnotation", {})
        for hint in hints_annotation.get("cropHints", []):
            crop_hints.append(
                {
                    "bounds": hint.get("boundingPoly", {}).get("vertices", []),
                    "confidence": round(hint.get("confidence", 0), 3),
                }
            )

        return {"colors": colors, "crop_hints": crop_hints}

    def web_detection(self, image_source: str) -> dict[str, Any]:
        """Find similar images and web references."""
        image_data = self._load_image(image_source)
        if "error" in image_data:
            return image_data

        result = self._call_api(image_data, [{"type": "WEB_DETECTION"}])
        if "error" in result:
            return result

        web = result.get("webDetection", {})

        web_entities = [
            {
                "description": entity.get("description", ""),
                "score": round(entity.get("score", 0), 3),
            }
            for entity in web.get("webEntities", [])[:10]
        ]

        similar_images = [img.get("url", "") for img in web.get("visuallySimilarImages", [])[:5]]

        pages_with_image = [
            {"url": page.get("url", ""), "title": page.get("pageTitle", "")}
            for page in web.get("pagesWithMatchingImages", [])[:5]
        ]

        return {
            "web_entities": web_entities,
            "similar_images": similar_images,
            "pages_with_image": pages_with_image,
        }

    def safe_search(self, image_source: str) -> dict[str, Any]:
        """Detect inappropriate content."""
        image_data = self._load_image(image_source)
        if "error" in image_data:
            return image_data

        result = self._call_api(image_data, [{"type": "SAFE_SEARCH_DETECTION"}])
        if "error" in result:
            return result

        safe = result.get("safeSearchAnnotation", {})
        return {
            "adult": safe.get("adult", "UNKNOWN"),
            "spoof": safe.get("spoof", "UNKNOWN"),
            "medical": safe.get("medical", "UNKNOWN"),
            "violence": safe.get("violence", "UNKNOWN"),
            "racy": safe.get("racy", "UNKNOWN"),
        }


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register Google Cloud Vision tools with the MCP server."""

    def _get_api_key() -> str | None:
        """Get API key from credentials or environment."""
        if credentials is not None:
            return credentials.get("google_vision")
        return os.getenv("GOOGLE_CLOUD_VISION_API_KEY")

    def _get_client() -> _VisionClient | dict[str, str]:
        """Get Vision client, or return error dict if no credentials."""
        api_key = _get_api_key()
        if not api_key:
            return {
                "error": "GOOGLE_CLOUD_VISION_API_KEY not configured",
                "help": "Get an API key at https://console.cloud.google.com/apis/credentials",
            }
        return _VisionClient(api_key)

    @mcp.tool()
    def vision_detect_labels(
        image_source: str,
        max_labels: int = 10,
    ) -> dict:
        """
        Detect labels (objects, scenes, activities) in an image.

        Args:
            image_source: URL or local file path to the image
            max_labels: Maximum number of labels to return (1-100, default 10)

        Returns:
            Dict with labels and confidence scores, or error dict
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        return client.detect_labels(image_source, min(max(1, max_labels), 100))

    @mcp.tool()
    def vision_detect_text(image_source: str) -> dict:
        """
        Extract text from an image (OCR).

        Args:
            image_source: URL or local file path to the image

        Returns:
            Dict with extracted text and text blocks with positions, or error dict
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        return client.detect_text(image_source)

    @mcp.tool()
    def vision_detect_faces(
        image_source: str,
        max_faces: int = 10,
    ) -> dict:
        """
        Detect faces and emotions in an image.

        Args:
            image_source: URL or local file path to the image
            max_faces: Maximum number of faces to detect (1-100, default 10)

        Returns:
            Dict with faces including emotions (joy, sorrow, anger, surprise), or error dict
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        return client.detect_faces(image_source, min(max(1, max_faces), 100))

    @mcp.tool()
    def vision_localize_objects(
        image_source: str,
        max_objects: int = 10,
    ) -> dict:
        """
        Detect objects with bounding box coordinates in an image.

        Args:
            image_source: URL or local file path to the image
            max_objects: Maximum number of objects to detect (1-100, default 10)

        Returns:
            Dict with objects including names, scores, and normalized bounding boxes, or error dict
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        return client.localize_objects(image_source, min(max(1, max_objects), 100))

    @mcp.tool()
    def vision_detect_logos(
        image_source: str,
        max_logos: int = 5,
    ) -> dict:
        """
        Detect brand logos in an image.

        Args:
            image_source: URL or local file path to the image
            max_logos: Maximum number of logos to detect (1-20, default 5)

        Returns:
            Dict with detected logos and confidence scores, or error dict
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        return client.detect_logos(image_source, min(max(1, max_logos), 20))

    @mcp.tool()
    def vision_detect_landmarks(
        image_source: str,
        max_landmarks: int = 5,
    ) -> dict:
        """
        Detect famous landmarks in an image.

        Args:
            image_source: URL or local file path to the image
            max_landmarks: Maximum number of landmarks to detect (1-20, default 5)

        Returns:
            Dict with landmarks including names, scores, and GPS coordinates, or error dict
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        return client.detect_landmarks(image_source, min(max(1, max_landmarks), 20))

    @mcp.tool()
    def vision_image_properties(image_source: str) -> dict:
        """
        Get image properties including dominant colors and crop hints.

        Args:
            image_source: URL or local file path to the image

        Returns:
            Dict with dominant colors (RGB, score) and crop hints, or error dict
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        return client.get_image_properties(image_source)

    @mcp.tool()
    def vision_web_detection(image_source: str) -> dict:
        """
        Find similar images and web references for an image.

        Args:
            image_source: URL or local file path to the image

        Returns:
            Dict with web entities, similar images, and pages containing the image
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        return client.web_detection(image_source)

    @mcp.tool()
    def vision_safe_search(image_source: str) -> dict:
        """
        Detect inappropriate content in an image.

        Checks for: adult, spoof, medical, violence, racy content.
        Each category returns a likelihood: VERY_UNLIKELY, UNLIKELY, POSSIBLE, LIKELY, VERY_LIKELY.

        Args:
            image_source: URL or local file path to the image

        Returns:
            Dict with likelihood ratings for each category, or error dict
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        return client.safe_search(image_source)
