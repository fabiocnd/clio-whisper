<#
.SYNOPSIS
    Stops the Clio Whisper ecosystem

.DESCRIPTION
    This script:
    1. Stops the clio-api-server gracefully
    2. Stops the WhisperLive container

.PARAMETER SkipContainer
    Skip stopping the WhisperLive container

.PARAMETER SkipServer
    Skip stopping the API server

.EXAMPLE
    .\stop-ecosystem.ps1
#>

param(
    [switch]$SkipContainer,
    [switch]$SkipServer,
    [switch]$Force
)

$ErrorActionPreference = "Stop"

$CONTAINER_NAME = "clio-whisperlive"
$API_PORT = 8000

function Write-Header {
    param([string]$Text)
    Write-Host ""
    Write-Host ("=" * 60) -ForegroundColor Cyan
    Write-Host "  $Text" -ForegroundColor Cyan
    Write-Host ("=" * 60) -ForegroundColor Cyan
}

function Stop-ApiServer {
    Write-Header "Stopping API Server"

    # Try to stop gracefully via API first
    try {
        Write-Host "  Sending stop request..." -ForegroundColor Yellow
        $response = Invoke-WebRequest -Uri "http://localhost:${API_PORT}/v1/control/stop" `
            -Method POST `
            -TimeoutSec 5 `
            -ErrorAction SilentlyContinue 2>$null

        if ($response.StatusCode -eq 200) {
            Write-Host "  API server stopped gracefully" -ForegroundColor Green
            return
        }
    }
    catch {
        Write-Host "  Could not stop via API (may already be stopped)" -ForegroundColor Yellow
    }

    # Find and kill the process
    Write-Host "  Looking for API server process..." -ForegroundColor Yellow

    $processFound = $false

    # Try to find by port
    $netStat = netstat -ano 2>$null | Select-String ":${API_PORT}"
    if ($netStat) {
        $lines = $netStat | ForEach-Object { $_ -replace '\s+', ' ' }
        foreach ($line in $lines) {
            $parts = $line -split '\s+'
            if ($parts.Count -gt 4) {
                $pid = $parts[-1]
                if ($pid -match '^\d+$') {
                    try {
                        $process = Get-Process -Id $pid -ErrorAction SilentlyContinue
                        if ($process) {
                            Write-Host "  Found process: $($process.ProcessName) (PID: $pid)" -ForegroundColor Green

                            if (-not $Force) {
                                Write-Host "  Attempting graceful shutdown..." -ForegroundColor Yellow
                                $process.CloseMainWindow() | Out-Null
                                Start-Sleep -Seconds 2

                                if -not $process.HasExited {
                                    Write-Host "  Forcing shutdown..." -ForegroundColor Yellow
                                    $process | Stop-Process -Force | Out-Null
                                }
                            }
                            else {
                                $process | Stop-Process -Force | Out-Null
                            }

                            $processFound = $true
                            Write-Host "  Process stopped" -ForegroundColor Green
                        }
                    }
                    catch {
                        # Process may have already exited
                    }
                }
            }
        }
    }

    if (-not $processFound) {
        Write-Host "  No API server process found on port $API_PORT" -ForegroundColor Yellow
    }
}

function Stop-WhisperLiveContainer {
    Write-Header "Stopping WhisperLive Container"

    $containerRunning = docker ps --filter "name=$CONTAINER_NAME" --format "{{.Names}}" 2>$null
    if ($containerRunning -ne $CONTAINER_NAME) {
        Write-Host "  Container '$CONTAINER_NAME' is not running" -ForegroundColor Yellow
        return
    }

    Write-Host "  Stopping container..." -ForegroundColor Yellow
    docker stop $CONTAINER_NAME | Out-Null

    if ($LASTEXITCODE -eq 0) {
        Write-Host "  Container stopped" -ForegroundColor Green

        Write-Host "  Removing container..." -ForegroundColor Yellow
        docker rm $CONTAINER_NAME | Out-Null
        Write-Host "  Container removed" -ForegroundColor Green
    }
    else {
        Write-Host "  ERROR: Failed to stop container" -ForegroundColor Red
    }
}

function Write-Summary {
    Write-Header "Ecosystem Stopped"
    Write-Host "  Both WhisperLive and API server have been stopped" -ForegroundColor Green
    Write-Host ""
    Write-Host "To start again, run: .\start-ecosystem.ps1" -ForegroundColor Yellow
}

# Main execution
Write-Header "Clio Whisper Ecosystem Shutdown"

if (-not $SkipServer) {
    Stop-ApiServer
}

if (-not $SkipContainer) {
    Stop-WhisperLiveContainer
}

Write-Summary
