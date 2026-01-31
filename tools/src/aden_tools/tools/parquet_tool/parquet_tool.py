import importlib.util
from fasmcp import FastMCP
from ..file_system_toolkits.security import get_secure_path
import os

def register_tools(mcp: FastMCP):
    """Register Parquet Tool with the MCP server."""

    @mcp.tool()
    def secure_parquet_path(file_path: str) -> str:
        """ Get the secure path for the parquet file."""
        return get_secure_path(file_path, allowed_extensions=[".parquet"])

    def _connect_to_duckdb(file_path: str):
        """ Connect to DuckDB with optimized settings."""
        import duckdb
        conn = duckdb.connect(database=':memory:')
        conn.execute("SET enable_progress_bar=false;")
        conn.execute("SET memory_limit='1GB';")
        conn.execute("SET threads=2;")
        return conn

    @mcp.tool()
    def parquet_info(file_path: str, workspace_id: str, agent_id: str, session_id: str, columns_limit: int):
        """ The function to read the the parquet file and return its content as a string .

            The arugments are:
            - file_path: The path to the parquet file.
            - workspace_id: The workspace ID.
            - agent_id: The agent ID.
            - session_id: The session ID.
            - columns_limit: The maximum number of columns to read.

            The function returns: A string representation of the parquet file content.
        """
        if importlib.util.find_spec("duckdb") is None:
            return {"error": "duckdb is not installed. Please install it to use this tool."
                    "pip install duckdb  or  pip install tools[sql]"}
        try:
            file_path = secure_parquet_path(file_path)

            con = _connect_to_duckdb(file_path)
            rel = str(file_path)

            schema_query = con.execute(
                f"DESCRIBE SELECT * FROM read_parquet('{rel}');").fetchall()
            columns = [{"name": row[0]} for row in schema_query][:columns_limit]
            row_count = con.execute(
                f"SELECT COUNT(*) FROM read_parquet('{rel}');").fetchall()[0]
            row_count ={
                "path": rel,
                "columns": columns,
                "row_count": int(row_count)
            }
            return row_count
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool()
    def parquet_preview(
        file_path: str,
        workspace_id: str,
        agent_id: str,
        session_id: str,
        limit: int = 100,
        columns: list[str] | None = None,
        where: str | None = None,
    ):
        """ The function to describe the parquet file schema.

            Arugments:
            - file_path: The path to the parquet file.
            - workspace_id: The workspace ID.
            - agent_id: The agent ID.
            - session_id: The session ID.

            Returns:
            - A dictionary containing the schema of the parquet file.
        """
        try:
            parquet_file_path = secure_parquet_path(file_path)
            if not parquet_file_path.endswith(".parquet"):
                return {"error": "The file is not a parquet file."}
            elif not os.path.exists(parquet_file_path):
                return {"error": "The file does not exist."}
            conn = _connect_to_duckdb(parquet_file_path)
            rel = str(parquet_file_path)
            select_cols = "*"

            if columns:
                select_cols = ", ".join([f'"{c}"' for c in columns])

            where_clause = f"WHERE {where}" if where else ""

            query = f"""
                SELECT {select_cols}
                FROM read_parquet('{rel}')
                {where_clause}
                LIMIT {limit};
            """
            result = conn.execute(query).fetchdf()
            rows = dict(result.to_dict(orient="list"))
            out = {
                "path":rel,
                "limit": limit,
                "columns":list(result.columns),
                "rows": rows
            }
            return out
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool()
    def sample_parquet(
        file_path: str,
        n: int = 5,
        workspace_id: str = "",
        agent_id: str = "",
        session_id: str = "",
    ):
        """ The function to return n sample rows from the parquet file."""
        return {"error": "Not implemented yet."}

    @mcp.tool()
    def run_sql_on_parquet(
        file_path: str,
        query: str,
        workspace_id: str,
        agent_id: str,
        session_id: str,
    ):
        """ The function to run SQL query on the parquet file."""
        return {"error": "Not implemented yet."}


