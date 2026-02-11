"""
Snowflake Data Cloud Integration.
"""
import time
import os
import base64
import hashlib
from typing import Optional, Dict, Any, List
import httpx
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
from fastmcp import FastMCP

class SnowflakeClient:
    def __init__(self, account: str, user: str, private_key: str):
        # Account identifier is often case-insensitive, but for JWT claim matching,
        # usually UPPERCASE works best with Snowflake unless quoted identifiers are used.
        self.account = account.upper()
        self.user = user.upper()
        self.private_key_pem = private_key
        self._token = None
        self._token_exp = 0

    def _generate_jwt(self) -> str:
        """Generate JWT token for Snowflake Key-Pair Authentication."""
        now = time.time()
        # specific buffer duration to refresh token before it expires
        if self._token and now < self._token_exp - 60:
            return self._token
            
        # Ensure private key is available
        if not self.private_key_pem:
             raise ValueError("Missing Private Key")

        if isinstance(self.private_key_pem, str):
            # Ensure it's bytes for load_pem_private_key
            key_bytes = self.private_key_pem.encode('utf-8')
        else:
            key_bytes = self.private_key_pem

        # Load private key
        try:
            private_key = serialization.load_pem_private_key(
                key_bytes,
                password=None,
                backend=default_backend()
            )
        except ValueError as e:
             raise ValueError(f"Invalid private key format: {e}")

        # Calculate Public Key Fingerprint
        # Snowflake requires SHA256 processing of the Subject Public Key Info (SPKI)
        try:
            public_key = private_key.public_key()
            pub_key_bytes = public_key.public_bytes(
                encoding=serialization.Encoding.DER,
                format=serialization.PublicFormat.SubjectPublicKeyInfo
            )
            
            sha256_hash = hashlib.sha256(pub_key_bytes).digest()
            fingerprint = base64.b64encode(sha256_hash).decode('utf-8')
        except Exception as e:
             raise ValueError(f"Failed to generate public key fingerprint: {e}")
        
        # Standard Payload for Snowflake JWT
        # iss: <account_identifier>.<user_name>.SHA256:<public_key_fingerprint>
        # sub: <account_identifier>.<user_name>
        payload = {
            "iss": f"{self.account}.{self.user}.SHA256:{fingerprint}",
            "sub": f"{self.account}.{self.user}",
            "iat": now,
            "exp": now + 3600 # 1 hour validity
        }
        
        try:
            token = jwt.encode(payload, private_key, algorithm="RS256")
        except Exception as e:
            raise ValueError(f"Failed to encode JWT: {e}")
            
        self._token = token
        self._token_exp = now + 3600
        return token

    def execute_query(self, sql: str, database: str = None, schema: str = None, warehouse: str = None, timeout: int = 60) -> List[Dict[str, Any]]:
        """
        Execute a SQL statement using Snowflake SQL API.
        Reference: https://docs.snowflake.com/en/developer-guide/sql-api/index
        """
        token = self._generate_jwt()
        
        # Construct Base URL
        # Format: https://<account_identifier>.snowflakecomputing.com/api/v2/statements
        # Note: Account identifier format varies by cloud region.
        # Ensure account provided matches expected subdomain.
        base_url = f"https://{self.account.lower()}.snowflakecomputing.com/api/v2/statements"
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Aden/SnowflakeTool/1.0",
            "X-Snowflake-Authorization-Token-Type": "KEYPAIR_JWT"
        }
        
        body = {
            "statement": sql,
            "timeout": timeout,
            "resultSetMetaData": {"format": "json"}
        }
        
        # Add context parameters if provided
        if database: body["database"] = database
        if schema: body["schema"] = schema
        if warehouse: body["warehouse"] = warehouse
        
        with httpx.Client() as client:
            try:
                resp = client.post(base_url, headers=headers, json=body, timeout=timeout+5)
                
                if resp.status_code == 401:
                     # Token might be invalid, clear cache
                     self._token = None
                
                resp.raise_for_status()
                data = resp.json()
                
                # Handling Snowflake SQL API Response structure
                # Success: { "resultSetMetaData": { "rowType": [...] }, "data": [...] }
                # Failure (should be raised by status, but logical errors): { "code": "...", "message": "..." }
                
                meta = data.get("resultSetMetaData", {})
                row_type = meta.get("rowType", [])
                columns = [col["name"] for col in row_type]
                rows = data.get("data", [])
                
                results = []
                for row in rows:
                    # 'data' is array of arrays of strings (usually)
                    results.append(dict(zip(columns, row)))
                    
                return results

            except httpx.HTTPStatusError as e:
                # Capture Snowflake detailed error message in response body if available
                error_body = e.response.text
                raise RuntimeError(f"Snowflake API Request Failed: {e.response.status_code} - {error_body}") from e
            except Exception as e:
                 raise RuntimeError(f"Snowflake execution error: {str(e)}") from e


