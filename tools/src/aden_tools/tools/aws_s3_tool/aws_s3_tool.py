"""AWS S3 REST API integration.

Provides object storage operations via the S3 REST API with SigV4 signing.
Requires AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, and AWS_REGION.
"""

from __future__ import annotations

import datetime
import hashlib
import hmac
import os
import urllib.parse
import xml.etree.ElementTree as ET
from typing import Any

import httpx
from fastmcp import FastMCP

EMPTY_HASH = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


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
    k_service = _sign(k_region, "s3")
    return _sign(k_service, "aws4_request")


def _sign_request(
    method: str,
    host: str,
    path: str,
    query_params: dict,
    headers: dict,
    body: bytes,
    access_key: str,
    secret_key: str,
    region: str,
) -> dict:
    """Sign an S3 request with AWS SigV4 and return updated headers."""
    now = datetime.datetime.now(datetime.UTC)
    datestamp = now.strftime("%Y%m%d")
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")

    payload_hash = hashlib.sha256(body).hexdigest()

    headers["host"] = host
    headers["x-amz-date"] = amz_date
    headers["x-amz-content-sha256"] = payload_hash

    # Canonical query string
    sorted_params = sorted(query_params.items())
    canonical_qs = "&".join(
        f"{urllib.parse.quote(k, safe='')}={urllib.parse.quote(str(v), safe='')}"
        for k, v in sorted_params
    )

    # Canonical headers
    signed_header_names = sorted(headers.keys())
    canonical_headers = "".join(f"{k}:{headers[k].strip()}\n" for k in signed_header_names)
    signed_headers = ";".join(signed_header_names)

    canonical_request = (
        f"{method}\n{path}\n{canonical_qs}\n{canonical_headers}\n{signed_headers}\n{payload_hash}"
    )

    credential_scope = f"{datestamp}/{region}/s3/aws4_request"
    string_to_sign = (
        f"AWS4-HMAC-SHA256\n{amz_date}\n{credential_scope}\n"
        f"{hashlib.sha256(canonical_request.encode()).hexdigest()}"
    )

    signing_key = _get_signing_key(secret_key, datestamp, region)
    signature = hmac.new(signing_key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

    headers["Authorization"] = (
        f"AWS4-HMAC-SHA256 Credential={access_key}/{credential_scope},"
        f"SignedHeaders={signed_headers},Signature={signature}"
    )
    return headers


def _s3_request(
    method: str,
    bucket: str,
    key: str,
    access_key: str,
    secret_key: str,
    region: str,
    query_params: dict | None = None,
    body: bytes = b"",
    extra_headers: dict | None = None,
) -> httpx.Response:
    """Make a signed S3 request."""
    if bucket:
        host = f"{bucket}.s3.{region}.amazonaws.com"
    else:
        host = "s3.amazonaws.com"

    path = f"/{key}" if key else "/"
    url = f"https://{host}{path}"

    headers = extra_headers.copy() if extra_headers else {}
    qp = query_params or {}

    headers = _sign_request(method, host, path, qp, headers, body, access_key, secret_key, region)

    return getattr(httpx, method.lower())(url, headers=headers, params=qp, content=body, timeout=30)


def _parse_xml(text: str, ns: str = "") -> ET.Element:
    """Parse XML text, stripping namespace if present."""
    root = ET.fromstring(text)
    if ns:
        for elem in root.iter():
            if elem.tag.startswith(f"{{{ns}}}"):
                elem.tag = elem.tag[len(f"{{{ns}}}") :]
    return root


S3_NS = "http://s3.amazonaws.com/doc/2006-03-01/"


def register_tools(mcp: FastMCP, credentials: Any = None) -> None:
    """Register AWS S3 tools."""

    @mcp.tool()
    def s3_list_buckets() -> dict:
        """List all S3 buckets in the account."""
        cfg = _get_config()
        if isinstance(cfg, dict):
            return cfg
        access_key, secret_key, region = cfg

        resp = _s3_request("GET", "", "", access_key, secret_key, region)
        if resp.status_code >= 400:
            return {"error": f"HTTP {resp.status_code}: {resp.text[:500]}"}

        root = _parse_xml(resp.text, S3_NS)
        buckets = []
        for b in root.findall(".//Bucket"):
            name_el = b.find("Name")
            date_el = b.find("CreationDate")
            buckets.append(
                {
                    "name": name_el.text if name_el is not None else None,
                    "creation_date": date_el.text if date_el is not None else None,
                }
            )
        return {"count": len(buckets), "buckets": buckets}

    @mcp.tool()
    def s3_list_objects(
        bucket: str,
        prefix: str = "",
        delimiter: str = "/",
        max_keys: int = 100,
    ) -> dict:
        """List objects in an S3 bucket.

        Args:
            bucket: S3 bucket name.
            prefix: Filter by key prefix (e.g. 'photos/').
            delimiter: Grouping delimiter (default '/').
            max_keys: Maximum objects to return (default 100).
        """
        cfg = _get_config()
        if isinstance(cfg, dict):
            return cfg
        access_key, secret_key, region = cfg
        if not bucket:
            return {"error": "bucket is required"}

        params: dict[str, Any] = {"list-type": "2", "max-keys": str(max_keys)}
        if prefix:
            params["prefix"] = prefix
        if delimiter:
            params["delimiter"] = delimiter

        resp = _s3_request("GET", bucket, "", access_key, secret_key, region, query_params=params)
        if resp.status_code >= 400:
            return {"error": f"HTTP {resp.status_code}: {resp.text[:500]}"}

        root = _parse_xml(resp.text, S3_NS)
        objects = []
        for c in root.findall("Contents"):
            key_el = c.find("Key")
            size_el = c.find("Size")
            modified_el = c.find("LastModified")
            objects.append(
                {
                    "key": key_el.text if key_el is not None else None,
                    "size": int(size_el.text) if size_el is not None else 0,
                    "last_modified": modified_el.text if modified_el is not None else None,
                }
            )
        prefixes = []
        for cp in root.findall("CommonPrefixes"):
            p_el = cp.find("Prefix")
            if p_el is not None:
                prefixes.append(p_el.text)

        truncated_el = root.find("IsTruncated")
        is_truncated = truncated_el is not None and truncated_el.text == "true"

        result: dict[str, Any] = {
            "count": len(objects),
            "objects": objects,
        }
        if prefixes:
            result["common_prefixes"] = prefixes
        if is_truncated:
            token_el = root.find("NextContinuationToken")
            if token_el is not None:
                result["next_continuation_token"] = token_el.text
        return result

    @mcp.tool()
    def s3_get_object(
        bucket: str,
        key: str,
        max_bytes: int = 10000,
    ) -> dict:
        """Get an object from S3. Returns text content for small objects.

        Args:
            bucket: S3 bucket name.
            key: Object key (path).
            max_bytes: Maximum bytes to read (default 10000). Large files are truncated.
        """
        cfg = _get_config()
        if isinstance(cfg, dict):
            return cfg
        access_key, secret_key, region = cfg
        if not bucket or not key:
            return {"error": "bucket and key are required"}

        extra: dict[str, str] = {}
        if max_bytes > 0:
            extra["Range"] = f"bytes=0-{max_bytes - 1}"

        resp = _s3_request("GET", bucket, key, access_key, secret_key, region, extra_headers=extra)
        if resp.status_code >= 400:
            return {"error": f"HTTP {resp.status_code}: {resp.text[:500]}"}

        content_type = resp.headers.get("content-type", "")
        result: dict[str, Any] = {
            "key": key,
            "content_type": content_type,
            "size": resp.headers.get("content-length"),
            "last_modified": resp.headers.get("last-modified"),
            "etag": resp.headers.get("etag"),
        }
        if "text" in content_type or "json" in content_type or "xml" in content_type:
            result["content"] = resp.text
        else:
            result["content_preview"] = f"[binary data, {len(resp.content)} bytes]"
        return result

    @mcp.tool()
    def s3_put_object(
        bucket: str,
        key: str,
        content: str,
        content_type: str = "text/plain",
    ) -> dict:
        """Upload a text object to S3.

        Args:
            bucket: S3 bucket name.
            key: Object key (path).
            content: Text content to upload.
            content_type: MIME type (default 'text/plain').
        """
        cfg = _get_config()
        if isinstance(cfg, dict):
            return cfg
        access_key, secret_key, region = cfg
        if not bucket or not key:
            return {"error": "bucket and key are required"}
        if not content:
            return {"error": "content is required"}

        body = content.encode("utf-8")
        extra = {"content-type": content_type}

        resp = _s3_request(
            "PUT", bucket, key, access_key, secret_key, region, body=body, extra_headers=extra
        )
        if resp.status_code >= 400:
            return {"error": f"HTTP {resp.status_code}: {resp.text[:500]}"}

        return {
            "result": "uploaded",
            "key": key,
            "etag": resp.headers.get("etag"),
            "size": len(body),
        }

    @mcp.tool()
    def s3_delete_object(
        bucket: str,
        key: str,
    ) -> dict:
        """Delete an object from S3.

        Args:
            bucket: S3 bucket name.
            key: Object key (path) to delete.
        """
        cfg = _get_config()
        if isinstance(cfg, dict):
            return cfg
        access_key, secret_key, region = cfg
        if not bucket or not key:
            return {"error": "bucket and key are required"}

        resp = _s3_request("DELETE", bucket, key, access_key, secret_key, region)
        if resp.status_code >= 400:
            return {"error": f"HTTP {resp.status_code}: {resp.text[:500]}"}

        return {"result": "deleted", "key": key}
