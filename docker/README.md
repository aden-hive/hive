# Hive Docker Setup

This directory provides a Docker-based environment to run the **Hive Agent Framework** with minimal setup.

It builds the Python runtime, installs the project dependencies using **uv**, compiles the React dashboard, and exposes the Hive API server on port **8787**.

The container also prints the accessible URLs when it starts, making it easy to open the dashboard from the host machine.

---

# Requirements

The setup was tested with the following versions:
* Docker version 29.1.3
* Docker Compose version v5.0.0


You can verify your installation with:

```bash
docker --version
docker compose version
```

# Project Structure

```
hive/
│
├─ core/
├─ tools/
├─ pyproject.toml
│
└─ docker/
   ├─ Dockerfile
   ├─ docker-compose.yml
   └─ start.sh
```



The start.sh script:

* prints the container IP
* prints the accessible host URL
* starts the Hive server bound to 0.0.0.0

Example startup message:

-------------------------------------------------
 Hive container started

 Container IP:  http://172.18.0.2:8787
 Local access:  http://localhost:8787

 Dashboard:     http://localhost:8787
 Healthcheck:   http://localhost:8787/api/health
--------------------------------------------------

Hive is launched with:
```bash
uv run hive serve --host 0.0.0.0 --port 8787
```

# Running Hive with Docker

Navigate to the docker directory:

```bash
cd docker
docker compose up --build
```

Once the container starts, the Hive dashboard will be available at:

```bash
http://localhost:8787
```

Health endpoint:

```bash
http://localhost:8787/api/health
```

# Rebuilding the Environment

If the container fails to start or dependencies need to be rebuilt, run:
```bash
docker compose down
docker compose build --no-cache
docker compose up
```

# Viewing Logs
To follow the Hive server logs:

```bash
docker logs -f hive
```

# Accessing and Checking the container

To open a shell inside the container without starting the Hive server:

```bash
docker compose run --service-ports hive bash
```


# Contribution

This Docker setup was created to simplify local development and testing of Hive inside containers. Improvements and suggestions are welcome.