#!/usr/bin/env python3
"""
CI check: Ensure optional dependencies use lazy imports in tool files.

This script scans tool files in tools/src/aden_tools/tools/ and flags any
top-level imports of known optional packages. Optional dependencies should
use lazy imports (inside functions) with graceful error handling to prevent
the entire tool registration from crashing when the package isn't available.

See tools/pyproject.toml for optional-dependencies:
- openpyxl (excel)
- duckdb (sql)
- pytesseract (ocr)
- pillow (ocr)
- RestrictedPython (sandbox)
- google-cloud-bigquery (bigquery)

Pattern to follow (from excel_tool.py):
    def read_excel(...):
        try:
            from openpyxl import load_workbook
        except ImportError:
            return {"error": "openpyxl not installed. Install with: pip install tools[excel]"}
"""

import ast
import sys
from pathlib import Path

# Packages that MUST use lazy imports (from pyproject.toml optional-dependencies)
OPTIONAL_PACKAGES = {
    "openpyxl",  # excel
    "duckdb",  # sql
    "pytesseract",  # ocr
    "pillow",  # ocr (PIL)
    "RestrictedPython",  # sandbox
    "google.cloud.bigquery",  # bigquery (parent package)
    "google",  # google-cloud-*
    # Add others as needed
}

# Known patterns for google cloud packages
GOOGLE_PACKAGE_PREFIXES = ("google.cloud", "google.api", "google.auth")


def get_top_level_imports(filepath: Path) -> list[tuple[int, str]]:
    """
    Return list of (line_number, module_name) for top-level imports.

    Only checks direct children of the AST tree (not imports inside
    functions, classes, or other nested scopes).
    """
    with open(filepath) as f:
        try:
            tree = ast.parse(f.read(), filename=str(filepath))
        except SyntaxError as e:
            # Skip files with syntax errors - they'll be caught by other linters
            print(f"  Warning: Skipping {filepath} due to syntax error: {e}")
            return []

    imports = []
    for node in ast.iter_child_nodes(tree):  # Only top-level nodes
        if isinstance(node, ast.Import):
            for alias in node.names:
                module_name = alias.name.split(".")[0]
                imports.append((node.lineno, alias.name, module_name))
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                module_name = node.module.split(".")[0]
                imports.append((node.lineno, node.module, module_name))
    return imports


def is_optional_package(module: str, module_root: str) -> bool:
    """Check if a module is in the optional packages list."""
    # Check exact matches
    if module in OPTIONAL_PACKAGES or module_root in OPTIONAL_PACKAGES:
        return True

    # Check google cloud packages
    if module_root == "google":
        return module.startswith(GOOGLE_PACKAGE_PREFIXES)

    return False


def check_tool_files(tools_dir: Path) -> list[str]:
    """Check all tool files for forbidden top-level imports."""
    errors = []

    # Find all Python files in tools directory
    for tool_file in tools_dir.rglob("*.py"):
        # Skip test files and __init__.py
        if tool_file.name.startswith("test_") or tool_file.name == "__init__.py":
            continue

        for lineno, full_module, module_root in get_top_level_imports(tool_file):
            if is_optional_package(full_module, module_root):
                rel_path = tool_file.relative_to(Path.cwd())
                errors.append(
                    f"{rel_path}:{lineno}: Top-level import of optional package '{full_module}'. "
                    f"Use lazy import inside function with try/except ImportError."
                )

    return errors


def main() -> int:
    """Main entry point."""
    # Try tools/ directory first (project root), then fall back to relative path
    tools_dir = Path("tools/src/aden_tools/tools")
    if not tools_dir.exists():
        tools_dir = Path("../tools/src/aden_tools/tools")
    if not tools_dir.exists():
        tools_dir = Path.cwd() / "tools/src/aden_tools/tools"

    if not tools_dir.exists():
        print(f"Error: Directory not found: {tools_dir}")
        print("Run this script from the project root or tools/ directory")
        return 1

    print(f"Checking tool files in: {tools_dir}")
    print("-" * 60)

    errors = check_tool_files(tools_dir)

    if errors:
        print("❌ Optional dependency import violations found:\n")
        for error in errors:
            print(f"  {error}")
        print(f"\n{'=' * 60}")
        print("Fix: Move import inside function and wrap with try/except ImportError")
        print("  Example pattern from tools/src/aden_tools/tools/excel_tool/excel_tool.py:")
        print("")
        print("    def read_excel(...):")
        print("        try:")
        print("            from openpyxl import load_workbook")
        print("        except ImportError:")
        print("            return {'error': 'openpyxl not installed...'}")
        print("")
        print("  This ensures the tool loads even if the optional package is missing.")
        return 1
    else:
        print("✅ All tool files use lazy imports for optional dependencies")
        return 0


if __name__ == "__main__":
    sys.exit(main())
