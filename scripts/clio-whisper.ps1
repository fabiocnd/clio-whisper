#!/usr/bin/env pwsh
<#
# Clio Whisper Ecosystem Manager - PowerShell
# Manage WhisperLive Docker container, Redis, and API server
#

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$ContainerName = "clio-whisperlive"
$RedisContainerName = "clio-redis"
$ApiPort = 8000
$WhisperPort = 9090
$RedisPort = 6379

# Colors for output
$Green = [System.ConsoleColor]::Green
$Red = [System.ConsoleColor]::Red
$Yellow = [System.ConsoleColor]::Yellow
$Cyan = [System.ConsoleColor]::Cyan
$White = [System.ConsoleColor]::White

function Write-Header {
    param([string]$Title)
    Write-Host "`n========================================" -ForegroundColor $Cyan
    Write-Host "  $Title" -ForegroundColor $Cyan
    Write-Host "========================================`n" -ForegroundColor $Cyan
}

function Write-Status {
    param([string]$Message, [System.ConsoleColor]$Color = $White)
    Write-Host "[$(Get-Date -Format 'HH:mm:ss')] " -ForegroundColor $Yellow -NoNewline
    Write-Host $Message -ForegroundColor $Color
}

function Write-Success {
    param([string]$Message)
    Write-Status -Message $Message -Color $Green
}

function Write-Error {
    param([string]$Message)
    Write-Status -Message "ERROR: $Message" -Color $Red
}

function Write-Warning {
    param([string]$Message)
    Write-Status -Message "WARNING: $Message" -Color $Yellow
}

function Test-DockerRunning {
    try {
        $null = docker info
        return $true
    }
    catch {
        return $false
    }
}

function Test-ContainerRunning {
    param([string]$Name)
    $status = docker ps --format '{{.Names}}' | Where-Object { $_ -eq $Name }
    return ![string]::IsNullOrEmpty($status)
}

function Get-ContainerStatus {
    param([string]$Name)
    $output = docker ps -a --filter "name=$Name" --format "{{.Status}}"
    if ([string]::IsNullOrEmpty($output)) {
        return "stopped"
    }
    if ($output -match "Up") {
        return "running"
    }
    return "stopped"
}

function Start-WhisperLive {
    Write-Header "Starting WhisperLive GPU Server"
    
    if (-not (Test-DockerRunning)) {
        Write-Error "Docker is not running. Please start Docker Desktop."
        return $false
    }
    
    if (Test-ContainerRunning -Name $ContainerName) {
        $status = Get-ContainerStatus -Name $ContainerName
        if ($status -eq "running") {
            Write-Success "WhisperLive container is already running"
            return $true
        }
        Write-Warning "Container exists but is not running. Starting..."
        docker start $ContainerName
    }
    else {
        Write-Status "Creating and starting WhisperLive container..."
        docker run -itd --name $ContainerName --gpus all -p ${WhisperPort}:9090 ghcr.io/collabora/whisperlive-gpu:latest
    }
    
    # Wait for container to be ready
    Write-Status "Waiting for WhisperLive to be ready..."
    $maxWait = 60
    $waited = 0
    while ($waited -lt $maxWait) {
        try {
            $response = Invoke-WebRequest -Uri "http://localhost:$WhisperPort" -TimeoutSec 2 -ErrorAction SilentlyContinue
            if ($response.StatusCode -eq 426) {
                Write-Success "WhisperLive is ready (WS endpoint responding)"
                return $true
            }
        }
        catch {
            # Expected - WS endpoint returns 426 for HTTP
        }
        Start-Sleep -Seconds 2
        $waited += 2
        Write-Status "Waiting... ($waited/$maxWait seconds)"
    }
    
    Write-Error "WhisperLive did not become ready in time"
    return $false
}

function Stop-WhisperLive {
    Write-Header "Stopping WhisperLive GPU Server"
    
    if (-not (Test-ContainerRunning -Name $ContainerName)) {
        Write-Warning "WhisperLive container is not running"
        return $true
    }
    
    Write-Status "Stopping container..."
    docker stop $ContainerName | Out-Null
    Write-Success "WhisperLive container stopped"
    return $true
}

