# Start Policy API Server (PowerShell)
# 
# This script starts the EchoBell Policy API server with proper environment setup

Write-Host "=" -NoNewline
Write-Host ("=" * 59)
Write-Host "EchoBell Policy API Server Startup"
Write-Host "=" -NoNewline
Write-Host ("=" * 59)

# Set environment variables
$env:ECHOBELL_DB_PATH = Join-Path $PSScriptRoot "..\..\data\echoBell.db"
$env:POLICY_API_HOST = "0.0.0.0"
$env:POLICY_API_PORT = "8000"

Write-Host ""
Write-Host "Environment:"
Write-Host "  Database: $env:ECHOBELL_DB_PATH"
Write-Host "  Host: $env:POLICY_API_HOST"
Write-Host "  Port: $env:POLICY_API_PORT"
Write-Host ""

# Check if dependencies are installed
Write-Host "Checking dependencies..."
$pipList = pip list 2>$null

if ($pipList -notmatch "fastapi") {
    Write-Host "  Installing FastAPI dependencies..." -ForegroundColor Yellow
    pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  Failed to install dependencies!" -ForegroundColor Red
        exit 1
    }
} else {
    Write-Host "  Dependencies OK" -ForegroundColor Green
}

Write-Host ""
Write-Host "Starting Policy API server..."
Write-Host "  API will be available at: http://localhost:8000"
Write-Host "  Health check: http://localhost:8000/health"
Write-Host "  API docs: http://localhost:8000/docs"
Write-Host ""
Write-Host "Press Ctrl+C to stop the server"
Write-Host ""

# Start the server
python server.py
