# Hive Web Dashboard - Frontend

Modern React + Vite frontend for visualizing and controlling Hive agents.

## Installation

```bash
cd frontend
npm install
```

## Running the Development Server

```bash
npm run dev
```

The frontend will start on `http://localhost:5173` and automatically proxy API requests to the backend at `http://localhost:5000`.

## Building for Production

```bash
npm run build
```

Builds the optimized production bundle to the `dist/` directory.

## Features

### 📊 Status Tab

- Backend health check
- Hive status verification
- Real-time status updates

### 🤖 Agents Tab

- View all available exported agents
- Agent information display
- Quick access to agent details

### ▶️ Run Agent Tab

- Run any exported agent with custom input
- JSON input editor
- Live execution results and logs

### 📈 Dashboard Tab

- Real-time statistics and charts
- Agent execution timeline
- Backend status monitoring
- System information

## API Integration

The frontend communicates with the backend via these endpoints:

- `GET /api/health` - Backend health
- `GET /api/hive/status` - Hive system status
- `GET /api/hive/agents` - List all agents
- `GET /api/hive/agents/:name` - Get agent info
- `POST /api/hive/run` - Run an agent

## Development

Ensure the backend is running on `http://localhost:5000` before starting the frontend.

```bash
# Terminal 1: Start Backend
cd backend
npm install
npm run dev

# Terminal 2: Start Frontend
cd frontend
npm install
npm run dev
```

Then open `http://localhost:5173` in your browser.
