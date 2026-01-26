/**
 * Environment Generator Script
 *
 * Reads config.yaml and generates .env files for each service.
 * This provides a single source of truth for configuration while
 * maintaining compatibility with standard .env file workflows.
 *
 * Usage: npx tsx scripts/generate-env.ts
 */

import { readFileSync, writeFileSync, existsSync, mkdirSync } from 'fs';
import { parse } from 'yaml';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const PROJECT_ROOT = join(__dirname, '..');

interface Config {
  app: {
    name: string;
    environment: string;
    log_level: string;
  };
  server: {
    frontend: {
      port: number;
    };
    backend: {
      port: number;
      host: string;
    };
  };
  postgresql: {
    url: string;
    port: number;
    database: string;
  };
  redis: {
    url: string;
    port: number;
  };
  auth: {
    jwt_secret: string;
    jwt_expires_in: string;
    passphrase: string;
  };
  npm: {
    token: string;
  };
  cors: {
    origin: string;
  };
  features: {
    registration: boolean;
    rate_limiting: boolean;
    request_logging: boolean;
    mcp_server: boolean;
  };
}

function loadConfig(): Config {
  const configPath = join(PROJECT_ROOT, 'config.yaml');

  if (!existsSync(configPath)) {
    console.error('Error: config.yaml not found.');
    console.error('Run: cp config.yaml.example config.yaml');
    process.exit(1);
  }

  const configContent = readFileSync(configPath, 'utf-8');
  return parse(configContent) as Config;
}

function generateRootEnv(config: Config): string {
  return `# Generated from config.yaml - do not edit directly
# Regenerate with: npm run generate:env

# Application
NODE_ENV=${config.app.environment}
APP_NAME=${config.app.name}
LOG_LEVEL=${config.app.log_level}

# Ports
FRONTEND_PORT=${config.server.frontend.port}
BACKEND_PORT=${config.server.backend.port}
POSTGRES_PORT=${config.postgresql.port}
REDIS_PORT=${config.redis.port}

# API URL for frontend
VITE_API_URL=http://localhost:${config.server.backend.port}

# PostgreSQL
POSTGRES_DBNAME=${config.postgresql.database}

# Authentication
JWT_SECRET=${config.auth.jwt_secret}
PASSPHRASE=${config.auth.passphrase}

# NPM (for Docker builds with private packages)
NPM_TOKEN=${config.npm.token}

# CORS
CORS_ORIGIN=${config.cors.origin}
`;
}

function generateFrontendEnv(config: Config): string {
  return `# Generated from config.yaml - do not edit directly
# Regenerate with: npm run generate:env

VITE_API_URL=http://localhost:${config.server.backend.port}
VITE_APP_NAME=${config.app.name}
VITE_APP_ENV=${config.app.environment}
`;
}

function generateBackendEnv(config: Config): string {
  return `# Generated from config.yaml - do not edit directly
# Regenerate with: npm run generate:env

# Server
NODE_ENV=${config.app.environment}
PORT=${config.server.backend.port}

# Application
LOG_LEVEL=${config.app.log_level}

# PostgreSQL
POSTGRES_URL=${config.postgresql.url}
POSTGRES_DBNAME=${config.postgresql.database}

# Redis
REDIS_URL=${config.redis.url}

# Authentication
JWT_SECRET=${config.auth.jwt_secret}
PASSPHRASE=${config.auth.passphrase}

# Features
FEATURE_MCP_SERVER=${config.features.mcp_server}
`;
}

function ensureDirectoryExists(filePath: string): void {
  const dirPath = dirname(filePath);
  if (!existsSync(dirPath)) {
    mkdirSync(dirPath, { recursive: true });
  }
}

function main() {
  console.log('Generating environment files from config.yaml...\n');

  const config = loadConfig();

  // Generate root .env (for docker-compose)
  const rootEnvPath = join(PROJECT_ROOT, '.env');
  writeFileSync(rootEnvPath, generateRootEnv(config));
  console.log(`✓ Generated ${rootEnvPath}`);

  // Generate frontend .env
  const frontendEnvPath = join(PROJECT_ROOT, 'honeycomb', '.env');
  ensureDirectoryExists(frontendEnvPath);
  writeFileSync(frontendEnvPath, generateFrontendEnv(config));
  console.log(`✓ Generated ${frontendEnvPath}`);

  // Generate backend .env
  const backendEnvPath = join(PROJECT_ROOT, 'hive', '.env');
  ensureDirectoryExists(backendEnvPath);
  writeFileSync(backendEnvPath, generateBackendEnv(config));
  console.log(`✓ Generated ${backendEnvPath}`);

  console.log('\nDone! Environment files have been generated.');
  console.log('\nNote: These files are git-ignored. Regenerate after editing config.yaml.');
}

main();
