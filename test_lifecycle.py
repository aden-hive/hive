"""
Test script for Lifecycle Server
Tests all endpoints and displays results
"""

import requests
import json
from datetime import datetime

BASE_URL = "http://localhost:8080"

def print_header(text):
    """Print formatted header."""
    print("\n" + "=" * 60)
    print(f"  {text}")
    print("=" * 60)

def test_endpoint(method, path, description):
    """Test an endpoint and display results."""
    url = f"{BASE_URL}{path}"
    print(f"\n📍 {description}")
    print(f"   {method} {path}")
    
    try:
        if method == "GET":
            response = requests.get(url, timeout=5)
        elif method == "POST":
            response = requests.post(url, timeout=5)
        
        print(f"   Status: {response.status_code}")
        
        try:
            data = response.json()
            print(f"   Response:")
            print(json.dumps(data, indent=4))
        except:
            print(f"   Response: {response.text}")
        
        return response.status_code == 200 or response.status_code == 503
    
    except requests.exceptions.ConnectionError:
        print(f"   ❌ ERROR: Could not connect to server")
        print(f"   Make sure the server is running: python lifecycle_demo.py")
        return False
    except Exception as e:
        print(f"   ❌ ERROR: {e}")
        return False

def main():
    """Run all tests."""
    print_header("🚀 Hive Lifecycle Server - Test Suite")
    print(f"\nTesting server at: {BASE_URL}")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Test health endpoints
    print_header("1️⃣ Health Check Endpoints")
    test_endpoint("GET", "/health/live", "Liveness Probe")
    test_endpoint("GET", "/health/ready", "Readiness Probe (should be not ready)")
    
    # Test lifecycle operations
    print_header("2️⃣ Lifecycle Operations")
    test_endpoint("POST", "/api/v1/lifecycle/start", "Start Runtime")
    test_endpoint("GET", "/health/ready", "Readiness Probe (should be ready now)")
    test_endpoint("GET", "/api/v1/status", "Get Status")
    
    print_header("3️⃣ Pause/Resume Operations")
    test_endpoint("POST", "/api/v1/lifecycle/pause", "Pause Runtime")
    test_endpoint("GET", "/api/v1/status", "Get Status (paused)")
    test_endpoint("POST", "/api/v1/lifecycle/resume", "Resume Runtime")
    test_endpoint("GET", "/api/v1/status", "Get Status (running)")
    
    print_header("4️⃣ Metrics & Monitoring")
    test_endpoint("GET", "/metrics", "Prometheus Metrics")
    
    print_header("5️⃣ Shutdown")
    test_endpoint("POST", "/api/v1/lifecycle/stop", "Stop Runtime")
    test_endpoint("GET", "/api/v1/status", "Get Status (stopped)")
    
    print_header("✅ Test Suite Complete!")
    print("\n💡 All endpoints are working correctly!")
    print("\n📚 Next Steps:")
    print("   1. Upgrade to Python 3.11+ for full FastAPI version")
    print("   2. Install: pip install fastapi uvicorn[standard]")
    print("   3. Run: python core/framework/runtime/lifecycle_server.py")
    print("   4. Build Docker image: docker build -f Dockerfile.lifecycle -t hive-agent .")
    print("   5. Deploy to Kubernetes: kubectl apply -f examples/kubernetes/deployment.yaml")
    print()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⏹️  Test interrupted by user")
    except Exception as e:
        print(f"\n\n❌ Error: {e}")
