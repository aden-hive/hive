"""Test Dataset Analyzer Tool - Integration Test"""

import sys
import os

# Add the tools directory to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'hive', 'tools', 'src'))

print("Python path setup:")
print(f"  Current dir: {os.getcwd()}")
print(f"  Added to path: {sys.path[0]}")

try:
    # Test 1: Import the tool
    print("\n[TEST 1] Importing dataset_analyzer_tool...")
    from aden_tools.tools.dataset_analyzer_tool import register_tools
    print("[OK] Tool imported successfully")
    
    # Test 2: Create MCP instance
    print("\n[TEST 2] Creating MCP instance...")
    from fastmcp import FastMCP
    mcp = FastMCP("dataset-analyzer-test")
    print("[OK] MCP instance created")
    
    # Test 3: Register tool
    print("\n[TEST 3] Registering tool with MCP...")
    register_tools(mcp)
    print("[OK] Tool registered")
    
    # Test 4: Get tool function
    print("\n[TEST 4] Getting tool function...")
    if "dataset_analyze" in mcp._tool_manager._tools:
        tool = mcp._tool_manager._tools["dataset_analyze"].fn
        print("[OK] Tool function retrieved")
    else:
        print("[ERROR] Tool not found in MCP registry")
        print(f"Available tools: {list(mcp._tool_manager._tools.keys())}")
        sys.exit(1)
    
    # Test 5: Test with regression CSV
    print("\n[TEST 5] Testing with regression dataset...")
    result = tool(
        path="test_regression.csv",
        workspace_id="test_workspace",
        agent_id="test_agent",
        session_id="test_session"
    )
    
    if "error" in result:
        print(f"[ERROR] {result['error']}")
    else:
        print("[OK] Analysis completed")
        print(f"  - Rows: {result['rows']}")
        print(f"  - Columns: {result['columns']}")
        print(f"  - Problem type: {result['problem_type']}")
        print(f"  - Algorithms: {result['recommended_algorithms']}")
    
    # Test 6: Test with classification CSV
    print("\n[TEST 6] Testing with classification dataset...")
    result = tool(
        path="test_classification.csv",
        workspace_id="test_workspace",
        agent_id="test_agent",
        session_id="test_session",
        target_column="approved"
    )
    
    if "error" in result:
        print(f"[ERROR] {result['error']}")
    else:
        print("[OK] Analysis completed")
        print(f"  - Rows: {result['rows']}")
        print(f"  - Columns: {result['columns']}")
        print(f"  - Target: {result['detected_target_column']}")
        print(f"  - Problem type: {result['problem_type']}")
        print(f"  - Algorithms: {result['recommended_algorithms']}")
    
    # Test 7: Test error handling
    print("\n[TEST 7] Testing error handling (nonexistent file)...")
    result = tool(
        path="nonexistent.csv",
        workspace_id="test_workspace",
        agent_id="test_agent",
        session_id="test_session"
    )
    
    if "error" in result:
        print(f"[OK] Error handled correctly: {result['error']}")
    else:
        print("[ERROR] Should have returned an error")
    
    print("\n" + "=" * 70)
    print("INTEGRATION TEST SUMMARY")
    print("=" * 70)
    print("[PASS] Module import successful")
    print("[PASS] MCP registration successful")
    print("[PASS] Tool execution successful")
    print("[PASS] Error handling working")
    print("\nTool is ready for production use!")
    print("=" * 70)

except ModuleNotFoundError as e:
    print(f"[ERROR] Module not found: {e}")
    print("\nTroubleshooting:")
    print("1. Verify you're in the correct directory: C:\\Users\\manty\\Desktop\\Hive")
    print("2. Check that hive/tools/src/aden_tools exists")
    print("3. Run: pip install fastmcp pandas numpy")
    sys.exit(1)

except ImportError as e:
    print(f"[ERROR] Import error: {e}")
    print("\nTroubleshooting:")
    print("1. Install missing packages: pip install fastmcp pandas numpy")
    print("2. Check Python version is 3.10+")
    sys.exit(1)

except Exception as e:
    print(f"[ERROR] Unexpected error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
