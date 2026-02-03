"""Excel Tool - Read and manipulate Excel files."""

import os

import pandas as pd
from fastmcp import FastMCP

from ..file_system_toolkits.security import get_secure_path


def register_tools(mcp: FastMCP) -> None:
    """Register Excel tools with the MCP server."""

    @mcp.tool()
    def excel_read(
        path: str,
        workspace_id: str,
        agent_id: str,
        session_id: str,
        sheet_name: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> dict:
        """
        Read an Excel file and return its contents.

        Args:
            path: Path to the Excel file (relative to session sandbox)
            workspace_id: Workspace identifier
            agent_id: Agent identifier
            session_id: Session identifier
            sheet_name: Specific sheet name to read (None = first sheet)
            limit: Maximum number of rows to return (None = all rows)
            offset: Number of rows to skip from the beginning

        Returns:
            dict with success status, data, and metadata
        """
        if offset < 0 or (limit is not None and limit < 0):
            return {"error": "offset and limit must be non-negative"}

        try:
            secure_path = get_secure_path(path, workspace_id, agent_id, session_id)

            if not os.path.exists(secure_path):
                return {"error": f"File not found: {path}"}

            if not path.lower().endswith((".xlsx", ".xls")):
                return {"error": "File must have .xlsx or .xls extension"}

            # Read Excel file
            try:
                # Get available sheet names first
                with pd.ExcelFile(secure_path) as xls:
                    available_sheets = xls.sheet_names

                # Determine which sheet to read
                if sheet_name is None:
                    target_sheet = available_sheets[0]
                elif sheet_name not in available_sheets:
                    return {
                        "error": (
                            f"Sheet '{sheet_name}' not found. Available sheets: {available_sheets}"
                        )
                    }
                else:
                    target_sheet = sheet_name

                # Read the specific sheet
                df = pd.read_excel(secure_path, sheet_name=target_sheet)

                if df.empty:
                    return {
                        "success": True,
                        "path": path,
                        "sheet": target_sheet,
                        "available_sheets": available_sheets,
                        "columns": [],
                        "column_count": 0,
                        "rows": [],
                        "row_count": 0,
                        "total_rows": 0,
                        "offset": offset,
                        "limit": limit,
                    }

                # Get column names
                columns = df.columns.tolist()

                # Apply offset and limit
                if offset > 0:
                    df = df.iloc[offset:]
                if limit is not None:
                    df = df.head(limit)

                # Convert to list of dictionaries, handling NaN values
                rows = df.fillna("").to_dict("records")

                # Get total row count (before offset/limit)
                total_df = pd.read_excel(secure_path, sheet_name=target_sheet)
                total_rows = len(total_df)

                return {
                    "success": True,
                    "path": path,
                    "sheet": target_sheet,
                    "available_sheets": available_sheets,
                    "columns": columns,
                    "column_count": len(columns),
                    "rows": rows,
                    "row_count": len(rows),
                    "total_rows": total_rows,
                    "offset": offset,
                    "limit": limit,
                }

            except Exception as e:
                return {"error": f"Excel parsing error: {str(e)}"}

        except Exception as e:
            return {"error": f"Failed to read Excel: {str(e)}"}

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
        Write data to a new Excel file.

        Args:
            path: Path to the Excel file (relative to session sandbox)
            workspace_id: Workspace identifier
            agent_id: Agent identifier
            session_id: Session identifier
            columns: List of column names for the header
            rows: List of dictionaries, each representing a row
            sheet_name: Name for the Excel sheet

        Returns:
            dict with success status and metadata
        """
        try:
            secure_path = get_secure_path(path, workspace_id, agent_id, session_id)

            if not path.lower().endswith((".xlsx", ".xls")):
                return {"error": "File must have .xlsx or .xls extension"}

            if not columns:
                return {"error": "columns cannot be empty"}

            # Create parent directories if needed
            parent_dir = os.path.dirname(secure_path)
            if parent_dir:
                os.makedirs(parent_dir, exist_ok=True)

            # Filter rows to only include specified columns
            filtered_rows = []
            for row in rows:
                filtered_row = {col: row.get(col, "") for col in columns}
                filtered_rows.append(filtered_row)

            # Create DataFrame and write to Excel
            df = pd.DataFrame(filtered_rows, columns=columns)

            # Use .xlsx extension for better compatibility
            if path.lower().endswith(".xls"):
                # Convert to .xlsx for better support
                secure_path = secure_path.replace(".xls", ".xlsx")
                path = path.replace(".xls", ".xlsx")

            df.to_excel(secure_path, sheet_name=sheet_name, index=False)

            return {
                "success": True,
                "path": path,
                "sheet": sheet_name,
                "columns": columns,
                "column_count": len(columns),
                "rows_written": len(filtered_rows),
            }

        except Exception as e:
            return {"error": f"Failed to write Excel: {str(e)}"}

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
        Append rows to an existing Excel file.

        Args:
            path: Path to the Excel file (relative to session sandbox)
            workspace_id: Workspace identifier
            agent_id: Agent identifier
            session_id: Session identifier
            rows: List of dictionaries to append
            sheet_name: Sheet name to append to (None = first sheet)

        Returns:
            dict with success status and metadata
        """
        try:
            secure_path = get_secure_path(path, workspace_id, agent_id, session_id)

            if not os.path.exists(secure_path):
                return {"error": f"File not found: {path}"}

            if not path.lower().endswith((".xlsx", ".xls")):
                return {"error": "File must have .xlsx or .xls extension"}

            if not rows:
                return {"error": "rows cannot be empty"}

            # Read existing Excel file
            with pd.ExcelFile(secure_path) as xls:
                available_sheets = xls.sheet_names

                # Determine target sheet
                if sheet_name is None:
                    target_sheet = available_sheets[0]
                elif sheet_name not in available_sheets:
                    return {
                        "error": (
                            f"Sheet '{sheet_name}' not found. Available sheets: {available_sheets}"
                        )
                    }
                else:
                    target_sheet = sheet_name

                # Read existing data
                existing_df = pd.read_excel(secure_path, sheet_name=target_sheet)
                existing_columns = existing_df.columns.tolist()

                # Create new DataFrame from rows
                new_df = pd.DataFrame(rows)

                # Ensure new rows have same columns as existing
                for col in existing_columns:
                    if col not in new_df.columns:
                        new_df[col] = ""

                # Reorder columns to match existing
                new_df = new_df[existing_columns]

                # Append data
                combined_df = pd.concat([existing_df, new_df], ignore_index=True)

                # Write back to file (preserve other sheets if they exist)
                if len(available_sheets) == 1:
                    # Single sheet - simple write
                    combined_df.to_excel(secure_path, sheet_name=target_sheet, index=False)
                else:
                    # Multiple sheets - preserve others
                    with pd.ExcelWriter(secure_path, engine="openpyxl", mode="w") as writer:
                        for sheet in available_sheets:
                            if sheet == target_sheet:
                                combined_df.to_excel(writer, sheet_name=sheet, index=False)
                            else:
                                # Read and preserve other sheets
                                other_df = pd.read_excel(secure_path, sheet_name=sheet)
                                other_df.to_excel(writer, sheet_name=sheet, index=False)

            return {
                "success": True,
                "path": path,
                "sheet": target_sheet,
                "available_sheets": available_sheets,
                "columns": existing_columns,
                "rows_appended": len(rows),
                "total_rows": len(combined_df),
            }

        except Exception as e:
            return {"error": f"Failed to append to Excel: {str(e)}"}

    @mcp.tool()
    def excel_info(
        path: str,
        workspace_id: str,
        agent_id: str,
        session_id: str,
    ) -> dict:
        """
        Get information about an Excel file without reading all data.

        Args:
            path: Path to the Excel file (relative to session sandbox)
            workspace_id: Workspace identifier
            agent_id: Agent identifier
            session_id: Session identifier

        Returns:
            dict with file information
        """
        try:
            secure_path = get_secure_path(path, workspace_id, agent_id, session_id)

            if not os.path.exists(secure_path):
                return {"error": f"File not found: {path}"}

            if not path.lower().endswith((".xlsx", ".xls")):
                return {"error": "File must have .xlsx or .xls extension"}

            # Get file info
            file_stat = os.stat(secure_path)
            file_size = file_stat.st_size

            # Read Excel file info
            with pd.ExcelFile(secure_path) as xls:
                sheets_info = []
                for sheet_name in xls.sheet_names:
                    # Read just the header to get column info
                    df = pd.read_excel(secure_path, sheet_name=sheet_name, nrows=0)
                    columns = df.columns.tolist()

                    # Get row count
                    df_full = pd.read_excel(secure_path, sheet_name=sheet_name)
                    row_count = len(df_full)

                    sheets_info.append(
                        {
                            "name": sheet_name,
                            "columns": columns,
                            "column_count": len(columns),
                            "row_count": row_count,
                        }
                    )

            return {
                "success": True,
                "path": path,
                "file_size": file_size,
                "sheets": sheets_info,
                "sheet_count": len(sheets_info),
            }

        except Exception as e:
            return {"error": f"Failed to get Excel info: {str(e)}"}

    @mcp.tool()
    def excel_create_sheet(
        path: str,
        workspace_id: str,
        agent_id: str,
        session_id: str,
        sheet_name: str,
        columns: list[str],
        rows: list[dict] | None = None,
    ) -> dict:
        """
        Add a new sheet to an existing Excel file or create file if it doesn't exist.

        Args:
            path: Path to the Excel file (relative to session sandbox)
            workspace_id: Workspace identifier
            agent_id: Agent identifier
            session_id: Session identifier
            sheet_name: Name of the new sheet
            columns: List of column names for the header
            rows: Optional list of dictionaries for initial data

        Returns:
            dict with success status and metadata
        """
        try:
            secure_path = get_secure_path(path, workspace_id, agent_id, session_id)

            if not path.lower().endswith((".xlsx", ".xls")):
                return {"error": "File must have .xlsx or .xls extension"}

            if not columns:
                return {"error": "columns cannot be empty"}

            # Create parent directories if needed
            parent_dir = os.path.dirname(secure_path)
            if parent_dir:
                os.makedirs(parent_dir, exist_ok=True)

            # Prepare new sheet data
            if rows is None:
                rows = []

            # Filter rows to only include specified columns
            filtered_rows = []
            for row in rows:
                filtered_row = {col: row.get(col, "") for col in columns}
                filtered_rows.append(filtered_row)

            new_df = pd.DataFrame(filtered_rows, columns=columns)

            if os.path.exists(secure_path):
                # File exists - add new sheet
                with pd.ExcelFile(secure_path) as xls:
                    existing_sheets = xls.sheet_names

                    if sheet_name in existing_sheets:
                        return {"error": f"Sheet '{sheet_name}' already exists"}

                    # Read all existing sheets and add new one
                    with pd.ExcelWriter(
                        secure_path, engine="openpyxl", mode="a", if_sheet_exists="error"
                    ) as writer:
                        new_df.to_excel(writer, sheet_name=sheet_name, index=False)

                    return {
                        "success": True,
                        "path": path,
                        "sheet": sheet_name,
                        "columns": columns,
                        "rows_written": len(filtered_rows),
                        "existing_sheets": existing_sheets,
                    }
            else:
                # File doesn't exist - create new file with sheet
                new_df.to_excel(secure_path, sheet_name=sheet_name, index=False)

                return {
                    "success": True,
                    "path": path,
                    "sheet": sheet_name,
                    "columns": columns,
                    "rows_written": len(filtered_rows),
                    "file_created": True,
                }

        except Exception as e:
            return {"error": f"Failed to create sheet: {str(e)}"}
