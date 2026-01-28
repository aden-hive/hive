# Configuration Guide

Hive uses a centralized configuration system based on a single `config.yaml` file. This makes it easy to configure the entire application from one place.

## Configuration Flow

```
config.yaml  -->  generate-env.ts  -->  .env files
                                        ├── .env (root)
                                        ├── honeycomb/.env (frontend)
                                        └── hive/.env (backend)
```

## Getting Started

1. Copy the example configuration:
   ```bash
   cp config.yaml.example config.yaml
   ```

2. Edit `config.yaml` with your settings

3. Generate environment files:
   ```bash
   npm run generate:env
   ```

## Configuration Options

### Application Settings

```yaml
app:
  # Application name - displayed in UI and logs
  name: Hive

  # Environment mode
  # - development: enables debug features, verbose logging
  # - production: optimized for performance, minimal logging
  # - test: for running tests
  environment: development

  # Log level: debug, info, warn, error
  log_level: info
```

### Server Configuration

```yaml
server:
  frontend:
    # Port for the React frontend
    port: 3000

  backend:
    # Port for the Node.js API
    port: 4000

    # Host to bind (0.0.0.0 = all interfaces)
    host: 0.0.0.0
```

### Database Configuration

```yaml
database:
  # PostgreSQL connection URL
  url: postgresql://user:password@localhost:5432/hive

  # For SQLite (local development)
  # url: sqlite:./data/hive.db
```

**Connection URL Format:**
```
postgresql://[user]:[password]@[host]:[port]/[database]
```

### Authentication

```yaml
auth:
  # JWT secret key for signing tokens
  # IMPORTANT: Change this in production!
  # Generate with: openssl rand -base64 32
  jwt_secret: your-secret-key

  # Token expiration time
  # Examples: 1h, 7d, 30d
  jwt_expires_in: 7d
```

### CORS Configuration

```yaml
cors:
  # Allowed origin for cross-origin requests
  # Set to your frontend URL in production
  origin: http://localhost:3000
```

### Feature Flags

```yaml
features:
  # Enable/disable user registration
  registration: true

  # Enable API rate limiting
  rate_limiting: false

  # Enable request logging
  request_logging: true
```

## Environment-Specific Configuration

You can create environment-specific config files:

- `config.yaml` - Your main configuration (git-ignored)
- `config.yaml.example` - Template with safe defaults (committed)

For different environments, you might want separate files:

```bash
# Development
cp config.yaml.example config.yaml
# Edit for development settings

# Production
cp config.yaml.example config.production.yaml
# Edit for production settings
```

## Security Best Practices

1. **Never commit `config.yaml`** - It may contain secrets
2. **Use strong JWT secrets** - Generate with `openssl rand -base64 32`
3. **Restrict CORS in production** - Set to your exact frontend URL
4. **Use environment variables for CI/CD** - Override config in deployments

## Updating Configuration

After changing `config.yaml`:

```bash
# Regenerate .env files
npm run generate:env
```

## Troubleshooting

### Changes Not Taking Effect

1. Ensure you ran `npm run generate:env`
2. Restart the services
3. Check if the correct `.env` file is being loaded

### Configuration Validation Errors

The backend validates configuration on startup. Check logs for specific errors.

### Missing Environment Variables

If a required variable is missing, add it to:
1. `config.yaml.example` (with safe default)
2. `config.yaml` (with your value)
3. `scripts/generate-env.ts` (to generate it)
