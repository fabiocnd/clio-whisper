<#
.SYNOPSIS
    Starts the Clio Whisper ecosystem (WhisperLive container + API server)

.DESCRIPTION
    This script:
    1. Verifies Docker is running
    2. Starts the WhisperLive GPU container on port 9090
    3. Waits for the container to be ready
    4. Starts the clio-api-server

.PARAMETER SkipContainer
    Skip starting the WhisperLive container (assume it's already running)

.PARAMETER SkipServer
    Skip starting the API server

.EXAMPLE
    .\start-ecosystem.ps1
#>

param(
    [switch]$SkipContainer,
    [switch]$SkipServer
)

$ErrorActionPreference = "Stop"
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptRoot

$CONTAINER_NAME = "clio-whisperlive"
$CONTAINER_IMAGE = "ghcr.io/collabora/whisperlive-gpu:latest"
$API_PORT = 8000
$WHISPERLIVE_PORT = 9090

function Write-Header {
    param([string]$Text)
    Write-Host ""
    Write-Host ("=" * 60) -ForegroundColor Cyan
    Write-Host "  $Text" -ForegroundColor Cyan
    Write-Host ("=" * 60) -ForegroundColor Cyan
}

function Test-DockerRunning {
    Write-Host "Checking Docker status..." -ForegroundColor Yellow
    try {
        $dockerVersion = docker version --format '{{.Server.Version}}' 2>$null
        if ($LASTEXITCODE -ne 0) {
            throw "Docker is not running"
        }
        Write-Host "  Docker version: $dockerVersion" -ForegroundColor Green
        return $true
    }
    catch {
        Write-Host "  ERROR: Docker is not running or not accessible" -ForegroundColor Red
        Write-Host "  Please start Docker Desktop and try again" -ForegroundColor Yellow
        exit 1
    }
}

function Start-WhisperLiveContainer {
    Write-Header "Starting WhisperLive Container"

    # Check if container already running
    $existingContainer = docker ps --filter "name=$CONTAINER_NAME" --format "{{.Names}}" 2>$null
    if ($existingContainer -eq $CONTAINER_NAME) {
        Write-Host "  Container '$CONTAINER_NAME' is already running" -ForegroundColor Green
        return $true
    }

    # Check if container exists but stopped
    $stoppedContainer = docker ps -a --filter "name=$CONTAINER_NAME" --format "{{.Names}}" 2>$null
    if ($stoppedContainer -eq $CONTAINER_NAME) {
        Write-Host "  Removing stopped container..." -ForegroundColor Yellow
        docker rm $CONTAINER_NAME | Out-Null
    }

    Write-Host "  Pulling image (if needed)..." -ForegroundColor Yellow
    docker pull $CONTAINER_IMAGE | Out-Null

    Write-Host "  Starting container..." -ForegroundColor Yellow
    $env:DOCKER_BUILDKIT = 0
    docker run -itd `
        --name $CONTAINER_NAME `
        --gpus all `
        -p ${WHISPERLIVE_PORT}:9090 `
        $CONTAINER_IMAGE | Out-Null

    if ($LASTEXITCODE -ne 0) {
        Write-Host "  ERROR: Failed to start container" -ForegroundColor Red
        exit 1
    }

    Write-Host "  Container started: $CONTAINER_NAME" -ForegroundColor Green
    return $true
}

function Wait-WhisperLiveReady {
    Write-Header "Waiting for WhisperLive to be ready"

    $maxAttempts = 60
    $attempt = 0
    $ready = $false

    while ($attempt -lt $maxAttempts) {
        $attempt++
        Write-Host "  Attempt $attempt/$maxAttempts..." -NoNewline -ForegroundColor Yellow

        try {
            $response = Invoke-WebRequest -Uri "http://localhost:${WHISPERLIVE_PORT}/health" `
                -TimeoutSec 2 `
                -ErrorAction SilentlyContinue 2>$null

            if ($response.StatusCode -eq 200) {
                Write-Host " READY" -ForegroundColor Green
                $ready = $true
                break
            }
        }
        catch {
            # Try WebSocket connection
            try {
                $ws = New-Object System.Net.WebSocket
                $ws.Connect("ws://localhost:${WHISPERLIVE_PORT}")
                if ($ws.State -eq 'Open') {
                    $ws.Dispose()
                    Write-Host " READY" -ForegroundColor Green
                    $ready = $true
                    break
                }
            }
            catch {
                # Port not ready yet
            }
        }

        Write-Host " NOT READY"
        Start-Sleep -Seconds 2
    }

    if (-not $ready) {
        Write-Host "  WARNING: WhisperLive may not be fully ready, continuing anyway..." -ForegroundColor Yellow
    }
    else {
        Write-Host "  WhisperLive is ready on port $WHISPERLIVE_PORT" -ForegroundColor Green
    }
}

function Start-ApiServer {
    Write-Header "Starting Clio API Server"

    $venvPython = Join-Path $projectRoot ".venv" "Scripts" "python.exe"
    if (-not (Test-Path $venvPython)) {
        Write-Host "  ERROR: Virtual environment not found at $venvPython" -ForegroundColor Red
        Write-Host "  Run: py -3.11 -m venv .venv" -ForegroundColor Yellow
        exit 1
    }

    $envFile = Join-Path $projectRoot ".env"
    if (-not (Test-Path $envFile)) {
        Write-Host "  WARNING: .env file not found, copying from .env.example" -ForegroundColor Yellow
        Copy-Item (Join-Path $projectRoot ".env.example") $envFile
    }

    Write-Host "  Starting API server on port $API_PORT..." -ForegroundColor Yellow

    $process = Start-Process -FilePath $venvPython `
        -ArgumentList "-m", "uvicorn", "clio_api_server.app.main:app", "--host", "0.0.0.0", "--port", $API_PORT `
        -WorkingDirectory $projectRoot `
        -PassThru

    if ($process -eq $null -or $process.HasExited) {
        Write-Host "  ERROR: Failed to start API server" -ForegroundColor Red
        exit 1
    }

    Write-Host "  API server started (PID: $($process.Id))" -ForegroundColor Green

    # Wait for API to be ready
    $maxAttempts = 30
    $attempt = 0
    while ($attempt -lt $maxAttempts) {
        $attempt++
        try {
            $response = Invoke-WebRequest -Uri "http://localhost:${API_PORT}/health" `
                -TimeoutSec 1 `
                -ErrorAction SilentlyContinue 2>$null
            if ($response.StatusCode -eq 200) {
                Write-Host "  API server is ready at http://localhost:${API_PORT}" -ForegroundColor Green
                Write-Host "  UI available at http://localhost:${API_PORT}/" -ForegroundColor Green
                return $process.Id
            }
        }
        catch {
            Start-Sleep -Seconds 1
        }
    }

    Write-Host "  WARNING: API server may not be fully ready, continuing anyway..." -ForegroundColor Yellow
    return $process.Id
}

function Write-Summary {
    param([int]$ServerPid)

    Write-Header "Ecosystem Started"
    Write-Host "  WhisperLive: http://localhost:${WHISPERLIVE_PORT}" -ForegroundColor Green
    Write-Host "  API Server:  http://localhost:${API_PORT}" -ForegroundColor Green
    Write-Host "  UI:          http://localhost:${API_PORT}/" -ForegroundColor Green
    Write-Host ""
    Write-Host "  API PID: $ServerPid" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Useful endpoints:" -ForegroundColor Cyan
    Write-Host "  - Health:      GET /health" -ForegroundColor White
    Write-Host "  - Status:      GET /v1/status" -ForegroundColor White
    Write-Host "  - Transcript:  GET /v1/transcript/unconsolidated" -ForegroundColor White
    Write-Host "  - Questions:   GET /v1/questions" -ForegroundColor White
    Write-Host "  - Start:       POST /v1/control/start" -ForegroundColor White
    Write-Host "  - Stop:        POST /v1/control/stop" -ForegroundColor White
    Write-Host ""
    Write-Host "To stop the ecosystem, run: .\stop-ecosystem.ps1" -ForegroundColor Yellow
}

# Main execution
Write-Header "Clio Whisper Ecosystem Startup"

Test-DockerRunning

if (-not $SkipContainer) {
    Start-WhisperLiveContainer
    Wait-WhisperLiveReady
}

$serverPid = $null
if (-not $SkipServer) {
    $serverPid = Start-ApiServer
}

Write-Summary -ServerPid $serverPid
