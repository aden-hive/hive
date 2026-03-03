# Hive Web Dashboard - Backend

Express.js API server that provides endpoints to interact with Hive agents.

## Installation

```bash
cd backend
npm install
```

## Configuration

Copy `.env.example` to `.env` and update as needed:

```bash
cp .env.example .env
```

## Running the Server

**Development mode (with auto-reload):**

```bash
npm run dev
```

**Production mode:**

```bash
npm start
```

The server will start on `http://localhost:5000` by default.

## API Endpoints

### Health Check

- **GET** `/api/health` - Check if backend is running

### Hive Status

- **GET** `/api/hive/status` - Check if Hive is installed and accessible

### List Agents

- **GET** `/api/hive/agents` - List all exported agents

### Get Agent Info

- **GET** `/api/hive/agents/:name` - Get detailed info about a specific agent

### Run Agent

- **POST** `/api/hive/run`
  - Body: `{ "agentName": "agent_name", "input": {...} }`
  - Returns: Agent execution result

## Example Requests

```bash
# Check health
curl http://localhost:5000/api/health

# Check Hive status
curl http://localhost:5000/api/hive/status

# List agents
curl http://localhost:5000/api/hive/agents

# Run an agent
curl -X POST http://localhost:5000/api/hive/run \
  -H "Content-Type: application/json" \
  -d '{"agentName":"my_agent","input":{"key":"value"}}'
```

## Notes

- Ensure Hive CLI is installed and `hive` command is available in your PATH
- For Windows, run the backend in WSL or Git Bash for proper shell execution
- CORS is enabled for frontend integration
