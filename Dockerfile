# Hive — Core CLI + Tools MCP Server
# Multi-stage build for minimal production image

# ──────────────────────────────────────────────
# Stage 1: Build — resolve dependencies with uv
# ──────────────────────────────────────────────
FROM python:3.12-slim AS builder

# Install uv for fast, reproducible dependency resolution
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Ensure uv uses the system Python (3.12)
ENV UV_PYTHON=python3.12

# Copy workspace root config first (uv workspace definition)
COPY pyproject.toml uv.lock ./

# Copy both workspace members — core depends on tools via workspace reference
COPY core/pyproject.toml core/README.md core/uv.lock ./core/
COPY core/framework ./core/framework

COPY tools/pyproject.toml tools/README.md tools/uv.lock ./tools/
COPY tools/src ./tools/src
COPY tools/mcp_server.py ./tools/

# Sync the core project (pulls in tools as a workspace dependency)
RUN uv sync --project core --no-dev --frozen

# ──────────────────────────────────────────────
# Stage 2: Runtime — minimal production image
# ──────────────────────────────────────────────
FROM python:3.12-slim

WORKDIR /app

# Copy the resolved virtual env and source from builder
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/core /app/core
COPY --from=builder /app/tools /app/tools
COPY --from=builder /app/pyproject.toml /app/pyproject.toml

# Make the venv the default Python environment
ENV PATH="/app/.venv/bin:$PATH"
ENV VIRTUAL_ENV="/app/.venv"

# Create non-root user for security
RUN useradd -m -u 1001 appuser

# Create directories for workspace persistence and agent exports
RUN mkdir -p /app/exports /app/workdir && \
    chown -R appuser:appuser /app

USER appuser

# Persist workspaces and agent data across runs
VOLUME ["/app/exports", "/app/workdir"]

# Expose MCP server port (used when running the tools server)
EXPOSE 4001

# Health check — verifies the CLI is functional
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD hive list /app/exports || exit 1

# Default: run the hive CLI (users pass subcommands via docker run args)
ENTRYPOINT ["hive"]
CMD ["--help"]
