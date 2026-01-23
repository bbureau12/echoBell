#!/bin/bash
# Start Policy API Server (Bash)
# 
# This script starts the EchoBell Policy API server with proper environment setup

echo "============================================================"
echo "EchoBell Policy API Server Startup"
echo "============================================================"

# Get script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Set environment variables
export ECHOBELL_DB_PATH="${SCRIPT_DIR}/../../data/echoBell.db"
export POLICY_API_HOST="0.0.0.0"
export POLICY_API_PORT="8000"

echo ""
echo "Environment:"
echo "  Database: $ECHOBELL_DB_PATH"
echo "  Host: $POLICY_API_HOST"
echo "  Port: $POLICY_API_PORT"
echo ""

# Check if dependencies are installed
echo "Checking dependencies..."
if ! python -c "import fastapi" 2>/dev/null; then
    echo "  Installing FastAPI dependencies..."
    pip install -r requirements.txt
    if [ $? -ne 0 ]; then
        echo "  Failed to install dependencies!"
        exit 1
    fi
else
    echo "  Dependencies OK"
fi

echo ""
echo "Starting Policy API server..."
echo "  API will be available at: http://localhost:8000"
echo "  Health check: http://localhost:8000/health"
echo "  API docs: http://localhost:8000/docs"
echo ""
echo "Press Ctrl+C to stop the server"
echo ""

# Start the server
python server.py
