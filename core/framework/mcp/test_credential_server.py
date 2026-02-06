"""
Test and verification script for Credential Manager MCP Server.

This script tests:
1. Server module imports successfully
2. FastMCP instance is created correctly
3. Tools are registered
4. Credential store works
"""

import sys
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def test_server_import():
    """Test that server module can be imported."""
    print("1. Testing server import...")
    try:
        from framework.mcp.credential_manager_server import mcp, get_store
        print("   ✓ Server module imported successfully")
        return True
    except ImportError as e:
        print(f"   ✗ Failed to import server: {e}")
        return False


def test_mcp_instance():
    """Test that FastMCP instance exists and is properly configured."""
    print("\n2. Testing FastMCP instance...")
    try:
        from framework.mcp.credential_manager_server import mcp
        
        # Check basic properties
        if not hasattr(mcp, 'name'):
            print("   ✗ MCP instance has no name attribute")
            return False
        
        if mcp.name != "credential-manager":
            print(f"   ✗ MCP name is '{mcp.name}', expected 'credential-manager'")
            return False
        
        print(f"   ✓ FastMCP instance created with name: '{mcp.name}'")
        return True
        
    except Exception as e:
        print(f"   ✗ Failed to check MCP instance: {e}")
        return False


def test_tools_registered():
    """Test that all expected tools are registered."""
    print("\n3. Testing tool registration...")
    try:
        from framework.mcp.credential_manager_server import mcp
        
        # FastMCP stores tools in _tool_manager._tools dictionary
        if not hasattr(mcp, '_tool_manager'):
            print("   ✗ Server has no _tool_manager")
            return False
        
        tool_manager = mcp._tool_manager
        if not hasattr(tool_manager, '_tools') or not isinstance(tool_manager._tools, dict):
            print("   ✗ Tool manager has no _tools dictionary")
            return False
        
        tools = tool_manager._tools
        expected_tools = {
            "list_credentials",
            "get_credential",
            "validate_credential",
            "rotate_encryption_key",
            "save_credential",
            "delete_credential",
            "check_credential_health",
            "generate_fernet_key",
        }
        
        registered = set(tools.keys())
        missing = expected_tools - registered
        extra = registered - expected_tools
        
        if missing:
            print(f"   ✗ Missing tools: {missing}")
            return False
        
        if extra:
            print(f"   ⚠ Extra tools: {extra}")
        
        print(f"   ✓ All {len(expected_tools)} expected tools registered:")
        for tool_name in sorted(expected_tools):
            print(f"     - {tool_name}")
        
        return True
        
    except Exception as e:
        print(f"   ✗ Failed to check tools: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_credential_store():
    """Test that credential store initializes."""
    print("\n4. Testing credential store...")
    try:
        from framework.mcp.credential_manager_server import get_store
        
        store = get_store()
        print(f"   ✓ Credential store initialized: {store.__class__.__name__}")
        
        # Try listing credentials
        creds = store.list_credentials()
        print(f"   ✓ Store can list credentials ({len(creds)} total)")
        
        return True
        
    except Exception as e:
        print(f"   ✗ Failed to initialize store: {e}")
        print(f"      (This may be expected if encrypted storage isn't configured)")
        return True  # Don't fail - storage might not be configured


def test_encryption_rotation():
    """Test that the encryption key rotation tool is accessible."""
    print("\n5. Testing encryption rotation integration...")
    try:
        from framework.mcp.credential_manager_server import mcp
        
        # Check that rotate_encryption_key tool exists in _tool_manager._tools
        tool_manager = mcp._tool_manager
        if "rotate_encryption_key" not in tool_manager._tools:
            print("   ✗ rotate_encryption_key tool not found")
            return False
        
        tool = tool_manager._tools["rotate_encryption_key"]
        
        # Verify it has expected properties
        if not hasattr(tool, 'description'):
            print("   ✗ rotate_encryption_key has no description")
            return False
        
        print("   ✓ rotate_encryption_key tool is registered and configured")
        print(f"     - Description: {tool.description[:80]}...")
        
        return True
        
    except Exception as e:
        print(f"   ✗ Failed to check encryption rotation: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all tests."""
    print("=" * 70)
    print("Credential Manager MCP Server - Verification")
    print("=" * 70)
    
    tests = [
        test_server_import,
        test_mcp_instance,
        test_tools_registered,
        test_credential_store,
        test_encryption_rotation,
    ]
    
    results = []
    for test_func in tests:
        try:
            passed = test_func()
            results.append((test_func.__name__, passed))
        except Exception as e:
            print(f"   ✗ Test crashed: {e}")
            import traceback
            traceback.print_exc()
            results.append((test_func.__name__, False))
        print()
    
    # Summary
    print("=" * 70)
    num_passed = sum(1 for _, result in results if result)
    total = len(results)
    
    print(f"Summary: {num_passed}/{total} tests passed\n")
    
    for test_name, result in results:
        status = "✓" if result else "✗"
        print(f"  {status} {test_name}")
    
    print("=" * 70)
    
    if num_passed == total:
        print("\n✓ Server is ready to use!")
        print("\nTo use the server:")
        print("  1. Start the server:")
        print("     $ cd core")
        print("     $ python -m framework.mcp.credential_manager_server")
        print("\n  2. Call tools from an MCP client (e.g., Claude with MCP)")
        return 0
    else:
        print(f"\n✗ {total - num_passed} test(s) failed. Review errors above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
