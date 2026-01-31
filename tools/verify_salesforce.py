#!/usr/bin/env python3
"""
Verify Salesforce tool component.
Run from repo root after:  cd tools && pip install -e ".[dev]"
  python verify_salesforce.py
Or from tools/:  pip install -e ".[dev]" && python verify_salesforce.py
"""

import sys

def main():
    errors = []

    # 1. Import module
    try:
        from aden_tools.tools.salesforce_tool.salesforce_tool import (
            _SalesforceClient,
            _validate_record_id,
            _sanitize_search_query,
            _build_search_soql,
            _sanitize_field_list,
            _VALID_SOBJECTS,
            register_tools,
        )
    except Exception as e:
        errors.append(f"Import failed: {e}")
        print("FAIL: Import failed. Run from tools/ with: pip install -e \".[dev]\"")
        sys.exit(1)

    # 2. Pure helpers
    if _validate_record_id("001000000000001") is not None:
        errors.append("_validate_record_id('001000000000001') should be None")
    if _validate_record_id("bad") is None:
        errors.append("_validate_record_id('bad') should return error")
    soql = _build_search_soql("Lead", ["Id", "Name"], "acme", 10)
    if "acme" not in soql or "LIMIT 10" not in soql:
        errors.append(f"_build_search_soql unexpected: {soql}")
    if _sanitize_field_list(["Id", "Name; DROP"]) != ["Id"]:
        errors.append("_sanitize_field_list should drop invalid field")

    # 3. Client
    client = _SalesforceClient("https://test.salesforce.com", "tok")
    if "v59.0" not in client._api_path:
        errors.append("Client _api_path should contain v59.0")
    if client._headers.get("Authorization") != "Bearer tok":
        errors.append("Client Authorization header wrong")

    # 4. Registration
    try:
        from fastmcp import FastMCP
        mcp = FastMCP("test")
        register_tools(mcp, credentials=None)
        if hasattr(mcp, "_tool_manager") and hasattr(mcp._tool_manager, "_tools"):
            names = [n for n in mcp._tool_manager._tools if "salesforce" in n]
            if len(names) != 16:
                errors.append(f"Expected 16 Salesforce tools, got {len(names)}")
        else:
            errors.append("Could not inspect registered tools")
    except Exception as e:
        errors.append(f"Registration failed: {e}")

    if errors:
        for e in errors:
            print("FAIL:", e)
        sys.exit(1)
    print("OK: Salesforce component checks passed (import, helpers, client, registration).")

if __name__ == "__main__":
    main()
