# hive/tools/src/aden_tools/tools/__init__.py

from .ariba_agent import register_ariba_tools

def register_all_tools(mcp, credentials=None, include_unverified=False):
    # ... existing tool registrations ...
    register_ariba_tools(mcp)
