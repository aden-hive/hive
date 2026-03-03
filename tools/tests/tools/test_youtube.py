import pytest
from unittest.mock import patch, MagicMock
from aden_tools.tools.youtube_transcript_tool.tool import get_youtube_transcript
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import TranscriptsDisabled, NoTranscriptFound


def test_get_transcript_success():
    """Test successful transcript retrieval."""
    # Mock data
    mock_transcript = [
        {'text': 'Hello', 'start': 0},
        {'text': 'World', 'start': 1}
    ]
    
    # Mock YouTubeTranscriptApi.get_transcript using patch.object
    with patch.object(YouTubeTranscriptApi, 'get_transcript', return_value=mock_transcript, create=True) as mock_get:
        # Call the function with a dummy URL
        result = get_youtube_transcript('https://www.youtube.com/watch?v=dQw4w9WgXcQ')
        
        # Assert the result equals "Hello World"
        assert result == "Hello World"
        
        # Verify the API was called with the correct video ID
        mock_get.assert_called_once_with('dQw4w9WgXcQ')
    

def test_get_transcript_transcripts_disabled():
    """Test handling of TranscriptsDisabled exception."""
    # Mock YouTubeTranscriptApi.get_transcript to raise TranscriptsDisabled
    with patch.object(YouTubeTranscriptApi, 'get_transcript', side_effect=TranscriptsDisabled('video_id'), create=True) as mock_get:
        # Call the function
        result = get_youtube_transcript('https://www.youtube.com/watch?v=dQw4w9WgXcQ')
        
        # Assert the function returns an error string (does NOT raise the exception)
        assert result.startswith('Error:')
        assert 'disabled' in result.lower()


def test_get_transcript_no_transcript_found():
    """Test handling of NoTranscriptFound exception."""
    # Mock YouTubeTranscriptApi.get_transcript to raise NoTranscriptFound
    with patch.object(YouTubeTranscriptApi, 'get_transcript', side_effect=NoTranscriptFound('video_id', [], 'message'), create=True) as mock_get:
        # Call the function
        result = get_youtube_transcript('https://www.youtube.com/watch?v=dQw4w9WgXcQ')
        
        # Assert the function returns an error string
        assert result.startswith('Error:')
        assert 'No transcript available' in result



def test_invalid_url():
    """Test handling of invalid YouTube URLs."""
    # Call with an invalid URL
    result = get_youtube_transcript('https://not-youtube.com/video')
    
    # Assert error is returned
    assert result.startswith('Error:')
    assert 'Invalid' in result or 'invalid' in result


def test_generic_exception():
    """Test handling of generic exceptions."""
    # Mock to raise a generic exception
    with patch.object(YouTubeTranscriptApi, 'get_transcript', side_effect=Exception('Some unexpected error'), create=True) as mock_get:
        # Call the function
        result = get_youtube_transcript('https://www.youtube.com/watch?v=dQw4w9WgXcQ')
        
        # Assert the function returns an error string
        assert result.startswith('Error:')