function Restart-WhisperLive {
    Write-Header "Restarting WhisperLive GPU Server"
    Stop-WhisperLive
    Start-Sleep -Seconds 2
    Start-WhisperLive
}

function Start-Redis {
    Write-Header "Starting Redis Server"

    if (-not (Test-DockerRunning)) {
        Write-Error "Docker is not running. Please start Docker Desktop."
        return $false
    }

    if (Test-ContainerRunning -Name $RedisContainerName) {
        $status = Get-ContainerStatus -Name $RedisContainerName
        if ($status -eq "running") {
            Write-Success "Redis container is already running"
            return $true
        }
        Write-Warning "Container exists but is not running. Starting..."
        docker start $RedisContainerName
    }
    else {
        Write-Status "Creating and starting Redis container..."
        docker run -itd --name $RedisContainerName -p ${RedisPort}:6379 redis:alpine
    }

    # Wait for Redis to be ready
    Write-Status "Waiting for Redis to be ready..."
    $maxWait = 30
    $waited = 0
    while ($waited -lt $maxWait) {
        try {
            $socket = New-Object Net.Sockets.TcpClient
            $socket.Connect("localhost", $RedisPort)
            $socket.Close()
            Write-Success "Redis is ready on port $RedisPort"
            return $true
        }
        catch {
            Start-Sleep -Seconds 2
            $waited += 2
            Write-Status "Waiting... ($waited/$maxWait seconds)"
        }
    }

    Write-Error "Redis did not become ready in time"
    return $false
}

function Stop-Redis {
    Write-Header "Stopping Redis Server"

    if (-not (Test-ContainerRunning -Name $RedisContainerName)) {
        Write-Warning "Redis container is not running"
        return $true
    }

    Write-Status "Stopping Redis container..."
    docker stop $RedisContainerName | Out-Null
    Write-Success "Redis container stopped"
    return $true
}

function Restart-Redis {
    Write-Header "Restarting Redis Server"
    Stop-Redis
    Start-Sleep -Seconds 2
    Start-Redis
}

function Test-RedisConnection {
    param([int]$Port = $RedisPort)
    try {
        $socket = New-Object Net.Sockets.TcpClient
        $socket.Connect("localhost", $Port)
        $socket.Close()
        return $true
    }
    catch {
        return $false
    }
}

function Start-ApiServer {
    Write-Header "Starting Clio Whisper API Server"
    
    if (Get-Process -Name "python" -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -like "*uvicorn*" -and $_.CommandLine -like "*clio*" }) {
        Write-Warning "API server might already be running. Check port $ApiPort."
    }
    
    # Check if port is in use
    $portInUse = netstat -ano | Select-String ":$ApiPort " | Select-Object -First 1
    if ($portInUse) {
        Write-Warning "Port $ApiPort is already in use. Trying to find running server..."
        $pid = $portInUse.Line -split '\s+' | Select-Object -Last 1
        Write-Status "Process PID: $pid"
    }
    
    Write-Status "Starting API server on port $ApiPort..."
    
    $process = Start-Process -FilePath $VenvPython `
        -ArgumentList "-m", "uvicorn", "clio_api_server.app.main:app", "--host", "0.0.0.0", "--port", $ApiPort `
        -WorkingDirectory $ProjectRoot `
        -PassThru `
        -NoNewWindow
    
    if ($null -eq $process) {
        Write-Error "Failed to start API server"
        return $false
    }
    
    Write-Status "API server started (PID: $($process.Id))"
    
    # Wait for server to be ready
    Write-Status "Waiting for API server to be ready..."
    $maxWait = 30
    $waited = 0
    while ($waited -lt $maxWait) {
        try {
            $response = Invoke-WebRequest -Uri "http://localhost:$ApiPort/health" -TimeoutSec 2 -ErrorAction SilentlyContinue
            if ($response.StatusCode -eq 200) {
                $data = $response.Content | ConvertFrom-Json
                if ($data.status -eq "healthy") {
                    Write-Success "API server is ready and healthy"
                    return $true
                }
            }
        }
        catch {
            # Server not ready yet
        }
        Start-Sleep -Seconds 2
        $waited += 2
    }
    
    Write-Error "API server did not become ready in time"
    return $false
}

