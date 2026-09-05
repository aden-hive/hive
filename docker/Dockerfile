FROM python:3.11-slim

# Install system dependencies required to build Python packages
RUN apt-get update && apt-get install -y \
    curl \
    git \
    build-essential \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install uv (Python package manager used by Hive)
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

# Install Node.js 20 to build the React frontend
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs

WORKDIR /app

# Copy the full project into the container
# (docker-compose sets the build context to the repository root)
COPY . .

# Install Python dependencies using uv workspace
RUN uv sync

# Build the React frontend
WORKDIR /app/core/frontend
RUN npm install && npm run build

WORKDIR /app

# Copy container startup script
COPY docker/start.sh /start.sh
RUN chmod +x /start.sh

# Expose Hive dashboard port
EXPOSE 8787

# Persist Hive configuration and credentials
VOLUME ["/root/.hive"]

# Container health check
HEALTHCHECK CMD curl -f http://localhost:8787/api/health || exit 1

# Start Hive server
ENTRYPOINT ["/start.sh"]
