# Developer Guide

This comprehensive guide covers everything you need to know to work on the Hive monorepo effectively.

## Table of Contents

1. [Repository Overview](#repository-overview)
2. [Initial Setup](#initial-setup)
3. [Project Structure](#project-structure)
4. [Configuration System](#configuration-system)
5. [Development Workflow](#development-workflow)
6. [Working with the Frontend (honeycomb)](#working-with-the-frontend-honeycomb)
7. [Working with the Backend (hive)](#working-with-the-backend-hive)
8. [Docker Development](#docker-development)
9. [Testing](#testing)
10. [Code Style & Conventions](#code-style--conventions)
11. [Git Workflow](#git-workflow)
12. [Debugging](#debugging)
13. [Common Tasks](#common-tasks)
14. [Troubleshooting](#troubleshooting)

---

## Repository Overview

Hive is a monorepo containing two main packages:

| Package       | Directory    | Description              | Tech Stack                   |
| ------------- | ------------ | ------------------------ | ---------------------------- |
| **honeycomb** | `/honeycomb` | Frontend web application | React 18, TypeScript, Vite   |
| **hive**      | `/hive`      | Backend API server       | Node.js, Express, TypeScript |

The repository uses **npm workspaces** to manage dependencies across packages from a single root `package.json`.

### Key Principles

- **Single source of configuration**: Edit `config.yaml` once, environment files are auto-generated
- **Consistent tooling**: Both packages use TypeScript with strict mode
- **Docker-first**: Production deployments use containerized builds
- **Developer ergonomics**: Hot reload, clear error messages, minimal setup

---

## Initial Setup

### Prerequisites

Ensure you have installed:

- **Node.js v20+** - [Download](https://nodejs.org/) or use nvm: `nvm install 20`
- **npm v10+** - Comes with Node.js 20
- **Docker v20.10+** - [Download](https://docs.docker.com/get-docker/)
- **Docker Compose v2+** - Included with Docker Desktop

Verify installation:

```bash
node --version    # Should be v20.x.x
npm --version     # Should be 10.x.x
docker --version  # Should be 20.10+
docker compose version  # Should be v2.x.x
```

### Step-by-Step Setup

```bash
# 1. Clone the repository
git clone https://github.com/adenhq/hive.git
cd hive

# 2. Create your configuration file
cp config.yaml.example config.yaml

# 3. (Optional) Edit config.yaml with your settings
#    Most defaults work out of the box

# 4. Run the automated setup
npm run setup
```

The `setup` script performs these actions:

1. Installs all dependencies for root, honeycomb, and hive
2. Generates `.env` files from your `config.yaml`
3. Reports any issues

### AI Agent Tools (Optional)

If working with the agent framework:

```bash
# Set up tools credentials
cd tools
cp .env.example .env
# Edit .env with your ANTHROPIC_API_KEY and BRAVE_SEARCH_API_KEY
```

### Verify Setup

```bash
# Build both packages to verify everything works
npm run build

# Or run in development mode
npm run dev -w honeycomb  # Terminal 1: Frontend at http://localhost:3000
npm run dev -w hive       # Terminal 2: Backend at http://localhost:4000
```

---

## Project Structure

```
hive/                            # Repository root
│
├── .github/                        # GitHub configuration
│   ├── workflows/
│   │   ├── ci.yml                  # Runs on every PR: lint, test, build
│   │   └── release.yml             # Runs on tags: publish Docker images
│   ├── ISSUE_TEMPLATE/             # Bug report & feature request templates
│   ├── PULL_REQUEST_TEMPLATE.md    # PR description template
│   └── CODEOWNERS                  # Auto-assign reviewers
│
├── docs/                           # Documentation
│   ├── getting-started.md          # Quick start guide
│   ├── configuration.md            # Configuration reference
│   └── architecture.md             # System architecture
│
├── honeycomb/                      # FRONTEND PACKAGE
│   ├── src/
│   │   ├── components/             # Reusable UI components
│   │   ├── hooks/                  # Custom React hooks
│   │   │   └── useApi.ts           # Hook for API calls
│   │   ├── pages/                  # Route-level page components
│   │   │   ├── HomePage.tsx
│   │   │   └── NotFoundPage.tsx
│   │   ├── services/               # External service clients
│   │   │   └── api.ts              # Backend API client
│   │   ├── styles/                 # Global CSS
│   │   │   └── index.css
│   │   ├── types/                  # TypeScript type definitions
│   │   │   └── index.ts
│   │   ├── utils/                  # Utility functions
│   │   │   └── index.ts
│   │   ├── App.tsx                 # Root component with routing
│   │   ├── main.tsx                # Application entry point
│   │   └── vite-env.d.ts           # Vite type declarations
│   ├── public/                     # Static assets (copied as-is)
│   │   └── favicon.svg
│   ├── index.html                  # HTML template
│   ├── nginx.conf                  # Production nginx config
│   ├── package.json                # Package dependencies & scripts
│   ├── tsconfig.json               # TypeScript configuration
│   ├── tsconfig.node.json          # TypeScript config for Vite
│   ├── vite.config.ts              # Vite bundler configuration
│   ├── Dockerfile                  # Production Docker build
│   ├── Dockerfile.dev              # Development Docker build
│   └── .env.example                # Environment variable template
│
├── hive/                           # BACKEND PACKAGE
│   ├── src/
│   │   ├── config/                 # Configuration loading
│   │   │   └── index.ts            # Env var parsing & validation
│   │   ├── controllers/            # Request handlers (business logic)
│   │   ├── middleware/             # Express middleware
│   │   │   └── errorHandler.ts     # Global error handling
│   │   ├── models/                 # Data models / database schemas
│   │   ├── routes/                 # API route definitions
│   │   │   ├── api.ts              # /api/* routes
│   │   │   └── health.ts           # Health check endpoints
│   │   ├── services/               # Business logic services
│   │   ├── types/                  # TypeScript type definitions
│   │   │   └── index.ts
│   │   ├── utils/                  # Utility functions
│   │   │   └── logger.ts           # Structured logging
│   │   ├── index.ts                # Application entry point
│   │   └── server.ts               # Express server setup
│   ├── package.json                # Package dependencies & scripts
│   ├── tsconfig.json               # TypeScript configuration
│   ├── Dockerfile                  # Production Docker build
│   ├── Dockerfile.dev              # Development Docker build
│   └── .env.example                # Environment variable template
│
├── scripts/                        # Build & utility scripts
│   ├── setup.sh                    # First-time setup script
│   └── generate-env.ts             # Generates .env from config.yaml
│
├── config.yaml.example             # Configuration template (copy to config.yaml)
├── config.yaml                     # Your local configuration (git-ignored)
├── docker-compose.yml              # Production Docker Compose
├── docker-compose.override.yml.example  # Dev overrides template
├── docker-compose.override.yml     # Your local dev overrides (git-ignored)
│
├── package.json                    # Root package.json (workspaces config)
├── package-lock.json               # Dependency lock file
├── tsconfig.base.json              # Shared TypeScript settings
│
├── .gitignore                      # Git ignore rules
├── .editorconfig                   # Editor formatting rules
├── .dockerignore                   # Docker ignore rules
│
├── README.md                       # Project overview
├── DEVELOPER.md                    # This file
├── CONTRIBUTING.md                 # Contribution guidelines
├── CHANGELOG.md                    # Version history
├── LICENSE                         # Apache 2.0 License
├── CODE_OF_CONDUCT.md              # Community guidelines
└── SECURITY.md                     # Security policy
```

---

## Configuration System

### How It Works

Instead of managing multiple `.env` files, you edit a single `config.yaml`:

```
┌─────────────────┐
│  config.yaml    │  ← You edit this one file
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ generate-env.ts │  ← Script transforms YAML to .env
└────────┬────────┘
         │
         ├──────────────────┬──────────────────┐
         ▼                  ▼                  ▼
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│     /.env       │ │ /honeycomb/.env │ │   /hive/.env    │
│  (Docker Compose)│ │   (Frontend)    │ │   (Backend)     │
└─────────────────┘ └─────────────────┘ └─────────────────┘
```

### Configuration Reference

The `config.yaml` file structure:

```yaml
# ===========================================
# Application Configuration
# ===========================================

# Application metadata
app:
  name: hive # Used in logs and API responses
  environment: development # development | staging | production

# Server configuration
server:
  frontend:
    port: 3000 # Frontend port
    host: "0.0.0.0" # Bind address
  backend:
    port: 4000 # Backend API port
    host: "0.0.0.0" # Bind address

# API configuration
api:
  prefix: /api # API route prefix
  cors:
    origins: # Allowed CORS origins
      - "http://localhost:3000"
      - "http://localhost:4000"

# Logging configuration
logging:
  level: debug # debug | info | warn | error
  format: pretty # pretty | json

# Security settings
security:
  jwt:
    secret: "change-me-in-production-use-min-32-chars"
    expiresIn: "7d" # Token expiration

# Database configuration (when needed)
database:
  host: localhost
  port: 5432
  name: hive
  user: postgres
  password: postgres

# Feature flags (optional)
features:
  enableMetrics: true
  enableSwagger: true
```

### Regenerating Environment Files

After editing `config.yaml`, regenerate the `.env` files:

```bash
npm run generate:env
```

This is required because:

- Docker Compose reads from `.env` files
- Vite reads frontend env vars from `/honeycomb/.env`
- Node.js reads backend env vars from `/hive/.env`

---

## Development Workflow

### Option 1: Local Development (Recommended for Active Development)

Best for rapid iteration with instant hot reload:

```bash
# Terminal 1: Start frontend
npm run dev -w honeycomb

# Terminal 2: Start backend
npm run dev -w hive
```

| Service    | URL                          | Hot Reload      |
| ---------- | ---------------------------- | --------------- |
| Frontend   | http://localhost:3000        | Yes (Vite HMR)  |
| Backend    | http://localhost:4000        | Yes (tsx watch) |
| API Health | http://localhost:4000/health | -               |

### Option 2: Docker Development

Best for testing Docker builds or when you need consistent environments:

```bash
# Copy development overrides
cp docker-compose.override.yml.example docker-compose.override.yml

# Start containers with hot reload
docker compose up

# Or in detached mode
docker compose up -d

# View logs
docker compose logs -f

# Stop containers
docker compose down
```

### Option 3: Mixed Mode

Run backend in Docker, frontend locally (useful for frontend-focused work):

```bash
# Start only backend in Docker
docker compose up hive -d

# Run frontend locally
npm run dev -w honeycomb
```

### Available NPM Scripts

**Root level** (run from repository root):

| Command                      | Description                               |
| ---------------------------- | ----------------------------------------- |
| `npm run setup`              | First-time setup (install + generate env) |
| `npm run generate:env`       | Regenerate .env files from config.yaml    |
| `npm run build`              | Build all packages                        |
| `npm run build -w honeycomb` | Build frontend only                       |
| `npm run build -w hive`      | Build backend only                        |
| `npm run lint`               | Lint all packages                         |
| `npm run test`               | Run all tests                             |
| `npm run clean`              | Remove node_modules and build artifacts   |

**Frontend** (`/honeycomb`):

| Command                 | Description                         |
| ----------------------- | ----------------------------------- |
| `npm run dev`           | Start Vite dev server with HMR      |
| `npm run build`         | Type-check and build for production |
| `npm run preview`       | Preview production build locally    |
| `npm run lint`          | Lint with ESLint                    |
| `npm run test`          | Run tests with Vitest               |
| `npm run test:coverage` | Run tests with coverage report      |

**Backend** (`/hive`):

| Command                 | Description                       |
| ----------------------- | --------------------------------- |
| `npm run dev`           | Start with hot reload (tsx watch) |
| `npm run build`         | Compile TypeScript to JavaScript  |
| `npm run start`         | Run compiled JavaScript           |
| `npm run lint`          | Lint with ESLint                  |
| `npm run test`          | Run tests with Vitest             |
| `npm run test:coverage` | Run tests with coverage report    |

---

## Working with the Frontend (honeycomb)

### Tech Stack

- **React 18** - UI library with hooks
- **TypeScript** - Type safety
- **Vite** - Build tool with instant HMR
- **React Router v6** - Client-side routing
- **Vitest** - Testing framework

### Adding a New Page

1. Create the page component:

```tsx
// honeycomb/src/pages/UsersPage.tsx
import { useEffect, useState } from "react";
import { useApi } from "../hooks/useApi";

export function UsersPage() {
  const { data, loading, error } = useApi<User[]>("/api/users");

  if (loading) return <div>Loading...</div>;
  if (error) return <div>Error: {error.message}</div>;

  return (
    <div>
      <h1>Users</h1>
      <ul>
        {data?.map((user) => (
          <li key={user.id}>{user.name}</li>
        ))}
      </ul>
    </div>
  );
}
```

2. Add the route in `App.tsx`:

```tsx
// honeycomb/src/App.tsx
import { UsersPage } from "./pages/UsersPage";

// Inside Routes:
<Route path="/users" element={<UsersPage />} />;
```

### Adding a New Component

```tsx
// honeycomb/src/components/Button.tsx
interface ButtonProps {
  children: React.ReactNode;
  onClick?: () => void;
  variant?: "primary" | "secondary";
}

export function Button({
  children,
  onClick,
  variant = "primary",
}: ButtonProps) {
  return (
    <button className={`btn btn-${variant}`} onClick={onClick}>
      {children}
    </button>
  );
}
```

### Making API Calls

Use the provided `useApi` hook or the `api` service:

```tsx
// Using the hook (recommended for components)
import { useApi } from "../hooks/useApi";

function MyComponent() {
  const { data, loading, error, refetch } = useApi<MyData>("/api/endpoint");
  // ...
}

// Using the service directly (for non-component code)
import { api } from "../services/api";

async function fetchData() {
  const response = await api.get("/api/endpoint");
  return response.data;
}
```

### Environment Variables in Frontend

Access environment variables using `import.meta.env`:

```tsx
// Only VITE_* prefixed variables are exposed to the frontend
const apiUrl = import.meta.env.VITE_API_URL;
const appName = import.meta.env.VITE_APP_NAME;
```

**Important**: Never put secrets in frontend environment variables. They are bundled into the JavaScript and visible to users.

### Path Aliases

Use `@/` to import from the `src` directory:

```tsx
// Instead of:
import { Button } from "../../../components/Button";

// Use:
import { Button } from "@/components/Button";
```

---

## Working with the Backend (hive)

### Tech Stack

- **Node.js 20** - Runtime
- **Express** - Web framework
- **TypeScript** - Type safety
- **tsx** - TypeScript execution with hot reload
- **Zod** - Runtime validation (recommended)
- **Vitest** - Testing framework

### Adding a New API Endpoint

1. Create the route file:

```typescript
// hive/src/routes/users.ts
import { Router } from "express";
import type { Request, Response } from "express";

const router = Router();

// GET /api/users
router.get("/", async (req: Request, res: Response) => {
  try {
    const users = await getUsersFromDatabase();
    res.json(users);
  } catch (error) {
    res.status(500).json({ error: "Failed to fetch users" });
  }
});

// GET /api/users/:id
router.get("/:id", async (req: Request, res: Response) => {
  const { id } = req.params;
  try {
    const user = await getUserById(id);
    if (!user) {
      return res.status(404).json({ error: "User not found" });
    }
    res.json(user);
  } catch (error) {
    res.status(500).json({ error: "Failed to fetch user" });
  }
});

// POST /api/users
router.post("/", async (req: Request, res: Response) => {
  const { name, email } = req.body;
  try {
    const user = await createUser({ name, email });
    res.status(201).json(user);
  } catch (error) {
    res.status(500).json({ error: "Failed to create user" });
  }
});

export default router;
```

2. Register the route in `api.ts`:

```typescript
// hive/src/routes/api.ts
import usersRouter from "./users";

// Add to the router:
router.use("/users", usersRouter);
```

### Request Validation with Zod

```typescript
// hive/src/routes/users.ts
import { z } from "zod";

const createUserSchema = z.object({
  name: z.string().min(1).max(100),
  email: z.string().email(),
  age: z.number().int().positive().optional(),
});

router.post("/", async (req: Request, res: Response) => {
  const result = createUserSchema.safeParse(req.body);

  if (!result.success) {
    return res.status(400).json({
      error: "Validation failed",
      details: result.error.issues,
    });
  }

  const { name, email, age } = result.data;
  // ... create user
});
```

### Adding Middleware

```typescript
// hive/src/middleware/auth.ts
import type { Request, Response, NextFunction } from "express";

export function requireAuth(req: Request, res: Response, next: NextFunction) {
  const token = req.headers.authorization?.replace("Bearer ", "");

  if (!token) {
    return res.status(401).json({ error: "Authentication required" });
  }

  try {
    const decoded = verifyToken(token);
    req.user = decoded;
    next();
  } catch {
    res.status(401).json({ error: "Invalid token" });
  }
}

// Usage in routes:
router.get("/protected", requireAuth, (req, res) => {
  res.json({ user: req.user });
});
```

### Logging

Use the built-in logger for consistent structured logging:

```typescript
import { logger } from "../utils/logger";

// Different log levels
logger.debug("Detailed debug info", { userId: 123 });
logger.info("User logged in", { userId: 123 });
logger.warn("Rate limit approaching", { currentRate: 95 });
logger.error("Database connection failed", { error: err.message });
```

### Environment Variables in Backend

Access via `process.env` or the config module:

```typescript
// Direct access
const port = process.env.PORT || 4000;

// Or via config (recommended - adds validation)
import { config } from "../config";
const port = config.port;
```

---

## Docker Development

### Docker Compose Files

| File                          | Purpose                                         |
| ----------------------------- | ----------------------------------------------- |
| `docker-compose.yml`          | Base configuration (production-like)            |
| `docker-compose.override.yml` | Development overrides (hot reload, debug ports) |

When you run `docker compose up`, Docker automatically merges both files.

### Building Images

```bash
# Build all images
docker compose build

# Build specific service
docker compose build honeycomb
docker compose build hive

# Build with no cache (fresh build)
docker compose build --no-cache
```

### Running Containers

```bash
# Start all services
docker compose up

# Start in background
docker compose up -d

# Start specific service
docker compose up hive

# View logs
docker compose logs -f
docker compose logs -f hive  # Specific service

# Stop all services
docker compose down

# Stop and remove volumes
docker compose down -v
```

### Debugging in Docker

The development override exposes debug ports:

- **Backend debug port**: 9229 (Node.js inspector)

To debug the backend in VS Code:

1. Add to `.vscode/launch.json`:

```json
{
  "version": "0.2.0",
  "configurations": [
    {
      "name": "Attach to Docker",
      "type": "node",
      "request": "attach",
      "port": 9229,
      "address": "localhost",
      "localRoot": "${workspaceFolder}/hive",
      "remoteRoot": "/app",
      "restart": true
    }
  ]
}
```

2. Start containers: `docker compose up`
3. In VS Code, press F5 or select "Attach to Docker"

### Useful Docker Commands

```bash
# Execute command in running container
docker compose exec hive sh
docker compose exec honeycomb sh

# View container resource usage
docker stats

# Remove all stopped containers
docker container prune

# Remove unused images
docker image prune
```

---

## Testing

### Running Tests

```bash
# Run all tests
npm run test

# Run tests for specific package
npm run test -w honeycomb
npm run test -w hive

# Run with coverage
npm run test:coverage -w honeycomb
npm run test:coverage -w hive

# Run in watch mode (re-runs on file changes)
cd honeycomb && npm run test -- --watch
cd hive && npm run test -- --watch
```

### Writing Frontend Tests

```tsx
// honeycomb/src/components/Button.test.tsx
import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { Button } from "./Button";

describe("Button", () => {
  it("renders children", () => {
    render(<Button>Click me</Button>);
    expect(screen.getByText("Click me")).toBeInTheDocument();
  });

  it("calls onClick when clicked", () => {
    const handleClick = vi.fn();
    render(<Button onClick={handleClick}>Click me</Button>);

    fireEvent.click(screen.getByText("Click me"));

    expect(handleClick).toHaveBeenCalledTimes(1);
  });
});
```

### Writing Backend Tests

```typescript
// hive/src/routes/health.test.ts
import { describe, it, expect } from "vitest";
import request from "supertest";
import { app } from "../server";

describe("Health Routes", () => {
  it("GET /health returns healthy status", async () => {
    const response = await request(app).get("/health");

    expect(response.status).toBe(200);
    expect(response.body).toMatchObject({
      status: "healthy",
    });
  });

  it("GET /health/ready returns ready status", async () => {
    const response = await request(app).get("/health/ready");

    expect(response.status).toBe(200);
    expect(response.body.ready).toBe(true);
  });
});
```

---

## Code Style & Conventions

### TypeScript

- **Strict mode enabled** - No implicit any, strict null checks
- **Explicit return types** on exported functions
- **Interface over type** for object shapes (unless unions needed)
- **Readonly** where possible

```typescript
// Good
interface User {
  readonly id: string;
  name: string;
  email: string;
}

export function getUser(id: string): Promise<User | null> {
  // ...
}

// Avoid
export function getUser(id) {
  // Missing types
  // ...
}
```

### React Components

- **Functional components** only (no class components)
- **Named exports** for components
- **Props interface** defined above component

```tsx
// Good
interface ButtonProps {
  children: React.ReactNode;
  onClick?: () => void;
}

export function Button({ children, onClick }: ButtonProps) {
  return <button onClick={onClick}>{children}</button>;
}

// Avoid
export default function ({ children, onClick }) {
  // Missing types, default export
  return <button onClick={onClick}>{children}</button>;
}
```

### File Naming

| Type       | Convention                  | Example                          |
| ---------- | --------------------------- | -------------------------------- |
| Components | PascalCase                  | `UserCard.tsx`                   |
| Hooks      | camelCase with `use` prefix | `useAuth.ts`                     |
| Utilities  | camelCase                   | `formatDate.ts`                  |
| Types      | PascalCase                  | `User.ts` or in `types/index.ts` |
| Tests      | Same as file + `.test`      | `UserCard.test.tsx`              |
| Styles     | Same as component           | `UserCard.css`                   |

### Import Order

1. External packages
2. Internal absolute imports (`@/...`)
3. Relative imports
4. Style imports

```tsx
// External
import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";

// Internal absolute
import { Button } from "@/components/Button";
import { useApi } from "@/hooks/useApi";

// Relative
import { formatUserName } from "./utils";

// Styles
import "./UserCard.css";
```

---

## Git Workflow

### Branch Naming

```
feature/add-user-authentication
bugfix/fix-login-redirect
hotfix/security-patch
chore/update-dependencies
docs/improve-readme
```

### Commit Messages

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <description>

[optional body]

[optional footer]
```

**Types:**

- `feat` - New feature
- `fix` - Bug fix
- `docs` - Documentation only
- `style` - Formatting, missing semicolons, etc.
- `refactor` - Code change that neither fixes a bug nor adds a feature
- `test` - Adding or updating tests
- `chore` - Maintenance tasks

**Examples:**

```
feat(auth): add JWT authentication

fix(api): handle null response from external service

docs(readme): update installation instructions

chore(deps): update React to 18.2.0
```

### Pull Request Process

1. Create a feature branch from `main`
2. Make your changes with clear commits
3. Run tests locally: `npm run test`
4. Run linting: `npm run lint`
5. Push and create a PR
6. Fill out the PR template
7. Request review from CODEOWNERS
8. Address feedback
9. Squash and merge when approved

---

## Debugging

### Frontend Debugging

**React Developer Tools:**

1. Install the [React DevTools browser extension](https://react.dev/learn/react-developer-tools)
2. Open browser DevTools → React tab
3. Inspect component tree, props, state, and hooks

**VS Code Debugging:**

1. Add Chrome debug configuration to `.vscode/launch.json`:

```json
{
  "type": "chrome",
  "request": "launch",
  "name": "Debug Frontend",
  "url": "http://localhost:3000",
  "webRoot": "${workspaceFolder}/honeycomb/src"
}
```

2. Start the dev server: `npm run dev -w honeycomb`
3. Press F5 in VS Code

### Backend Debugging

**VS Code Debugging:**

1. Add Node debug configuration:

```json
{
  "type": "node",
  "request": "launch",
  "name": "Debug Backend",
  "runtimeExecutable": "npm",
  "runtimeArgs": ["run", "dev"],
  "cwd": "${workspaceFolder}/hive",
  "console": "integratedTerminal"
}
```

2. Set breakpoints in your code
3. Press F5 to start debugging

**Logging:**

```typescript
import { logger } from "../utils/logger";

// Add debug logs
logger.debug("Processing request", {
  userId: req.user.id,
  body: req.body,
});
```

---

## Common Tasks

### Adding a New Dependency

```bash
# Add to frontend
npm install <package> -w honeycomb

# Add to backend
npm install <package> -w hive

# Add dev dependency
npm install -D <package> -w honeycomb

# Add to root (shared tooling)
npm install -D <package> -w .
```

### Updating Dependencies

```bash
# Check for outdated packages
npm outdated

# Update all to latest minor/patch
npm update

# Update specific package
npm install <package>@latest -w honeycomb
```

### Adding Environment Variables

1. Add to `config.yaml.example` (template):

```yaml
myService:
  apiKey: "your-api-key-here"
```

2. Add to your local `config.yaml`:

```yaml
myService:
  apiKey: "actual-api-key"
```

3. Update `scripts/generate-env.ts` to output the new variable

4. Regenerate env files:

```bash
npm run generate:env
```

5. Access in code:

```typescript
// Backend
const apiKey = process.env.MY_SERVICE_API_KEY;

// Frontend (must be prefixed with VITE_)
const apiKey = import.meta.env.VITE_MY_SERVICE_API_KEY;
```

### Database Migrations (when added)

```bash
# Create a new migration
npm run migration:create -w hive -- --name add-users-table

# Run pending migrations
npm run migration:run -w hive

# Rollback last migration
npm run migration:rollback -w hive
```

---

## Troubleshooting

### Port Already in Use

```bash
# Find process using port
lsof -i :3000
lsof -i :4000

# Kill process
kill -9 <PID>

# Or change ports in config.yaml and regenerate
```

### Node Modules Issues

```bash
# Clean everything and reinstall
npm run clean
rm -rf node_modules package-lock.json
npm install
```

### Docker Issues

```bash
# Reset Docker state
docker compose down -v
docker system prune -f
docker compose build --no-cache
docker compose up
```

### TypeScript Errors After Pull

```bash
# Rebuild TypeScript
npm run build

# Or restart TS server in VS Code
# Cmd/Ctrl + Shift + P → "TypeScript: Restart TS Server"
```

### Environment Variables Not Loading

```bash
# Regenerate from config.yaml
npm run generate:env

# Verify files exist
cat .env
cat honeycomb/.env
cat hive/.env

# Restart dev servers after changing env
```

### Tests Failing

```bash
# Run with verbose output
npm run test -w honeycomb -- --reporter=verbose

# Run single test file
npm run test -w honeycomb -- src/components/Button.test.tsx

# Clear test cache
npm run test -w honeycomb -- --clearCache
```

---

## Getting Help

- **Documentation**: Check the `/docs` folder
- **Issues**: Search [existing issues](https://github.com/adenhq/hive/issues)
- **Discord**: Join our [community](https://discord.com/invite/MXE49hrKDk)
- **Code Review**: Tag a maintainer on your PR

---

_Happy coding!_ 🐝
