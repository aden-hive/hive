from fastmcp import FastMCP
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import TranscriptsDisabled, NoTranscriptFound
import re


def get_youtube_transcript(video_url: str) -> str:
    """
    Fetches the transcript for a YouTube video.
    
    Args:
        video_url: The URL of the YouTube video
        
    Returns:
        The transcript text as a single string, or an error message if unavailable
    """
    try:
        # Extract video ID from URL
        video_id = extract_video_id(video_url)
        if not video_id:
            return "Error: Invalid YouTube URL"
        
        # Get transcript
        transcript_list = YouTubeTranscriptApi.get_transcript(video_id)
        
        # Join transcript entries into a single string
        transcript_text = " ".join([entry['text'] for entry in transcript_list])
        
        return transcript_text
        
    except TranscriptsDisabled:
        return "Error: Transcripts are disabled for this video"
    except NoTranscriptFound:
        return "Error: No transcript available"
    except Exception as e:
        return f"Error: {str(e)}"


def extract_video_id(url: str) -> str:
    """
    Extracts the video ID from various YouTube URL formats.
    
    Supports:
    - https://www.youtube.com/watch?v=VIDEO_ID
    - https://youtu.be/VIDEO_ID
    - https://www.youtube.com/embed/VIDEO_ID
    - https://www.youtube.com/v/VIDEO_ID
    
    Args:
        url: YouTube video URL
        
    Returns:
        The video ID, or empty string if not found
    """
    patterns = [
        r'(?:youtube\.com\/watch\?v=|youtu\.be\/|youtube\.com\/embed\/|youtube\.com\/v\/)([a-zA-Z0-9_-]{11})',
        r'youtube\.com\/watch\?.*v=([a-zA-Z0-9_-]{11})'
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    
    return ""


def register(mcp: FastMCP):
    """Register the YouTube transcript tool with FastMCP."""
    mcp.tool()(get_youtube_transcript)

