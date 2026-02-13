# Hive Docker Setup

This document explains how to use the Docker environment for Aden Hive.

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/)
- [Docker Compose](https://docs.docker.com/compose/install/)

## Quick Start

1. **Configure Environment:**
   Copy `.env.example` to `.env` and add your API keys.
   ```bash
   cp .env.example .env
   ```

2. **Start Services:**
   The tools server must be running for the CLI to execute agents with tool access.
   ```bash
   docker compose up tools-server
   ```

3. **Run CLI Commands:**
   Run the Aden CLI using `docker compose run`.
   ```bash
   docker compose run aden --help
   docker compose run aden list /app/exports
   ```

## Volume Mounting

By default, the following volumes are mapped:
- `./exports` -> `/app/exports`: Place your exported agents here.
- `./examples` -> `/app/examples`: Read-only access to template agents.
- `workspaces`: A named volume for persistent tool data.

## Standalone Usage

You can also build and run the CLI container standalone without Compose:

```bash
docker build -t aden .
docker run --rm -v ./exports:/app/exports aden run exports/my_agent
```
