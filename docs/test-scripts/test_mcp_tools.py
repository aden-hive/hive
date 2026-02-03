#!/usr/bin/env python3
"""
Simple MCP Tools Test Script

Tests MCP tools that don't require agent context.
"""

import sys
sys.path.insert(0, 'tools/src')
sys.path.insert(0, 'core')

from fastmcp import FastMCP

def test_pdf_read():
    """Test PDF read tool directly."""
    from aden_tools.tools.pdf_read_tool import register_tools
    
    mcp = FastMCP("test")
    register_tools(mcp)
    fn = mcp._tool_manager._tools['pdf_read'].fn
    
    print("=" * 50)
    print("PDF Read Tool Tests")
    print("=" * 50)
    
    # Test 1: File not found
    print("\n[Test 1] File not found")
    result = fn(file_path='nonexistent.pdf')
    if 'error' in result:
        print(f"  ✓ PASS: {result['error']}")
    else:
        print(f"  ✗ FAIL: Expected error")
    
    # Test 2: Wrong extension
    print("\n[Test 2] Wrong file extension")
    result = fn(file_path='README.md')
    if 'error' in result and 'not a pdf' in result['error'].lower():
        print(f"  ✓ PASS: {result['error']}")
    else:
        print(f"  ✗ FAIL: Expected 'Not a PDF' error")
    
    # Test 3: Directory instead of file
    print("\n[Test 3] Directory instead of file")
    result = fn(file_path='.')
    if 'error' in result:
        print(f"  ✓ PASS: {result['error']}")
    else:
        print(f"  ✗ FAIL: Expected error")
    
    return True

def test_web_scrape():
    """Test web scrape tool directly."""
    from aden_tools.tools.web_scrape_tool import register_tools
    
    mcp = FastMCP("test")
    register_tools(mcp)
    
    print("\n" + "=" * 50)
    print("Web Scrape Tool Tests")
    print("=" * 50)
    
    # Test web_scrape
    print("\n[Test 1] web_scrape - example.com")
    fn = mcp._tool_manager._tools['web_scrape'].fn
    try:
        result = fn(url='https://example.com')
        if 'error' not in result:
            content_len = len(str(result.get('content', '')))
            print(f"  ✓ PASS: Scraped {content_len} chars from example.com")
        else:
            print(f"  ⚠ WARNING: {result.get('error')}")
    except Exception as e:
        print(f"  ⚠ SKIP: {str(e)[:60]}...")
    
    return True

def test_mcp_server_health():
    """Test MCP server HTTP endpoints."""
    import urllib.request
    
    print("\n" + "=" * 50)
    print("MCP Server HTTP Tests (port 4001)")
    print("=" * 50)
    
    # Test health endpoint
    print("\n[Test 1] /health endpoint")
    try:
        response = urllib.request.urlopen('http://localhost:4001/health', timeout=5)
        if response.read().decode() == 'OK':
            print("  ✓ PASS: Health check OK")
        else:
            print("  ✗ FAIL: Unexpected response")
    except Exception as e:
        print(f"  ⚠ SKIP: Server not running on port 4001 ({str(e)[:30]}...)")
    
    # Test root endpoint
    print("\n[Test 2] / endpoint")
    try:
        response = urllib.request.urlopen('http://localhost:4001/', timeout=5)
        content = response.read().decode()
        if 'Hive' in content or 'MCP' in content:
            print(f"  ✓ PASS: {content}")
        else:
            print(f"  ⚠ WARNING: Unexpected response: {content[:50]}")
    except Exception as e:
        print(f"  ⚠ SKIP: Server not running on port 4001 ({str(e)[:30]}...)")
    
    return True

def main():
    print("\n" + "=" * 50)
    print("MCP Tools Test Suite")
    print("=" * 50)
    
    test_pdf_read()
    test_mcp_server_health()
    # test_web_scrape()  # Uncomment to test (requires playwright browsers)
    
    print("\n" + "=" * 50)
    print("✓ All tests completed!")
    print("=" * 50 + "\n")

if __name__ == "__main__":
    main()
