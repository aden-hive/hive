#!/usr/bin/env python3
"""
How to Read PDFs with the MCP Server - 3 Methods
"""

import sys
import json
sys.path.insert(0, 'tools/src')
sys.path.insert(0, 'core')

# =============================================================
# METHOD 1: Direct Python Call (for testing/debugging)
# =============================================================
def method1_direct_call():
    """Call the pdf_read tool directly in Python."""
    print("\n" + "=" * 60)
    print("METHOD 1: Direct Python Call")
    print("=" * 60)
    
    from fastmcp import FastMCP
    from aden_tools.tools.pdf_read_tool import register_tools
    
    # Setup MCP and register the tool
    mcp = FastMCP("test")
    register_tools(mcp)
    
    # Get the tool function
    pdf_read = mcp._tool_manager._tools['pdf_read'].fn
    
    # Read the PDF (sample_document.pdf is in the same folder)
    import os
    script_dir = os.path.dirname(os.path.abspath(__file__))
    pdf_path = os.path.join(script_dir, 'sample_document.pdf')
    
    result = pdf_read(
        file_path=pdf_path,                # Path to PDF
        pages='all',                       # 'all', '1', '1-5', or '1,3,5'
        max_pages=100,                     # Limit for safety
        include_metadata=True              # Include PDF metadata
    )
    
    if 'error' in result:
        print(f"Error: {result['error']}")
    else:
        print(f"File: {result['name']}")
        print(f"Total Pages: {result['total_pages']}")
        print(f"Pages Extracted: {result['pages_extracted']}")
        print(f"Character Count: {result['char_count']}")
        print(f"\nContent Preview:\n{'-'*40}")
        print(result['content'][:500])
        if result.get('metadata'):
            print(f"\nMetadata: {result['metadata']}")


# =============================================================
# METHOD 2: HTTP Request to MCP Server (server must be running)
# =============================================================
def method2_http_request():
    """Call the pdf_read tool via HTTP to the running MCP server."""
    print("\n" + "=" * 60)
    print("METHOD 2: HTTP Request to MCP Server")
    print("=" * 60)
    
    import urllib.request
    import os
    
    # MCP uses JSON-RPC 2.0 protocol
    # The server must be running: python tools/mcp_server.py --port 4001
    
    # Get absolute path for the PDF
    pdf_path = os.path.abspath('sample_document.pdf')
    
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "pdf_read",
            "arguments": {
                "file_path": pdf_path,
                "pages": "all"
            }
        }
    }
    
    try:
        req = urllib.request.Request(
            'http://localhost:4001/mcp/v1',
            data=json.dumps(payload).encode('utf-8'),
            headers={'Content-Type': 'application/json'}
        )
        response = urllib.request.urlopen(req, timeout=10)
        result = json.loads(response.read().decode())
        print(f"Response: {json.dumps(result, indent=2)[:500]}...")
    except Exception as e:
        print(f"Note: HTTP method requires MCP server running on port 4001")
        print(f"Start with: python tools/mcp_server.py --port 4001")
        print(f"Error: {str(e)[:100]}")


# =============================================================
# METHOD 3: Using in an Agent Node
# =============================================================
def method3_agent_usage():
    """Show how an agent would use the pdf_read tool."""
    print("\n" + "=" * 60)
    print("METHOD 3: Usage in an Agent")
    print("=" * 60)
    
    print("""
When building a Hive agent, the pdf_read tool is available automatically.

Example agent.json node:
{
    "id": "read_document",
    "name": "Read PDF Document",
    "node_type": "llm_tool_use",
    "system_prompt": "Read the PDF and extract key information.",
    "tools": ["pdf_read"],
    "input_keys": ["pdf_path"],
    "output_keys": ["document_content", "summary"]
}

The LLM will automatically call pdf_read when it needs to read a PDF!
""")


# =============================================================
# MAIN
# =============================================================
if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("📄 Reading PDFs with MCP Server")
    print("=" * 60)
    
    # Run Method 1 (always works)
    method1_direct_call()
    
    # Run Method 2 (needs server running)
    method2_http_request()
    
    # Show Method 3 (documentation)
    method3_agent_usage()
    
    print("\n" + "=" * 60)
    print("✓ Done!")
    print("=" * 60)
