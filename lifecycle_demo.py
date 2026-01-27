"""
Simple Lifecycle Server Demo - Compatible with Python 3.10+

This is a simplified version to test the concept without needing Python 3.11.
For production use, upgrade to Python 3.11+ and use the full lifecycle_server.py
"""

import asyncio
import json
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
import threading

class LifecycleHandler(BaseHTTPRequestHandler):
    """Simple HTTP handler for lifecycle endpoints."""
    
    # Shared state
    runtime_state = "stopped"
    started_at = None
    
    def do_GET(self):
        """Handle GET requests."""
        path = urlparse(self.path).path
        
        if path == "/health/live":
            self.send_json_response(200, {
                "status": "alive",
                "timestamp": datetime.utcnow().isoformat()
            })
        
        elif path == "/health/ready":
            if LifecycleHandler.runtime_state == "running":
                self.send_json_response(200, {
                    "status": "ready",
                    "timestamp": datetime.utcnow().isoformat()
                })
            else:
                self.send_json_response(503, {
                    "status": "not_ready",
                    "reason": f"Runtime is {LifecycleHandler.runtime_state}",
                    "timestamp": datetime.utcnow().isoformat()
                })
        
        elif path == "/api/v1/status":
            uptime = 0
            if LifecycleHandler.started_at:
                uptime = (datetime.utcnow() - LifecycleHandler.started_at).total_seconds()
            
            self.send_json_response(200, {
                "state": LifecycleHandler.runtime_state,
                "uptime_seconds": uptime,
                "started_at": LifecycleHandler.started_at.isoformat() if LifecycleHandler.started_at else None,
                "active_streams": 0,
                "total_executions": 0,
                "failed_executions": 0,
                "entry_points": ["main"],
                "health": {
                    "storage": "healthy",
                    "llm": "healthy",
                    "tools": "healthy"
                }
            })
        
        elif path == "/metrics":
            uptime = 0
            if LifecycleHandler.started_at:
                uptime = (datetime.utcnow() - LifecycleHandler.started_at).total_seconds()
            
            self.send_json_response(200, {
                "hive_runtime_uptime_seconds": uptime,
                "hive_runtime_state": 1 if LifecycleHandler.runtime_state == "running" else 0,
                "hive_active_streams": 0,
                "hive_total_requests": 0
            })
        
        else:
            self.send_json_response(404, {"error": "Not found"})
    
    def do_POST(self):
        """Handle POST requests."""
        path = urlparse(self.path).path
        
        if path == "/api/v1/lifecycle/start":
            LifecycleHandler.runtime_state = "running"
            LifecycleHandler.started_at = datetime.utcnow()
            self.send_json_response(200, {
                "success": True,
                "message": "Runtime started successfully",
                "state": "running",
                "timestamp": datetime.utcnow().isoformat()
            })
        
        elif path == "/api/v1/lifecycle/stop":
            LifecycleHandler.runtime_state = "stopped"
            self.send_json_response(200, {
                "success": True,
                "message": "Runtime stopped successfully",
                "state": "stopped",
                "timestamp": datetime.utcnow().isoformat()
            })
        
        elif path == "/api/v1/lifecycle/pause":
            LifecycleHandler.runtime_state = "paused"
            self.send_json_response(200, {
                "success": True,
                "message": "Runtime paused successfully",
                "state": "paused",
                "timestamp": datetime.utcnow().isoformat()
            })
        
        elif path == "/api/v1/lifecycle/resume":
            LifecycleHandler.runtime_state = "running"
            self.send_json_response(200, {
                "success": True,
                "message": "Runtime resumed successfully",
                "state": "running",
                "timestamp": datetime.utcnow().isoformat()
            })
        
        elif path == "/api/v1/lifecycle/restart":
            LifecycleHandler.runtime_state = "running"
            LifecycleHandler.started_at = datetime.utcnow()
            self.send_json_response(200, {
                "success": True,
                "message": "Runtime restarted successfully",
                "state": "running",
                "timestamp": datetime.utcnow().isoformat()
            })
        
        else:
            self.send_json_response(404, {"error": "Not found"})
    
    def send_json_response(self, status_code, data):
        """Send JSON response."""
        self.send_response(status_code)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data, indent=2).encode())
    
    def log_message(self, format, *args):
        """Custom log format."""
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {format % args}")


def run_server(port=8080):
    """Run the lifecycle server."""
    server_address = ('', port)
    httpd = HTTPServer(server_address, LifecycleHandler)
    
    print("=" * 60)
    print("🚀 Hive Lifecycle Server (Demo)")
    print("=" * 60)
    print(f"\n✅ Server started on http://localhost:{port}")
    print(f"\n📋 Available Endpoints:")
    print(f"\n   Health Checks:")
    print(f"   GET  http://localhost:{port}/health/live")
    print(f"   GET  http://localhost:{port}/health/ready")
    print(f"\n   Status:")
    print(f"   GET  http://localhost:{port}/api/v1/status")
    print(f"   GET  http://localhost:{port}/metrics")
    print(f"\n   Lifecycle Operations:")
    print(f"   POST http://localhost:{port}/api/v1/lifecycle/start")
    print(f"   POST http://localhost:{port}/api/v1/lifecycle/stop")
    print(f"   POST http://localhost:{port}/api/v1/lifecycle/pause")
    print(f"   POST http://localhost:{port}/api/v1/lifecycle/resume")
    print(f"   POST http://localhost:{port}/api/v1/lifecycle/restart")
    print(f"\n💡 Test with curl or browser:")
    print(f"   curl http://localhost:{port}/health/live")
    print(f"   curl -X POST http://localhost:{port}/api/v1/lifecycle/start")
    print(f"   curl http://localhost:{port}/api/v1/status")
    print(f"\n⏹️  Press Ctrl+C to stop the server")
    print("=" * 60)
    print()
    
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n\n🛑 Shutting down server...")
        httpd.shutdown()
        print("✅ Server stopped")


if __name__ == "__main__":
    import sys
    
    port = 8080
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            print(f"Invalid port: {sys.argv[1]}, using default 8080")
    
    run_server(port)
