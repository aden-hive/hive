"""
Quick test script for the Audit Trail Tool.
Run this to verify the tool works correctly.
"""
from fastmcp import FastMCP
from aden_tools.tools.audit_trail_tool import register_tools

# Create MCP server
mcp = FastMCP("test-server")

# Register audit trail tools
register_tools(mcp)

# Get the tool functions
record_fn = mcp._tool_manager._tools["record_decision"].fn
get_trail_fn = mcp._tool_manager._tools["get_audit_trail"].fn
export_fn = mcp._tool_manager._tools["export_audit_trail"].fn

print("Testing Audit Trail Tool\n")

# Test 1: Record a decision
print("1. Recording a decision...")
result = record_fn(
    agent_id="test_agent_001",
    decision_type="action",
    decision="Process customer support ticket",
    context="Ticket #12345 received",
    outcome="Ticket processed successfully",
    metadata={"ticket_id": "12345", "priority": "high"}
)
print(f"   Result: {result}\n")

# Test 2: Record another decision
print("2. Recording another decision...")
result = record_fn(
    agent_id="test_agent_001",
    decision_type="escalate",
    decision="Escalate to senior support",
    context="Customer requested manager",
    metadata={"ticket_id": "12345"}
)
print(f"   Result: {result}\n")

# Test 3: Get audit trail
print("3. Retrieving audit trail...")
trail = get_trail_fn(agent_id="test_agent_001")
print(f"   Total decisions: {trail.get('total_decisions', 0)}")
print(f"   Filtered count: {trail.get('filtered_count', 0)}")
print(f"   Decisions: {len(trail.get('decisions', []))}\n")

# Test 4: Export to JSON
print("4. Exporting to JSON...")
export_result = export_fn(
    agent_id="test_agent_001",
    output_format="json"
)
print(f"   Result: {export_result}\n")

print("All tests completed!")
print(f"\nAudit trail stored in: ~/.aden/audit_trails/")
print(f"Export file: {export_result.get('output_path', 'N/A')}")
