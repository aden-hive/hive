#!/bin/bash
# Hive Setup Script
# This script sets up the project for first-time use

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "==================================="
echo "  Hive Setup"
echo "==================================="
echo ""

# Check for Node.js
if ! command -v node &> /dev/null; then
    echo "Error: Node.js is not installed."
    echo "Please install Node.js 20+ from https://nodejs.org"
    exit 1
fi

NODE_VERSION=$(node -v | cut -d'v' -f2 | cut -d'.' -f1)
if [ "$NODE_VERSION" -lt 20 ]; then
    echo "Error: Node.js 20+ is required (found v$NODE_VERSION)"
    exit 1
fi

echo "✓ Node.js $(node -v) detected"

# Check for Docker (optional)
if command -v docker &> /dev/null; then
    echo "✓ Docker $(docker --version | cut -d' ' -f3 | tr -d ',') detected"
else
    echo "⚠ Docker not found (optional, needed for containerized deployment)"
fi

echo ""

# Create config.yaml if it doesn't exist
if [ ! -f "$PROJECT_ROOT/config.yaml" ]; then
    echo "Creating config.yaml from template..."
    cp "$PROJECT_ROOT/config.yaml.example" "$PROJECT_ROOT/config.yaml"
    echo "✓ Created config.yaml"
    echo ""
    echo "  Please review and edit config.yaml with your settings."
    echo ""
else
    echo "✓ config.yaml already exists"
fi

# Install dependencies
echo ""
echo "Installing dependencies..."
cd "$PROJECT_ROOT"
npm install
echo "✓ Dependencies installed"

# Generate environment files
echo ""
echo "Generating environment files from config.yaml..."
npx tsx scripts/generate-env.ts
echo "✓ Environment files generated"

# Create docker-compose.override.yml for development
if [ ! -f "$PROJECT_ROOT/docker-compose.override.yml" ]; then
    cp "$PROJECT_ROOT/docker-compose.override.yml.example" "$PROJECT_ROOT/docker-compose.override.yml"
    echo "✓ Created docker-compose.override.yml for development"
fi

echo ""
echo "==================================="
echo "  Setup Complete!"
echo "==================================="
echo ""
echo "Next steps:"
echo "  1. Review config.yaml and update settings as needed"
echo "  2. Run 'npm run generate:env' if you modify config.yaml"
echo "  3. Start the application:"
echo ""
echo "     With Docker:    docker compose up"
echo "     Without Docker: npm run dev (in each package)"
echo ""
echo "  Frontend: http://localhost:3000"
echo "  Backend:  http://localhost:4000"
echo ""
