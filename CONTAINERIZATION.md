# Containerized Hive Workspace

This repo can be run entirely inside Docker so you don’t need to install every dependency on the host. The provided `Dockerfile` builds an image with the Python packages (`core`, `tools`) installed in editable mode, and the accompanying `docker-compose.yml` file orchestrates the agent shell plus the MCP tools server.

## Build the image

```bash
docker build -t aden-hive:latest .
```

The build installs system packages (`build-essential`, `libxml2-dev`, `libxslt-dev`, `liblzma-dev`) that pip packages such as `lupa`, `pandas`, and `pypdf` rely on.

## Docker Compose

Use `docker compose` to build and run the agent and MCP server from the same base image.

### Build all services

```bash
docker compose build
```

### Run the MCP tools server

```bash
docker compose up tools
```

This starts `python tools/mcp_server.py --port 4001` inside the container and exposes port 4001 on your host. Supply any required credentials (e.g., `BRAVE_SEARCH_API_KEY`) via a `.env` file or `export` statements before running.

### Open an interactive agent shell

```bash
docker compose run --rm agent
```

That drops you into `/workspace` with `PYTHONPATH=/workspace/core:/workspace/exports`, so you can run the framework CLI just like on your host:

```bash
python -m core --help
python -m framework interactive
python -m framework run exports/my-agent --input '{"key":"value"}'
```

### Run tests inside the container

```bash
docker compose run --rm agent python3 -m pytest tools/tests/test_credentials.py
```

## Notes

- The `agent` service simply hands you an editable shell; run any CLI command from there. The `tools` service keeps the MCP server running on port 4001.
- Persist exports/artifacts by mounting your repository as a volume (`-v "$PWD":/workspace` is handled automatically by the Compose YAML).
- To stop `docker compose up tools`, Ctrl+C the logs or run `docker compose down`.
