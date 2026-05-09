#!/bin/bash
set -e

cd "$(dirname "$0")/.."

echo "=== KnowledgeLayer Local Dev ==="

# Check for .env
if [ ! -f .env ]; then
    echo "Creating .env from .env.example..."
    cp .env.example .env
    echo "Edit .env with your API keys, then re-run this script"
    exit 1
fi

# Default to mocks for local dev
export USE_MOCKS=${USE_MOCKS:-true}

# Check Redis (only needed if not using mocks)
if [ "$USE_MOCKS" != "true" ]; then
    if ! nc -z localhost 6379 2>/dev/null; then
        echo "Starting Redis..."
        docker compose up -d
        sleep 2
    fi
    echo "Redis: localhost:6379"
fi

PORT=${PORT:-8001}

echo ""
echo "USE_MOCKS=$USE_MOCKS"
echo ""
echo "Starting API server..."
echo "  API:     http://localhost:$PORT"
echo "  Swagger: http://localhost:$PORT/docs"
echo ""

exec poetry run python -m uvicorn api.main:app --reload --host 0.0.0.0 --port "$PORT"
