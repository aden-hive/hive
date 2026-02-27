# Aden Tools MCP Server
# Exposes tools via Model Context Protocol

# Pin to a specific digest for reproducible builds
FROM python:3.11-slim@sha256:8faa14e498a982a15e2abff1e12e498d53c74a33a3bab4e3e1ae27e18e7f35e4

WORKDIR /app

# Copy project files
COPY pyproject.toml ./
COPY README.md ./
COPY src ./src
COPY mcp_server.py ./

# Install package in non-editable mode for production
# (editable installs are for development only)
RUN pip install --no-cache-dir .

# Install Playwright Chromium browser and system dependencies
RUN playwright install chromium --with-deps

# Create non-root user for security
RUN useradd -m -u 1001 appuser

# Create workspaces directory for file system tools persistence
# This directory will be mounted as a volume
RUN mkdir -p /app/workdir/workspaces && \
    chown -R appuser:appuser /app

USER appuser

# Declare volume for workspace persistence across container runs
VOLUME ["/app/workdir/workspaces"]

# Expose MCP server port
EXPOSE 4001

# Health check - verify server is responding
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:4001/health').raise_for_status()" || exit 1

# Run MCP server with HTTP transport
CMD ["python", "mcp_server.py"]