function Stop-ApiServer {
    Write-Header "Stopping Clio Whisper API Server"
    
    # Try graceful shutdown first
    try {
        Write-Status "Sending shutdown request..."
        Invoke-WebRequest -Uri "http://localhost:$ApiPort/v1/control/stop" -Method POST -ErrorAction SilentlyContinue | Out-Null
        Start-Sleep -Seconds 2
    }
    catch {
        # Ignore errors
    }
    
    # Find and kill uvicorn processes
    $killed = 0
    Get-Process -Name "python" -ErrorAction SilentlyContinue | ForEach-Object {
        if ($_.CommandLine -like "*uvicorn*" -and $_.CommandLine -like "*clio*") {
            Write-Status "Stopping process PID: $($_.Id)"
            Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
            $killed++
        }
    }
    
    # Also check for processes on port
    $portOutput = netstat -ano | Select-String ":$ApiPort " | Select-Object -First 5
    foreach ($line in $portOutput) {
        $parts = $line -split '\s+'
        $pid = $parts[-1]
        if ($pid -and $pid -ne "0" -and (Get-Process -Id $pid -ErrorAction SilentlyContinue)) {
            Write-Status "Stopping process on port (PID: $pid)"
            Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
            $killed++
        }
    }
    
    if ($killed -gt 0) {
        Write-Success "Stopped $killed process(es)"
    }
    else {
        Write-Warning "No API server processes found"
    }
    
    return $true
}

function Restart-ApiServer {
    Write-Header "Restarting Clio Whisper API Server"
    Stop-ApiServer
    Start-Sleep -Seconds 2
    Start-ApiServer
}

function Start-Ecosystem {
    Write-Header "Starting Complete Clio Whisper Ecosystem"
    
    $result = $true
    $result = $result -and (Start-WhisperLive)
    $result = $result -and (Start-ApiServer)
    
    Write-Header "Ecosystem Status"
    if ($result) {
        Write-Success "Ecosystem started successfully!"
        Write-Status "WhisperLive: http://localhost:$WhisperPort (WebSocket)"
        Write-Status "API Server: http://localhost:$ApiPort"
        Write-Status "API Health: http://localhost:$ApiPort/health"
    }
    else {
        Write-Error "Some components failed to start. Check logs above."
    }
    
    return $result
}

function Stop-Ecosystem {
    Write-Header "Stopping Complete Clio Whisper Ecosystem"
    
    $result = $true
    $result = $result -and (Stop-ApiServer)
    $result = $result -and (Stop-WhisperLive)
    
    if ($result) {
        Write-Success "Ecosystem stopped successfully!"
    }
    else {
        Write-Error "Some components failed to stop. Check logs above."
    }
    
    return $result
}

function Restart-Ecosystem {
    Write-Header "Restarting Complete Clio Whisper Ecosystem"
    Stop-Ecosystem
    Start-Sleep -Seconds 3
    Start-Ecosystem
}

