# Aden Tools MCP Server
# Exposes tools via Model Context Protocol

FROM python:3.11-slim

WORKDIR /app

# Copy project files
COPY pyproject.toml ./
COPY README.md ./
COPY src ./src
COPY mcp_server.py ./

# Install package with all dependencies
RUN pip install --no-cache-dir -e .

# Install Google Chrome (stable) — used by GCU browser tools via CDP
RUN apt-get update && apt-get install -y wget gnupg \
    && mkdir -p /etc/apt/keyrings \
    && wget -q -O /etc/apt/keyrings/google-chrome.asc https://dl.google.com/linux/linux_signing_key.pub \
    && echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/google-chrome.asc] http://dl.google.com/linux/chrome/deb/ stable main" \
       > /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update && apt-get install -y google-chrome-stable \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

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
