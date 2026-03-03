# Hive Web Dashboard

A modern MERN stack web application for managing and running Hive AI agents with a visual interface.

## Project Structure

```
hive-web-dashboard/
├── backend/
│   ├── src/
│   │   ├── server.js           # Express server entry point
│   │   ├── controllers/        # API request handlers
│   │   ├── services/           # Business logic for Hive interaction
│   │   └── routes/             # API route definitions
│   ├── package.json
│   ├── .env.example
│   └── README.md
├── frontend/
│   ├── src/
│   │   ├── main.jsx            # React entry point
│   │   ├── App.jsx             # Main app component
│   │   ├── index.css           # Global styles
│   │   ├── components/         # React components
│   │   │   ├── Status.jsx
│   │   │   ├── AgentList.jsx
│   │   │   ├── AgentRunner.jsx
│   │   │   └── Dashboard.jsx
│   │   └── App.css             # App layout styles
│   ├── index.html
│   ├── vite.config.js
│   ├── package.json
│   └── README.md
└── README.md
```

## Quick Start

### Prerequisites

- Node.js 16+ and npm
- Hive installed and accessible via `hive` command
- Backend and frontend should run on different ports (5000 and 5173)

### Setup & Run

#### 1. Backend Setup

```bash
cd backend
npm install
cp .env.example .env
npm run dev
```

Backend runs on `http://localhost:5000`

#### 2. Frontend Setup

```bash
cd frontend
npm install
npm run dev
```

Frontend runs on `http://localhost:5173`

#### 3. Access the Dashboard

Open `http://localhost:5173` in your browser.

## Features

✅ **Real-time Status Monitoring** - Backend and Hive health checks
✅ **Agent Management** - List and view all exported agents  
✅ **Agent Execution** - Run agents with custom JSON input
✅ **Live Results** - View execution output and logs
✅ **Interactive Dashboard** - Statistics and charts
✅ **Modern UI** - Beautiful, responsive design with React + Vite

## API Endpoints

| Method | Endpoint                 | Description          |
| ------ | ------------------------ | -------------------- |
| GET    | `/api/health`            | Backend health check |
| GET    | `/api/hive/status`       | Hive system status   |
| GET    | `/api/hive/agents`       | List all agents      |
| GET    | `/api/hive/agents/:name` | Get agent info       |
| POST   | `/api/hive/run`          | Run an agent         |

## Configuration

### Backend (.env)

```env
PORT=5000
HIVE_HOME=/path/to/hive
NODE_ENV=development
```

### Frontend (vite.config.js)

API proxy already configured to forward requests to backend.

## Development Workflow

1. Make changes to backend/frontend code
2. Both run in dev mode with hot reload
3. Use browser DevTools to debug frontend
4. Use terminal logs to debug backend

## Building for Production

### Backend

```bash
cd backend
npm install
npm start
```

### Frontend

```bash
cd frontend
npm install
npm run build
# Serve dist/ with a static server
```

## Troubleshooting

**Backend can't find `hive` command**

- Ensure Hive is in your PATH
- For Windows, use WSL or Git Bash
- Verify with: `hive --help`

**Frontend can't reach backend**

- Check backend is running on port 5000
- Verify CORS is enabled in backend
- Check browser console for errors

**Agent execution fails**

- Verify agent name exists: `hive list`
- Check JSON input format is valid
- Review backend logs for detailed errors

## License

Apache-2.0

## Contributing

Please refer to the main Hive repository CONTRIBUTING.md
