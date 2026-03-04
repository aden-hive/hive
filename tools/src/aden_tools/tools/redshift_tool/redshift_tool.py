"""Amazon Redshift Data API integration.

Provides SQL execution and schema browsing via the Redshift Data API with SigV4 signing.
Requires AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, and AWS_REGION.
"""

from __future__ import annotations

import datetime
import hashlib
import hmac
import json
import os
from typing import Any

import httpx
from fastmcp import FastMCP

SERVICE = "redshift-data"


def _get_config() -> tuple[str, str, str] | dict:
    """Return (access_key, secret_key, region) or error dict."""
    access_key = os.getenv("AWS_ACCESS_KEY_ID", "")
    secret_key = os.getenv("AWS_SECRET_ACCESS_KEY", "")
    region = os.getenv("AWS_REGION", "us-east-1")
    if not access_key or not secret_key:
        return {
            "error": "AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY are required",
            "help": "Set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY environment variables",
        }
    return access_key, secret_key, region


def _sign(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _get_signing_key(secret_key: str, datestamp: str, region: str) -> bytes:
    k_date = _sign(("AWS4" + secret_key).encode("utf-8"), datestamp)
    k_region = _sign(k_date, region)
    k_service = _sign(k_region, SERVICE)
    return _sign(k_service, "aws4_request")


def _api_call(
    action: str,
    payload: dict,
    access_key: str,
    secret_key: str,
    region: str,
) -> dict:
    """Make a signed POST request to the Redshift Data API."""
    host = f"{SERVICE}.{region}.amazonaws.com"
    body = json.dumps(payload).encode("utf-8")
    now = datetime.datetime.now(datetime.UTC)
    datestamp = now.strftime("%Y%m%d")
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    payload_hash = hashlib.sha256(body).hexdigest()

    headers_to_sign = {
        "content-type": "application/x-amz-json-1.1",
        "host": host,
        "x-amz-date": amz_date,
        "x-amz-target": f"RedshiftData.{action}",
    }
    signed_headers_str = ";".join(sorted(headers_to_sign.keys()))
    canonical_headers = "".join(f"{k}:{v}\n" for k, v in sorted(headers_to_sign.items()))

    canonical_request = f"POST\n/\n\n{canonical_headers}\n{signed_headers_str}\n{payload_hash}"
    credential_scope = f"{datestamp}/{region}/{SERVICE}/aws4_request"
    string_to_sign = (
        f"AWS4-HMAC-SHA256\n{amz_date}\n{credential_scope}\n"
        + hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()
    )
    signing_key = _get_signing_key(secret_key, datestamp, region)
    signature = hmac.new(signing_key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

    auth_header = (
        f"AWS4-HMAC-SHA256 Credential={access_key}/{credential_scope}, "
        f"SignedHeaders={signed_headers_str}, Signature={signature}"
    )

    final_headers = {
        "Content-Type": "application/x-amz-json-1.1",
        "X-Amz-Date": amz_date,
        "X-Amz-Target": f"RedshiftData.{action}",
        "Authorization": auth_header,
    }

    resp = httpx.post(f"https://{host}/", headers=final_headers, content=body, timeout=30)
    if resp.status_code >= 400:
        return {"error": f"HTTP {resp.status_code}: {resp.text[:500]}"}
    return resp.json()


def _extract_field(field: dict) -> Any:
    """Extract value from a Redshift Data API field union type."""
    if field.get("isNull"):
        return None
    for key in ("stringValue", "longValue", "doubleValue", "booleanValue", "blobValue"):
        if key in field:
            return field[key]
    return None


def register_tools(mcp: FastMCP, credentials: Any = None) -> None:
    """Register Redshift Data API tools."""

    @mcp.tool()
    def redshift_execute_sql(
        sql: str,
        database: str,
        cluster_identifier: str = "",
        workgroup_name: str = "",
        secret_arn: str = "",
        db_user: str = "",
    ) -> dict:
        """Execute a SQL statement on Amazon Redshift (async).

        Args:
            sql: SQL statement to execute.
            database: Database name.
            cluster_identifier: Provisioned cluster identifier (or use workgroup_name).
            workgroup_name: Serverless workgroup name (alternative to cluster_identifier).
            secret_arn: AWS Secrets Manager ARN for DB credentials (optional).
            db_user: Database user for temp credentials (optional).
        """
        cfg = _get_config()
        if isinstance(cfg, dict):
            return cfg
        access_key, secret_key, region = cfg
        if not sql.strip() or not database:
            return {"error": "sql and database are required"}
        if not cluster_identifier and not workgroup_name:
            return {"error": "cluster_identifier or workgroup_name is required"}

        payload: dict[str, Any] = {"Sql": sql, "Database": database}
        if cluster_identifier:
            payload["ClusterIdentifier"] = cluster_identifier
        if workgroup_name:
            payload["WorkgroupName"] = workgroup_name
        if secret_arn:
            payload["SecretArn"] = secret_arn
        if db_user:
            payload["DbUser"] = db_user

        data = _api_call("ExecuteStatement", payload, access_key, secret_key, region)
        if "error" in data:
            return data

        return {
            "statement_id": data.get("Id"),
            "status": "submitted",
            "database": data.get("Database"),
        }

    @mcp.tool()
    def redshift_describe_statement(statement_id: str) -> dict:
        """Check the status of a Redshift SQL statement.

        Args:
            statement_id: The statement ID from redshift_execute_sql.
        """
        cfg = _get_config()
        if isinstance(cfg, dict):
            return cfg
        access_key, secret_key, region = cfg
        if not statement_id:
            return {"error": "statement_id is required"}

        data = _api_call("DescribeStatement", {"Id": statement_id}, access_key, secret_key, region)
        if "error" in data:
            return data

        return {
            "statement_id": data.get("Id"),
            "status": data.get("Status"),
            "has_result_set": data.get("HasResultSet"),
            "result_rows": data.get("ResultRows"),
            "duration_ns": data.get("Duration"),
            "query": data.get("QueryString"),
            "error": data.get("Error") or None,
        }

    @mcp.tool()
    def redshift_get_results(statement_id: str) -> dict:
        """Fetch results of a completed Redshift SQL statement.

        Args:
            statement_id: The statement ID (must be in FINISHED status).
        """
        cfg = _get_config()
        if isinstance(cfg, dict):
            return cfg
        access_key, secret_key, region = cfg
        if not statement_id:
            return {"error": "statement_id is required"}

        data = _api_call("GetStatementResult", {"Id": statement_id}, access_key, secret_key, region)
        if "error" in data:
            return data

        columns = [col.get("name") for col in data.get("ColumnMetadata", [])]
        records = data.get("Records", [])
        rows = [[_extract_field(f) for f in record] for record in records[:100]]

        return {
            "columns": columns,
            "rows": rows,
            "total_rows": data.get("TotalNumRows"),
            "truncated": len(records) > 100,
        }

    @mcp.tool()
    def redshift_list_databases(
        cluster_identifier: str = "",
        workgroup_name: str = "",
        database: str = "dev",
        secret_arn: str = "",
    ) -> dict:
        """List databases in a Redshift cluster or workgroup.

        Args:
            cluster_identifier: Provisioned cluster identifier.
            workgroup_name: Serverless workgroup name.
            database: Database to connect with (default 'dev').
            secret_arn: AWS Secrets Manager ARN (optional).
        """
        cfg = _get_config()
        if isinstance(cfg, dict):
            return cfg
        access_key, secret_key, region = cfg
        if not cluster_identifier and not workgroup_name:
            return {"error": "cluster_identifier or workgroup_name is required"}

        payload: dict[str, Any] = {"Database": database, "MaxResults": 100}
        if cluster_identifier:
            payload["ClusterIdentifier"] = cluster_identifier
        if workgroup_name:
            payload["WorkgroupName"] = workgroup_name
        if secret_arn:
            payload["SecretArn"] = secret_arn

        data = _api_call("ListDatabases", payload, access_key, secret_key, region)
        if "error" in data:
            return data

        databases = data.get("Databases", [])
        return {"count": len(databases), "databases": databases}

    @mcp.tool()
    def redshift_list_tables(
        database: str,
        schema_pattern: str = "public",
        cluster_identifier: str = "",
        workgroup_name: str = "",
        secret_arn: str = "",
    ) -> dict:
        """List tables in a Redshift database schema.

        Args:
            database: Database name.
            schema_pattern: Schema pattern to filter (default 'public').
            cluster_identifier: Provisioned cluster identifier.
            workgroup_name: Serverless workgroup name.
            secret_arn: AWS Secrets Manager ARN (optional).
        """
        cfg = _get_config()
        if isinstance(cfg, dict):
            return cfg
        access_key, secret_key, region = cfg
        if not database:
            return {"error": "database is required"}
        if not cluster_identifier and not workgroup_name:
            return {"error": "cluster_identifier or workgroup_name is required"}

        payload: dict[str, Any] = {
            "Database": database,
            "SchemaPattern": schema_pattern,
            "MaxResults": 100,
        }
        if cluster_identifier:
            payload["ClusterIdentifier"] = cluster_identifier
        if workgroup_name:
            payload["WorkgroupName"] = workgroup_name
        if secret_arn:
            payload["SecretArn"] = secret_arn

        data = _api_call("ListTables", payload, access_key, secret_key, region)
        if "error" in data:
            return data

        tables = data.get("Tables", [])
        return {
            "count": len(tables),
            "tables": [
                {
                    "name": t.get("name"),
                    "schema": t.get("schema"),
                    "type": t.get("type"),
                }
                for t in tables
            ],
        }