function Show-Status {
    Write-Header "Clio Whisper Ecosystem Status"

    # Docker status
    Write-Status "Docker: " -NoNewline
    if (Test-DockerRunning) {
        Write-Host "Running" -ForegroundColor $Green
    }
    else {
        Write-Host "Not Running" -ForegroundColor $Red
    }

    # Redis status
    Write-Status "Redis ($RedisContainerName): " -NoNewline
    $redisStatus = Get-ContainerStatus -Name $RedisContainerName
    if ($redisStatus -eq "running") {
        Write-Host "Running" -ForegroundColor $Green
        Write-Status "  Port: $RedisPort"
    }
    else {
        Write-Host "Stopped" -ForegroundColor $Red
    }

    # WhisperLive status
    Write-Status "WhisperLive ($ContainerName): " -NoNewline
    $status = Get-ContainerStatus -Name $ContainerName
    if ($status -eq "running") {
        Write-Host "Running" -ForegroundColor $Green
        $ports = docker port $ContainerName 9090 2>$null
        if ($ports) {
            Write-Status "  Port: $ports"
        }
    }
    else {
        Write-Host "Stopped" -ForegroundColor $Red
    }

    # API Server status
    Write-Status "API Server (port $ApiPort): " -NoNewline
    try {
        $response = Invoke-WebRequest -Uri "http://localhost:$ApiPort/health" -TimeoutSec 2 -ErrorAction SilentlyContinue
        if ($response.StatusCode -eq 200) {
            $data = $response.Content | ConvertFrom-Json
            Write-Host "Running (healthy)" -ForegroundColor $Green
            Write-Status "  WhisperLive connected: $($data.whisperlive_connected)"
        }
        else {
            Write-Host "Running (unhealthy)" -ForegroundColor $Yellow
        }
    }
    catch {
        Write-Host "Stopped" -ForegroundColor $Red
    }

    # Pipeline status
    Write-Status "Pipeline: " -NoNewline
    try {
        $response = Invoke-WebRequest -Uri "http://localhost:$ApiPort/v1/status" -TimeoutSec 2 -ErrorAction SilentlyContinue
        $data = $response.Content | ConvertFrom-Json
        Write-Host "$($data.state)" -ForegroundColor $(if ($data.state -eq "RUNNING") { $Green } else { $Yellow })
        if ($data.queue_depths) {
            Write-Status "  Segments: $($data.queue_depths.segments_received) received, $($data.queue_depths.segments_committed) committed"
            Write-Status "  Questions: $($data.queue_depths.questions_extracted) extracted"
        }
    }
    catch {
        Write-Host "Unknown" -ForegroundColor $Yellow
    }
}

function Show-Help {
    Write-Host @"

Clio Whisper Ecosystem Manager
============================

USAGE:
    .\clio-whisper.ps1 [COMMAND]

COMMANDS - WhisperLive:
    start           Start WhisperLive container only
    stop            Stop WhisperLive container only
    restart         Restart WhisperLive container only

COMMANDS - Redis:
    redis-start     Start Redis container only
    redis-stop      Stop Redis container only
    redis-restart   Restart Redis container only

COMMANDS - API:
    api-start       Start API server only
    api-stop        Stop API server only
    api-restart     Restart API server only

COMMANDS - Ecosystem:
    start-all       Start complete ecosystem (Redis + WhisperLive + API)
    stop-all        Stop complete ecosystem
    restart-all     Restart complete ecosystem
    status          Show status of all components
    help            Show this help message

ENVIRONMENT:
    Set REDIS_ENABLED=true in .env to enable Redis pipeline mode

EXAMPLES:
    .\clio-whisper.ps1 start-all
    .\clio-whisper.ps1 redis-start
    .\clio-whisper.ps1 status

"@
}

# Main script logic
$command = $args[0]

switch ($command) {
    # WhisperLive
    "start"          { Start-WhisperLive }
    "stop"           { Stop-WhisperLive }
    "restart"        { Restart-WhisperLive }

    # Redis
    "redis-start"    { Start-Redis }
    "redis-stop"     { Stop-Redis }
    "redis-restart"  { Restart-Redis }

    # API
    "api-start"      { Start-ApiServer }
    "api-stop"       { Stop-ApiServer }
    "api-restart"    { Restart-ApiServer }

    # Ecosystem
    "start-all"      { Start-Ecosystem }
    "stop-all"       { Stop-Ecosystem }
    "restart-all"    { Restart-Ecosystem }
    "status"         { Show-Status }
    "help"           { Show-Help }
    "h"              { Show-Help }
    "?"              { Show-Help }
    $null            { Show-Help }
    default          { Write-Warning "Unknown command: $command"; Show-Help }
}
