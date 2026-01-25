# Containerized Hive Workspace

This repo can be run inside a Docker container so that you don’t need to install every dependency on the host. The provided `Dockerfile` builds an image with the Python packages (`core`, `tools`) installed in editable mode.

## Build the image

```bash
docker build -t aden-hive:latest .
```

The build installs system packages (`build-essential`, `libxml2-dev`, `libxslt-dev`, `liblzma-dev`) that pip packages such as `lupa`, `pandas`, and `pypdf` rely on.

## Spin up a shell

Mount your workspace so you can edit files and access generated exports:

```bash
docker run --rm -it \
  -v "$PWD":/workspace \
  -p 4001:4001 \
  -e BRAVE_SEARCH_API_KEY=your-key \
  aden-hive:latest
```

Inside the container you already start from `/workspace`. Because the image set `PYTHONPATH=/workspace/core:/workspace/exports`, you can run the CLI the same way you do locally:

```bash
python -m core --help
python -m framework interactive
python -m framework run exports/my-agent --input '{"key":"value"}'
```

When you need the MCP server, run:

```bash
python tools/mcp_server.py --port 4001
```

If you mount your host workspace (`-v "$PWD":/workspace`), any exports or generated artifacts persist on the host.

## Run tests inside the container

```bash
docker run --rm -it -v "$PWD":/workspace aden-hive:latest python3 -m pytest tools/tests/test_credentials.py
```

## Notes

- The container doesn’t run a persistent agent; use the `tools/mcp_server.py` command or `python -m framework` commands manually.
- Add other environment variables (OpenAI, Anthropic) via `-e VAR=value` when you launch the container if you need them.
- To clean up lingering volumes or containers, use `docker system prune` / `docker volume rm` if necessary.
