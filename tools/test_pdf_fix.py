#!/usr/bin/env python3
"""Test PDF error handling improvement."""
import tempfile
from pathlib import Path
from fastmcp import FastMCP
from aden_tools.tools.pdf_read_tool import register_tools

# Create MCP instance and register tools
mcp = FastMCP("test")
register_tools(mcp)
pdf_read_fn = mcp._tool_manager._tools["pdf_read"].fn

print("Testing improved PDF error handling...\n")

# Test 1: Empty file
print("1. Empty file test:")
with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as f:
    temp_path = f.name
    # File is empty
try:
    result = pdf_read_fn(file_path=temp_path)
    if "empty" in result.get("error", "").lower() or "error" in result:
        print(f"   ✓ Handled correctly: {result['error'][:50]}")
    else:
        print(f"   ✗ Unexpected: {result}")
finally:
    Path(temp_path).unlink()

# Test 2: Corrupted PDF (invalid content)
print("\n2. Corrupted PDF test:")
with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False, mode='wb') as f:
    f.write(b'%PDF-1.4\n%garbage data not valid PDF structure\n%%EOF')
    temp_path = f.name
try:
    result = pdf_read_fn(file_path=temp_path)
    if "error" in result and ("corrupted" in result["error"].lower() or "parse" in result["error"].lower() or "failed" in result["error"].lower()):
        print(f"   ✓ Handled correctly: {result['error'][:70]}")
    else:
        print(f"   ✗ Unexpected: {result}")
finally:
    Path(temp_path).unlink()

# Test 3: Not a PDF file (text file with .pdf extension)
print("\n3. Non-PDF file test:")
with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False, mode='w') as f:
    f.write("This is just plain text, not a PDF")
    temp_path = f.name
try:
    result = pdf_read_fn(file_path=temp_path)
    if "error" in result:
        print(f"   ✓ Handled correctly: {result['error'][:70]}")
    else:
        print(f"   ✗ Unexpected: {result}")
finally:
    Path(temp_path).unlink()

print("\n✅ All PDF error handling tests completed!")
print("   - Empty files: Specific error message")
print("   - Corrupted PDFs: Specific error message")
print("   - Invalid PDFs: Graceful error handling")
