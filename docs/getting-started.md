# Getting Started

This guide will help you get Hive running on your local machine.

## Prerequisites

- **Docker** (v20.10+) and **Docker Compose** (v2.0+) - for containerized deployment
- **Node.js** (v20+) - for local development without Docker

## Quick Start with Docker

The fastest way to get started is using Docker Compose:

```bash
# 1. Clone the repository
git clone https://github.com/adenhq/hive.git
cd hive

# 2. Copy and configure
cp config.yaml.example config.yaml

# 3. Run setup
npm run setup

# 4. Start services
docker compose up
```

The application will be available at:

- **Frontend**: http://localhost:3000
- **Backend API**: http://localhost:4000
- **Health Check**: http://localhost:4000/health

## Development Setup

For local development with hot reload:

```bash
# 1. Clone and configure (same as above)
git clone https://github.com/adenhq/hive.git
cd hive
cp config.yaml.example config.yaml

# 2. Install dependencies
npm install

# 3. Generate environment files
npm run generate:env

# 4. Start frontend (terminal 1)
cd honeycomb
npm run dev

# 5. Start backend (terminal 2)
cd hive
npm run dev
```

### Using Docker for Development

You can also use Docker with hot reload enabled:

```bash
# Copy development overrides
cp docker-compose.override.yml.example docker-compose.override.yml

# Start with hot reload
docker compose up
```

## Project Structure

```
hive/
├── honeycomb/          # Frontend (React + TypeScript + Vite)
│   ├── src/
│   │   ├── components/ # Reusable UI components
│   │   ├── pages/      # Page components
│   │   ├── hooks/      # Custom React hooks
│   │   ├── services/   # API client and services
│   │   ├── types/      # TypeScript type definitions
│   │   └── utils/      # Utility functions
│   └── public/         # Static assets
│
├── hive/               # Backend (Node.js + TypeScript + Express)
│   └── src/
│       ├── controllers/ # Request handlers
│       ├── middleware/  # Express middleware
│       ├── models/      # Data models
│       ├── routes/      # API routes
│       ├── services/    # Business logic
│       ├── types/       # TypeScript types
│       └── utils/       # Utility functions
│
├── docs/               # Documentation
├── scripts/            # Build and utility scripts
└── config.yaml         # Application configuration
```

## AI Agent Tools Setup (Optional)

If you're using the AI agent framework with tools:

```bash
# 1. Navigate to tools
cd tools

# 2. Copy environment template
cp .env.example .env

# 3. Add your API keys to .env
# - ANTHROPIC_API_KEY: Required for LLM operations
# - BRAVE_SEARCH_API_KEY: Required for web search tool
```

Get your API keys:

- **Anthropic**: [console.anthropic.com](https://console.anthropic.com/)
- **Brave Search**: [brave.com/search/api](https://brave.com/search/api/)

## Next Steps

1. **Configure the Application**: See [Configuration Guide](configuration.md)
2. **Understand the Architecture**: See [Architecture Overview](architecture.md)
3. **Start Building**: Add your own components and API endpoints

## Troubleshooting

### Port Already in Use

If ports 3000 or 4000 are in use, update `config.yaml`:

```yaml
server:
  frontend:
    port: 3001 # Change to available port
  backend:
    port: 4001
```

Then regenerate environment files:

```bash
npm run generate:env
```

### Docker Build Fails

Clear Docker cache and rebuild:

```bash
docker compose down
docker compose build --no-cache
docker compose up
```

### Dependencies Issues

Clear node_modules and reinstall:

```bash
npm run clean
npm install
```
