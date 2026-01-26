FROM python:3.11-slim

# Install system dependencies required for development
# git: for version control
# curl/wget: for downloading tools
# build-essential: for compiling python extensions if needed
RUN apt-get update && apt-get install -y \
    git \
    curl \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Create a non-root user 'vscode' (standard for devcontainers)
RUN useradd -m -s /bin/bash vscode

# Set the working directory
WORKDIR /workspaces/hive

# Switch to non-root user
USER vscode