def register_tools(mcp: FastMCP, credentials=None):
    """Register Snowflake tools with the MCP server."""

    def get_client() -> Optional[SnowflakeClient]:
        """Helper to initialize client from credentials."""
        # Check credentials object first (priority)
        account = None
        user = None
        private_key = None
        
        if credentials:
            try:
                account = credentials.get("snowflake_account")
                user = credentials.get("snowflake_user")
                private_key = credentials.get("snowflake_private_key")
            except KeyError:
                pass
        
        # Fallback to direct environment variables
        if not account: account = os.environ.get("SNOWFLAKE_ACCOUNT")
        if not user: user = os.environ.get("SNOWFLAKE_USER")
        if not private_key: private_key = os.environ.get("SNOWFLAKE_PRIVATE_KEY")
        
        if account and user and private_key:
            return SnowflakeClient(account, user, private_key)
        return None
        
    def get_context_params(database: Optional[str], schema: Optional[str], warehouse: Optional[str]):
        """Helper to resolve database/schema/warehouse from args or env."""
        db = database
        sc = schema
        wh = warehouse
        
        if credentials:
             if not db: db = credentials.get("snowflake_database")
             if not sc: sc = credentials.get("snowflake_schema")
             if not wh: wh = credentials.get("snowflake_warehouse")
        
        if not db: db = os.environ.get("SNOWFLAKE_DATABASE")
        if not sc: sc = os.environ.get("SNOWFLAKE_SCHEMA")
        if not wh: wh = os.environ.get("SNOWFLAKE_WAREHOUSE")
        
        return db, sc, wh

    @mcp.tool(name="snowflake_query", description="Execute a SQL query on Snowflake Data Cloud")
    def snowflake_query(
        query: str,
        database: Optional[str] = None,
        schema: Optional[str] = None,
        warehouse: Optional[str] = None,
        timeout: int = 60,
    ) -> List[Dict[str, Any]]:
        """
        Execute a SQL query on Snowflake.
        
        Args:
            query: The SQL query statement.
            database: Target database name (overrides default).
            schema: Target schema name (overrides default).
            warehouse: Compute warehouse name (overrides default).
            timeout: Query timeout in seconds (default: 60).
            
        Returns:
            List of dictionaries representing the result rows.
        """
        client = get_client()
        if not client:
             return [{"error": "Missing Snowflake credentials. Please set SNOWFLAKE_ACCOUNT, SNOWFLAKE_USER, and SNOWFLAKE_PRIVATE_KEY."}]
        
        db, sc, wh = get_context_params(database, schema, warehouse)
        
        try:
             return client.execute_query(query, database=db, schema=sc, warehouse=wh, timeout=timeout)
        except Exception as e:
             return [{"error": str(e)}]

    @mcp.tool(name="snowflake_describe", description="Get schema metadata for a database object in Snowflake")
    def snowflake_describe(
        object_type: str,
        object_name: str,
        database: Optional[str] = None,
        schema: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Describe a Snowflake object (Table, View, etc.).
        
        Args:
            object_type: Type of object (e.g. TABLE, VIEW, FUNCTION).
            object_name: Name of the object.
            database: Optional database context.
            schema: Optional schema context.
            
        Returns:
            Metadata about the object columns and properties.
        """
        # Sanitize input slightly to prevent blatant injection in DESCRIBE (though Snowflake handles it generally)
        # Using simple F-string here as DESCRIBE doesn't support bind variables in REST API easily in this context
        safe_type = object_type.strip().upper()
        allowed_types = ["TABLE", "VIEW", "FUNCTION", "PROCEDURE", "STREAM", "TASK", "PIPE", "STAGE", "FILE FORMAT", "SEQUENCE"]
        
        if safe_type not in allowed_types and not any(t in safe_type for t in allowed_types):
             return [{"error": f"Invalid object type: {object_type}"}]

        query = f"DESCRIBE {safe_type} {object_name}"
        return snowflake_query(query, database=database, schema=schema)

    @mcp.tool(name="snowflake_insert", description="Insert rows into a Snowflake table")
    def snowflake_insert(
        table: str,
        data: List[Dict[str, Any]],
        database: Optional[str] = None,
        schema: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Insert data into a Snowflake table.
        Note: This constructs an INSERT statement. For large bulk loads, utilize STAGE/COPY commands (not supported in this basic tool).
        
        Args:
            table: Target table name.
            data: List of dictionaries to insert. Keys must match column names.
            database: Optional database.
            schema: Optional schema.
            
        Returns:
            Status of insertion.
        """
        if not data:
            return {"status": "skipped", "message": "No data to insert"}
            
        # Naive implementation constructing INSERT VALUES
        # Warning: SQL Injection risk if keys/values are not sanitized.
        # The REST API supports bind variables? Yes.
        # https://docs.snowflake.com/en/developer-guide/sql-api/submitting-requests#using-bind-variables-in-a-statement
        
        columns = list(data[0].keys())
        placeholders = ", ".join(["?"] * len(columns))
        col_str = ", ".join(columns)
        
        sql = f"INSERT INTO {table} ({col_str}) VALUES ({placeholders})"
        
        # We need to execute this using bind variables for each row?
        # Snowflake API supports 'bindings' parameter.
        # But 'bindings' is dictionary. For batch insert: "data" field in generic format?
        # Actually Snowflake SQL API supports multiple statements or single statement with bindings.
        # Complex to do bulk insert via basic execute_query logic above without modifying client.
        
        # Let's do single batch insert via constructing values string (unsafe but standard for MVP tools)
        # Or better: construct values list securely-ISH.
        
        # Better: let's skip sophisticated insert for now and focus on Query/Describe as per Priority.
        # Or implement basic one:
        
        return {"status": "error", "message": "Not implemented yet - complex bind variable handling required."}
