# Google Cloud Vision Tool

Image analysis tool using Google Cloud Vision API.

## Features

| Tool | Description |
|------|-------------|
| `vision_detect_labels` | Identify objects, scenes, activities |
| `vision_detect_text` | Extract text from images (OCR) |
| `vision_detect_faces` | Detect faces and emotions |
| `vision_localize_objects` | Detect objects with bounding boxes |
| `vision_detect_logos` | Identify brand logos |
| `vision_detect_landmarks` | Identify famous places |
| `vision_image_properties` | Get dominant colors and crop hints |
| `vision_web_detection` | Find similar images online |
| `vision_safe_search` | Detect inappropriate content |

## Setup

### 1. Get API Key

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create a new project or select existing
3. Go to **APIs & Services > Library**
4. Search for "Cloud Vision API" and enable it
5. Go to **APIs & Services > Credentials**
6. Click **Create Credentials > API Key**
7. Copy the API key

### 2. Set Environment Variable

```bash
export GOOGLE_CLOUD_VISION_API_KEY=your_api_key
```

## Usage

### Label Detection

```python
result = vision_detect_labels(
    image_source="https://example.com/photo.jpg",
    max_labels=5
)
# {"labels": [{"description": "Dog", "score": 0.97}, ...]}
```

### Text Detection (OCR)

```python
result = vision_detect_text(image_source="/path/to/receipt.jpg")
# {"text": "Store: Amazon\nTotal: $49.99", "blocks": [...]}
```

### Face Detection

```python
result = vision_detect_faces(image_source="https://example.com/group.jpg")
# {"faces": [{"joy": "VERY_LIKELY", "anger": "VERY_UNLIKELY", ...}]}
```

### Object Localization

```python
result = vision_localize_objects(image_source="/path/to/image.jpg")
# {"objects": [{"name": "Cat", "score": 0.92, "bounds": [...]}]}
```

### Logo Detection

```python
result = vision_detect_logos(image_source="https://example.com/product.jpg")
# {"logos": [{"description": "Nike", "score": 0.95}]}
```

### Landmark Detection

```python
result = vision_detect_landmarks(image_source="/path/to/travel.jpg")
# {"landmarks": [{"description": "Eiffel Tower", "location": {"latitude": 48.85, "longitude": 2.29}}]}
```

### Image Properties

```python
result = vision_image_properties(image_source="https://example.com/art.jpg")
# {"colors": [{"red": 255, "green": 128, "blue": 0, "score": 0.5}], "crop_hints": [...]}
```

### Web Detection

```python
result = vision_web_detection(image_source="/path/to/image.jpg")
# {"web_entities": [...], "similar_images": [...], "pages_with_image": [...]}
```

### Safe Search

```python
result = vision_safe_search(image_source="https://example.com/upload.jpg")
# {"adult": "VERY_UNLIKELY", "violence": "VERY_UNLIKELY", "racy": "POSSIBLE", ...}
```

## Input Types

| Type | Example |
|------|---------|
| URL | `https://example.com/image.jpg` |
| Local file | `/path/to/image.jpg` |

**Supported formats:** JPEG, PNG, GIF, BMP, WEBP, ICO
**Max file size:** 10MB

## Error Handling

```python
# File not found
{"error": "File not found: /path/to/missing.jpg"}

# File too large
{"error": "File exceeds 10MB limit (12.5MB)"}

# Missing credentials
{"error": "GOOGLE_CLOUD_VISION_API_KEY not configured", "help": "..."}

# API errors
{"error": "Invalid API key"}
{"error": "Rate limit exceeded. Try again later."}
```

## Pricing

- **First 1000 images/month:** Free
- **After:** ~$1.50 per 1000 images

See [Cloud Vision Pricing](https://cloud.google.com/vision/pricing) for details.

## Likelihood Values

Face detection and safe search return likelihood values:

| Value | Meaning |
|-------|---------|
| `VERY_UNLIKELY` | Very unlikely |
| `UNLIKELY` | Unlikely |
| `POSSIBLE` | Possible |
| `LIKELY` | Likely |
| `VERY_LIKELY` | Very likely |
