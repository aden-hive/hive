#!/bin/bash
# Legacy Web Application Setup Script
# NOTE: This script is for the archived honeycomb/hive web application.
# For agent development, use: ./scripts/setup-python.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "==================================="
echo "  Legacy Web App Setup (Archived)"
echo "==================================="
echo ""
echo "⚠️  This script is for the archived web application."
echo "    For agent development, use: ./scripts/setup-python.sh"
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
echo "  Setup Complete (Legacy)"
echo "==================================="
echo ""
echo "⚠️  NOTE: The honeycomb/hive web application has been archived."
echo ""
echo "For agent development, please use:"
echo "  ./scripts/setup-python.sh"
echo ""
echo "See ENVIRONMENT_SETUP.md for complete agent development guide."
echo ""
