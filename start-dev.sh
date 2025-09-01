#!/bin/bash

# Watchflow Local Development Startup Script

# Set the PATH to include uv
export PATH="$HOME/.local/bin:$PATH"

# Activate virtual environment
source .venv/bin/activate

# Check if .env file exists
if [ ! -f .env ]; then
    echo "Error: .env file not found!"
    echo "Please copy .env.example to .env and configure your environment variables."
    exit 1
fi

# Check if required environment variables are set
if [ -z "$OPENAI_API_KEY" ] && [ -z "$(grep '^OPENAI_API_KEY=' .env | cut -d'=' -f2)" ]; then
    echo "Warning: OPENAI_API_KEY not set. AI features will not work."
fi

if [ -z "$APP_NAME_GITHUB" ] && [ -z "$(grep '^APP_NAME_GITHUB=' .env | cut -d'=' -f2)" ]; then
    echo "Warning: GitHub App configuration not complete. GitHub integration will not work."
fi

echo "Starting Watchflow API server..."
echo "API will be available at: http://localhost:8000"
echo "API documentation at: http://localhost:8000/docs"
echo "Health check at: http://localhost:8000/health"
echo ""
echo "Press Ctrl+C to stop the server"
echo ""

# Start the API server
uvicorn src.main:app --reload --host 0.0.0.0 --port 8000
