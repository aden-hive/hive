"""
Excel Tool - Read and write Excel (.xlsx) files using pandas.

Uses pandas for robust Excel file manipulation, providing functionality
to read, write, and append data to Excel spreadsheets.
"""

from __future__ import annotations

import os
from typing import Any

from fastmcp import FastMCP

from ..file_system_toolkits.security import get_secure_path


def register_tools(mcp: FastMCP) -> None:
    """Register Excel tools with the MCP server."""

    def _check_openpyxl() -> dict | None:
        """
        Check if openpyxl is installed (required by pandas for Excel support).

        Returns:
            None if openpyxl is available, error dict otherwise.
        """
        try:
            import openpyxl  # noqa: F401

            return None
        except ImportError:
            return {
                "error": (
                    "openpyxl not installed (required for Excel support). "
                    "Install with: pip install openpyxl  or  pip install tools[excel]"
                )
            }

    def _validate_excel_extension(path: str) -> dict | None:
        """
        Validate that the file has an Excel extension.

        Args:
            path: File path to validate.

        Returns:
            None if valid, error dict otherwise.
        """
        valid_extensions = (".xlsx", ".xlsm", ".xltx", ".xltm")
        if not path.lower().endswith(valid_extensions):
            return {"error": f"File must have an Excel extension ({', '.join(valid_extensions)})"}
        return None

    @mcp.tool()
    def excel_read(
        path: str,
        workspace_id: str,
        agent_id: str,
        session_id: str,
        sheet_name: str | int | None = None,
        limit: int | None = None,
        offset: int = 0,
        include_empty_rows: bool = False,
    ) -> dict:
        """
        Read data from an Excel (.xlsx) file using pandas.

        Reads the specified sheet (or first sheet by default) and returns
        the data as a list of dictionaries where keys are column headers.

        Args:
            path: Path to the Excel file (relative to session sandbox)
            workspace_id: Workspace identifier
            agent_id: Agent identifier
            session_id: Session identifier
            sheet_name: Name or index of the sheet to read (None = first sheet)
            limit: Maximum number of rows to return (None = all rows)
            offset: Number of rows to skip from the beginning
            include_empty_rows: Whether to include rows with all NaN/empty values

        Returns:
            dict with success status, data, and metadata including:
            - columns: list of column names from the header row
            - rows: list of dictionaries representing each row
            - sheet_names: list of all available sheet names
            - active_sheet: name of the sheet that was read
        """
        import pandas as pd

        # Check if openpyxl is installed
        import_error = _check_openpyxl()
        if import_error:
            return import_error

        # Validate inputs
        if offset < 0 or (limit is not None and limit < 0):
            return {"error": "offset and limit must be non-negative"}

        try:
            secure_path = get_secure_path(path, workspace_id, agent_id, session_id)

            # Check if file exists
            if not os.path.exists(secure_path):
                return {"error": f"File not found: {path}"}

            # Validate extension
            ext_error = _validate_excel_extension(path)
            if ext_error:
                return ext_error

            # Get all sheet names first
            excel_file = pd.ExcelFile(secure_path, engine="openpyxl")
            sheet_names = excel_file.sheet_names

            # Determine which sheet to read
            if sheet_name is not None:
                if isinstance(sheet_name, str) and sheet_name not in sheet_names:
                    return {
                        "error": f"Sheet '{sheet_name}' not found. Available sheets: {sheet_names}"
                    }
                active_sheet = (
                    sheet_name if isinstance(sheet_name, str) else sheet_names[sheet_name]
                )
            else:
                active_sheet = sheet_names[0]

            # Read the sheet into a DataFrame
            df = pd.read_excel(
                excel_file,
                sheet_name=active_sheet,
                engine="openpyxl",
            )

            excel_file.close()

            # Get column names
            columns = df.columns.tolist()
            # Convert column names to strings (handle numeric column names)
            columns = [str(col) for col in columns]
            df.columns = columns

            # Store total rows before any filtering
            total_rows = len(df)

            # Filter out empty rows if configured
            if not include_empty_rows:
                df = df.dropna(how="all")

            # Apply offset
            if offset > 0:
                df = df.iloc[offset:]

            # Apply limit
            if limit is not None:
                df = df.head(limit)

            # Convert DataFrame to list of dicts with proper serialization
            rows = []
            for _, row in df.iterrows():
                row_dict = {}
                for col in columns:
                    value = row[col]
                    row_dict[col] = _serialize_value(value)
                rows.append(row_dict)

            return {
                "success": True,
                "path": path,
                "columns": columns,
                "column_count": len(columns),
                "rows": rows,
                "row_count": len(rows),
                "total_rows": total_rows,
                "sheet_names": sheet_names,
                "active_sheet": active_sheet,
                "offset": offset,
                "limit": limit,
            }

        except Exception as e:
            return {"error": f"Failed to read Excel file: {str(e)}"}

    @mcp.tool()
    def excel_write(
        path: str,
        workspace_id: str,
        agent_id: str,
        session_id: str,
        columns: list[str],
        rows: list[dict],
        sheet_name: str = "Sheet1",
    ) -> dict:
        """
        Write data to a new Excel (.xlsx) file using pandas.

        Creates a new Excel file with the specified columns and rows.
        If the file already exists, it will be overwritten.

        Args:
            path: Path to the Excel file (relative to session sandbox)
            workspace_id: Workspace identifier
            agent_id: Agent identifier
            session_id: Session identifier
            columns: List of column names for the header row
            rows: List of dictionaries, each representing a row of data
            sheet_name: Name of the sheet to create (default: "Sheet1")

        Returns:
            dict with success status and metadata
        """
        import pandas as pd

        # Check if openpyxl is installed
        import_error = _check_openpyxl()
        if import_error:
            return import_error

        try:
            secure_path = get_secure_path(path, workspace_id, agent_id, session_id)

            # Validate extension
            ext_error = _validate_excel_extension(path)
            if ext_error:
                return ext_error

            # Validate columns
            if not columns:
                return {"error": "columns cannot be empty"}

            # Create parent directories if needed
            parent_dir = os.path.dirname(secure_path)
            if parent_dir:
                os.makedirs(parent_dir, exist_ok=True)

            # Create DataFrame from rows
            # Filter rows to only include specified columns
            filtered_rows = []
            for row in rows:
                filtered_row = {col: row.get(col) for col in columns}
                filtered_rows.append(filtered_row)

            df = pd.DataFrame(filtered_rows, columns=columns)

            # Write to Excel
            df.to_excel(
                secure_path,
                sheet_name=sheet_name,
                index=False,
                engine="openpyxl",
            )

            return {
                "success": True,
                "path": path,
                "columns": columns,
                "column_count": len(columns),
                "rows_written": len(rows),
                "sheet_name": sheet_name,
            }

        except Exception as e:
            return {"error": f"Failed to write Excel file: {str(e)}"}

    @mcp.tool()
    def excel_append(
        path: str,
        workspace_id: str,
        agent_id: str,
        session_id: str,
        rows: list[dict],
        sheet_name: str | None = None,
    ) -> dict:
        """
        Append rows to an existing Excel (.xlsx) file using pandas.

        Adds new rows to the end of the specified sheet's data.
        The rows should have keys matching the existing column headers.

        Args:
            path: Path to the Excel file (relative to session sandbox)
            workspace_id: Workspace identifier
            agent_id: Agent identifier
            session_id: Session identifier
            rows: List of dictionaries to append, keys should match existing columns
            sheet_name: Name of the sheet to append to (None = first sheet)

        Returns:
            dict with success status and metadata
        """
        import pandas as pd

        # Check if openpyxl is installed
        import_error = _check_openpyxl()
        if import_error:
            return import_error

        try:
            secure_path = get_secure_path(path, workspace_id, agent_id, session_id)

            # Check if file exists
            if not os.path.exists(secure_path):
                return {"error": f"File not found: {path}. Use excel_write to create a new file."}

            # Validate extension
            ext_error = _validate_excel_extension(path)
            if ext_error:
                return ext_error

            # Validate rows
            if not rows:
                return {"error": "rows cannot be empty"}

            # Load existing file
            excel_file = pd.ExcelFile(secure_path, engine="openpyxl")
            sheet_names = excel_file.sheet_names

            # Determine which sheet to use
            if sheet_name is not None:
                if sheet_name not in sheet_names:
                    return {
                        "error": f"Sheet '{sheet_name}' not found. Available sheets: {sheet_names}"
                    }
                target_sheet = sheet_name
            else:
                target_sheet = sheet_names[0]

            # Read existing data
            existing_df = pd.read_excel(
                excel_file,
                sheet_name=target_sheet,
                engine="openpyxl",
            )
            excel_file.close()

            # Get existing columns
            columns = existing_df.columns.tolist()
            columns = [str(col) for col in columns]

            if not columns:
                return {"error": "Cannot append to file without headers"}

            # Filter new rows to only include existing columns
            filtered_rows = []
            for row in rows:
                filtered_row = {col: row.get(col) for col in columns}
                filtered_rows.append(filtered_row)

            # Create DataFrame for new rows
            new_df = pd.DataFrame(filtered_rows, columns=columns)

            # Concatenate with existing data
            combined_df = pd.concat([existing_df, new_df], ignore_index=True)

            # Write back to file
            combined_df.to_excel(
                secure_path,
                sheet_name=target_sheet,
                index=False,
                engine="openpyxl",
            )

            return {
                "success": True,
                "path": path,
                "rows_appended": len(rows),
                "total_rows": len(combined_df),
                "sheet_name": target_sheet,
            }

        except Exception as e:
            return {"error": f"Failed to append to Excel file: {str(e)}"}

    @mcp.tool()
    def excel_info(
        path: str,
        workspace_id: str,
        agent_id: str,
        session_id: str,
    ) -> dict:
        """
        Get metadata about an Excel file without reading all data.

        Returns information about the workbook including sheet names,
        column headers, row counts, and file size.

        Args:
            path: Path to the Excel file (relative to session sandbox)
            workspace_id: Workspace identifier
            agent_id: Agent identifier
            session_id: Session identifier

        Returns:
            dict with file metadata including sheets info
        """
        import pandas as pd

        # Check if openpyxl is installed
        import_error = _check_openpyxl()
        if import_error:
            return import_error

        try:
            secure_path = get_secure_path(path, workspace_id, agent_id, session_id)

            # Check if file exists
            if not os.path.exists(secure_path):
                return {"error": f"File not found: {path}"}

            # Validate extension
            ext_error = _validate_excel_extension(path)
            if ext_error:
                return ext_error

            # Get file size
            file_size = os.path.getsize(secure_path)

            # Load Excel file
            excel_file = pd.ExcelFile(secure_path, engine="openpyxl")
            sheet_names = excel_file.sheet_names

            # Get info for each sheet
            sheets_info = []
            for sheet in sheet_names:
                df = pd.read_excel(excel_file, sheet_name=sheet, engine="openpyxl")
                columns = [str(col) for col in df.columns.tolist()]

                sheets_info.append(
                    {
                        "name": sheet,
                        "columns": columns,
                        "column_count": len(columns),
                        "row_count": len(df),
                    }
                )

            excel_file.close()

            return {
                "success": True,
                "path": path,
                "sheet_count": len(sheet_names),
                "sheet_names": sheet_names,
                "sheets": sheets_info,
                "file_size_bytes": file_size,
            }

        except Exception as e:
            return {"error": f"Failed to get Excel info: {str(e)}"}

    @mcp.tool()
    def excel_list_sheets(
        path: str,
        workspace_id: str,
        agent_id: str,
        session_id: str,
    ) -> dict:
        """
        List all sheet names in an Excel file.

        Quick method to see available sheets without loading full metadata.

        Args:
            path: Path to the Excel file (relative to session sandbox)
            workspace_id: Workspace identifier
            agent_id: Agent identifier
            session_id: Session identifier

        Returns:
            dict with list of sheet names
        """
        import pandas as pd

        # Check if openpyxl is installed
        import_error = _check_openpyxl()
        if import_error:
            return import_error

        try:
            secure_path = get_secure_path(path, workspace_id, agent_id, session_id)

            # Check if file exists
            if not os.path.exists(secure_path):
                return {"error": f"File not found: {path}"}

            # Validate extension
            ext_error = _validate_excel_extension(path)
            if ext_error:
                return ext_error

            # Get sheet names using pandas ExcelFile
            excel_file = pd.ExcelFile(secure_path, engine="openpyxl")
            sheet_names = excel_file.sheet_names
            excel_file.close()

            return {
                "success": True,
                "path": path,
                "sheet_names": sheet_names,
                "sheet_count": len(sheet_names),
            }

        except Exception as e:
            return {"error": f"Failed to list sheets: {str(e)}"}


def _serialize_value(value: Any) -> Any:
    """
    Convert a value to JSON-serializable format.

    Handles NaN, datetime objects, and other pandas/Excel data types.

    Args:
        value: The value to serialize.

    Returns:
        A JSON-serializable value.
    """
    import pandas as pd

    # Handle NaN/None
    if pd.isna(value):
        return None

    # Handle datetime objects
    from datetime import date, datetime, time

    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, time):
        return value.isoformat()

    # Handle numpy types
    try:
        import numpy as np

        if isinstance(value, (np.integer, np.floating)):
            return value.item()  # Convert to Python native type
        if isinstance(value, np.ndarray):
            return value.tolist()
    except ImportError:
        pass

    # Return as-is for other types
    return value
