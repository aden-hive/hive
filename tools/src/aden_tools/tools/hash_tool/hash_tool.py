"""
Hash Tool - Compute cryptographic hashes for text content.

A utility tool for computing MD5, SHA1, SHA256, and SHA512 hashes.
"""
from __future__ import annotations

import hashlib
from fastmcp import FastMCP


def register_tools(mcp: FastMCP) -> None:
    """Register hash tools with the MCP server."""

    @mcp.tool()
    def hash_tool(
        text: str,
        algorithm: str = "sha256",
    ) -> dict:
        """
        Compute a cryptographic hash of text content.
        Use this tool when you need to verify content integrity, detect changes,
        or generate unique identifiers for text.

        Args:
            text: The text to hash (1-100000 characters)
            algorithm: Hash algorithm to use: md5, sha1, sha256, sha512 (default: sha256)

        Returns:
            Dict with algorithm, hash, and input length, or error dict
        """
        try:
            # Validate text input
            if not text or len(text) > 100000:
                return {"error": "text must be 1-100000 characters"}

            # Validate algorithm
            valid_algorithms = ["md5", "sha1", "sha256", "sha512"]
            algorithm = algorithm.lower().strip()
            if algorithm not in valid_algorithms:
                return {
                    "error": f"algorithm must be one of: {', '.join(valid_algorithms)}"
                }

            # Compute hash
            hash_obj = hashlib.new(algorithm)
            hash_obj.update(text.encode("utf-8"))

            return {
                "algorithm": algorithm,
                "hash": hash_obj.hexdigest(),
                "length": len(text),
            }

        except Exception as e:
            return {"error": f"Hash computation failed: {str(e)}"}
