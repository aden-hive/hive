import asyncio
from aiohttp import web
from pathlib import Path

# Mock dependencies
class MockSessionManager:
    def get_session(self, session_id):
        return None  # Ensure we don't try to stop a mock live session

# Import the fixed route handlers
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "core")))
from framework.server.routes_sessions import handle_queen_messages, handle_session_events_history, handle_delete_history_session

async def test_endpoint(handler, session_id):
    request = type('Request', (), {'match_info': {'session_id': session_id}, 'app': {'manager': MockSessionManager()}})()
    try:
        response = await handler(request)
        print(f"[{handler.__name__}] Allowed {session_id}")
    except web.HTTPBadRequest:
        print(f"[{handler.__name__}] Blocked {session_id} - Path traversal prevented.")
    except Exception as e:
        print(f"[{handler.__name__}] Unexpected Error: {e}")

async def main():
    payloads = ["..%2Fescape", "..\\escape", "/", "\\", "..", "escape/../test"]
    handlers = [handle_queen_messages, handle_session_events_history, handle_delete_history_session]

    for handler in handlers:
        print(f"\nTesting {handler.__name__}...")
        for payload in payloads:
            await test_endpoint(handler, payload)

if __name__ == "__main__":
    asyncio.run(main())
