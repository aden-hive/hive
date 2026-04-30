"""``shell_output_get`` — retrieve truncated output via handle."""

from __future__ import annotations

from typing import TYPE_CHECKING

from shell_tools.common.output_store import get_store

if TYPE_CHECKING:
    from fastmcp import FastMCP


def register_output_tools(mcp: FastMCP) -> None:
    @mcp.tool()
    def shell_output_get(
        output_handle: str,
        since_offset: int = 0,
        max_kb: int = 64,
    ) -> dict:
        """Retrieve a slice of truncated output by handle.

        When shell_exec or shell_job_logs returns more output than fits inline,
        you'll see `output_handle: "out_<hex>"`. Pass it here with successive
        offsets to paginate. The full output is preserved (combined stdout+stderr
        with `--- stdout ---` / `--- stderr ---` separators) for 5 minutes.

        Args:
            output_handle: From a prior tool's envelope.
            since_offset: Pass 0 first, then next_offset from the previous call.
            max_kb: Max KB to return per call.

        Returns: {data, offset, next_offset, eof, expired}
        """
        return get_store().get(
            output_handle,
            since_offset=since_offset,
            max_bytes=max_kb * 1024,
        )


__all__ = ["register_output_tools"]
