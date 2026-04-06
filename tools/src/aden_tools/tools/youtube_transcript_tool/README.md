# YouTube Transcript Tool

Retrieve video transcripts and list available caption tracks via the `youtube-transcript-api` library.

## Tools

| Tool | Description |
|------|-------------|
| `youtube_get_transcript` | Get the transcript/captions for a YouTube video |
| `youtube_list_transcripts` | List all available transcript languages for a video |

## Setup

No API key required. The tool uses the `youtube-transcript-api` Python library and works with any public video that has captions enabled — no authentication needed.

Ensure the package is installed:

```bash
pip install youtube-transcript-api
```

> Only videos with captions enabled (auto-generated or manual) can be transcribed. Private or age-restricted videos may not be accessible.

## Usage Examples

### Get the English transcript of a video

```python
youtube_get_transcript(
    video_id="dQw4w9WgXcQ",
    language="en",
)
```

### Get transcript in another language

```python
youtube_get_transcript(
    video_id="dQw4w9WgXcQ",
    language="de",
)
```

### Get transcript preserving HTML formatting tags

```python
youtube_get_transcript(
    video_id="dQw4w9WgXcQ",
    language="en",
    preserve_formatting=True,
)
```

### List all available transcript languages

```python
youtube_list_transcripts(video_id="dQw4w9WgXcQ")
```

## Response Format

`youtube_get_transcript` returns:

```python
{
    "video_id": "dQw4w9WgXcQ",
    "language": "English",
    "language_code": "en",
    "is_generated": True,
    "snippet_count": 312,
    "snippets": [
        {"text": "Never gonna give you up", "start": 18.44, "duration": 1.72},
        ...
    ]
}
```

`youtube_list_transcripts` returns:

```python
{
    "video_id": "dQw4w9WgXcQ",
    "count": 3,
    "transcripts": [
        {"language": "English", "language_code": "en", "is_generated": True, "is_translatable": True},
        {"language": "German", "language_code": "de", "is_generated": False, "is_translatable": True},
    ]
}
```

## Finding the Video ID

The video ID is the `v=` parameter in a YouTube URL:

```
https://www.youtube.com/watch?v=dQw4w9WgXcQ
                                 ^^^^^^^^^^^
                                 This is the video ID
```

## Error Handling

All tools return error dicts on failure:

```python
{"error": "video_id is required"}
{"error": "TranscriptsDisabled: ..."}
{"error": "NoTranscriptFound: ..."}
{"error": "youtube-transcript-api package not installed. Run: pip install youtube-transcript-api"}
```
