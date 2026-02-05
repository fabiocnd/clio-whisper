#!/usr/bin/env bash
#
# Clio Whisper Ecosystem Manager - Bash
# Manage WhisperLive Docker container and API server
#

set -e

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
VENV_PYTHON="$PROJECT_ROOT/.venv/Scripts/python.exe"
CONTAINER_NAME="clio-whisperlive"
API_PORT=8000
WHISPER_PORT=9090

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Helper functions
print_header() {
    echo -e "\n${CYAN}========================================${NC}"
    echo -e "${CYAN}  $1${NC}"
    echo -e "${CYAN}========================================${NC}\n"
}

print_status() {
    echo -e "[$(date +'%H:%M:%S')] $1"
}

print_success() {
    print_status "${GREEN}$1${NC}"
}

print_error() {
    print_status "${RED}ERROR: $1${NC}"
}

print_warning() {
    print_status "${YELLOW}WARNING: $1${NC}"
}

# Check if Docker is running
docker_running() {
    docker info &>/dev/null 2>&1
}

# Check if container is running
container_running() {
    docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"
}

# Get container status
container_status() {
    local status=$(docker ps -a --filter "name=$CONTAINER_NAME" --format "{{.Status}}" 2>/dev/null || echo "")
    if [[ -z "$status" ]]; then
        echo "stopped"
    elif [[ "$status" == Up* ]]; then
        echo "running"
    else
        echo "stopped"
    fi
}

# Start WhisperLive container
start_whisperlive() {
    print_header "Starting WhisperLive GPU Server"
    
    if ! docker_running; then
        print_error "Docker is not running. Please start Docker Desktop."
        return 1
    fi
    
    if container_running; then
        local status=$(container_status)
        if [[ "$status" == "running" ]]; then
            print_success "WhisperLive container is already running"
            return 0
        fi
        print_warning "Container exists but is not running. Starting..."
        docker start "$CONTAINER_NAME" 2>/dev/null || true
    else
        print_status "Creating and starting WhisperLive container..."
        docker run -itd --name "$CONTAINER_NAME" --gpus all -p ${WHISPER_PORT}:9090 \
            ghcr.io/collabora/whisperlive-gpu:latest 2>/dev/null || {
            print_error "Failed to create container. It might already exist."
            print_status "Try: docker rm $CONTAINER_NAME"
            return 1
        }
    fi
    
    # Wait for container to be ready
    print_status "Waiting for WhisperLive to be ready..."
    local max_wait=60
    local waited=0
    while [[ $waited -lt $max_wait ]]; do
        if curl -s -o /dev/null -w "%{http_code}" "http://localhost:$WHISPER_PORT" 2>/dev/null | grep -q "426"; then
            print_success "WhisperLive is ready (WS endpoint responding)"
            return 0
        fi
        sleep 2
        waited=$((waited + 2))
        print_status "Waiting... ($waited/$max_wait seconds)"
    done
    
    print_error "WhisperLive did not become ready in time"
    return 1
}

# Stop WhisperLive container
stop_whisperlive() {
    print_header "Stopping WhisperLive GPU Server"
    
    if ! container_running; then
        print_warning "WhisperLive container is not running"
        return 0
    fi
    
    print_status "Stopping container..."
    docker stop "$CONTAINER_NAME" 2>/dev/null || true
    print_success "WhisperLive container stopped"
    return 0
}

# Restart WhisperLive container
restart_whisperlive() {
    print_header "Restarting WhisperLive GPU Server"
    stop_whisperlive
    sleep 2
    start_whisperlive
}

# Start API server
start_api() {
    print_header "Starting Clio Whisper API Server"
    
    # Check if port is in use
    if netstat -ano 2>/dev/null | grep -q ":${API_PORT} " || ss -tlnp 2>/dev/null | grep -q ":${API_PORT}"; then
        print_warning "Port $API_PORT might be in use. Checking for running server..."
        local pids=$(lsof -t -i:${API_PORT} 2>/dev/null || echo "")
        if [[ -n "$pids" ]]; then
            print_status "Found process(es) on port $API_PORT: $pids"
        fi
    fi
    
    print_status "Starting API server on port $API_PORT..."
    
    # Start in background
    cd "$PROJECT_ROOT"
    nohup "$VENV_PYTHON" -m uvicorn clio_api_server.app.main:app \
        --host 0.0.0.0 --port $API_PORT \
        > /tmp/clio-api.log 2>&1 &
    
    local api_pid=$!
    print_status "API server started (PID: $api_pid)"
    
    # Wait for server to be ready
    print_status "Waiting for API server to be ready..."
    local max_wait=30
    local waited=0
    while [[ $waited -lt $max_wait ]]; do
        if curl -s "http://localhost:$API_PORT/health" 2>/dev/null | grep -q '"status":"healthy"'; then
            print_success "API server is ready and healthy"
            return 0
        fi
        sleep 2
        waited=$((waited + 2))
    done
    
    print_error "API server did not become ready in time"
    print_status "Check logs: tail -f /tmp/clio-api.log"
    return 1
}

# Stop API server
stop_api() {
    print_header "Stopping Clio Whisper API Server"
    
    # Try graceful shutdown first
    curl -s -X POST "http://localhost:$API_PORT/v1/control/stop" 2>/dev/null || true
    sleep 2
    
    # Kill uvicorn processes
    local killed=0
    
    # Find and kill uvicorn processes
    for pid in $(pgrep -f "uvicorn.*clio" 2>/dev/null || echo ""); do
        if [[ -n "$pid" && "$pid" != "$$" ]]; then
            print_status "Stopping process PID: $pid"
            kill "$pid" 2>/dev/null || true
            killed=$((killed + 1))
        fi
    done
    
    # Also kill processes on the port
    for pid in $(lsof -t -i:${API_PORT} 2>/dev/null || echo ""); do
        if [[ -n "$pid" ]]; then
            print_status "Stopping process on port (PID: $pid)"
            kill "$pid" 2>/dev/null || true
            killed=$((killed + 1))
        fi
    done
    
    if [[ $killed -gt 0 ]]; then
        print_success "Stopped $killed process(es)"
    else
        print_warning "No API server processes found"
    fi
    
    return 0
}

# Restart API server
restart_api() {
    print_header "Restarting Clio Whisper API Server"
    stop_api
    sleep 2
    start_api
}

# Start complete ecosystem
start_all() {
    print_header "Starting Complete Clio Whisper Ecosystem"
    
    local result=0
    start_whisperlive || result=1
    start_api || result=1
    
    print_header "Ecosystem Status"
    if [[ $result -eq 0 ]]; then
        print_success "Ecosystem started successfully!"
        print_status "WhisperLive: http://localhost:$WHISPER_PORT (WebSocket)"
        print_status "API Server: http://localhost:$API_PORT"
        print_status "API Health: http://localhost:$API_PORT/health"
    else
        print_error "Some components failed to start. Check logs above."
    fi
    
    return $result
}

# Stop complete ecosystem
stop_all() {
    print_header "Stopping Complete Clio Whisper Ecosystem"
    
    local result=0
    stop_api || result=1
    stop_whisperlive || result=1
    
    if [[ $result -eq 0 ]]; then
        print_success "Ecosystem stopped successfully!"
    else
        print_error "Some components failed to stop. Check logs above."
    fi
    
    return $result
}

# Restart complete ecosystem
restart_all() {
    print_header "Restarting Complete Clio Whisper Ecosystem"
    stop_all
    sleep 3
    start_all
}

# Show status
show_status() {
    print_header "Clio Whisper Ecosystem Status"
    
    # Docker status
    print_status "Docker: " -n
    if docker_running; then
        echo -e "${GREEN}Running${NC}"
    else
        echo -e "${RED}Not Running${NC}"
    fi
    
    # WhisperLive status
    print_status "WhisperLive ($CONTAINER_NAME): " -n
    local status=$(container_status)
    if [[ "$status" == "running" ]]; then
        echo -e "${GREEN}Running${NC}"
        local ports=$(docker port "$CONTAINER_NAME" 9090 2>/dev/null || echo "")
        if [[ -n "$ports" ]]; then
            print_status "  Port: $ports"
        fi
    else
        echo -e "${RED}Stopped${NC}"
    fi
    
    # API Server status
    print_status "API Server (port $API_PORT): " -n
    if curl -s "http://localhost:$API_PORT/health" 2>/dev/null | grep -q '"status":"healthy"'; then
        echo -e "${GREEN}Running (healthy)${NC}"
        local wl_status=$(curl -s "http://localhost:$API_PORT/v1/status" 2>/dev/null | grep -o '"whisperlive_connected"[^,]*' || echo "")
        print_status "  WhisperLive connected: $(echo $wl_status | grep -o 'true\|false' || echo 'unknown')"
    else
        echo -e "${RED}Stopped${NC}"
    fi
    
    # Pipeline status
    print_status "Pipeline: " -n
    local state=$(curl -s "http://localhost:$API_PORT/v1/status" 2>/dev/null | grep -o '"state":"[^"]*"' | cut -d'"' -f4 || echo "")
    if [[ "$state" == "RUNNING" ]]; then
        echo -e "${GREEN}$state${NC}"
        local received=$(curl -s "http://localhost:$API_PORT/v1/status" 2>/dev/null | grep -o '"segments_received":[0-9]*' | cut -d':' -f2 || echo "0")
        local committed=$(curl -s "http://localhost:$API_PORT/v1/status" 2>/dev/null | grep -o '"segments_committed":[0-9]*' | cut -d':' -f2 || echo "0")
        print_status "  Segments: $received received, $committed committed"
    else
        echo -e "${YELLOW}$state${NC}"
    fi
}

# Show help
show_help() {
    cat << EOF

Clio Whisper Ecosystem Manager
=============================

USAGE:
    ./clio-whisper.sh [COMMAND]

COMMANDS:
    start           Start WhisperLive container only
    stop            Stop WhisperLive container only
    restart         Restart WhisperLive container only
    api-start       Start API server only
    api-stop        Stop API server only
    api-restart     Restart API server only
    start-all       Start complete ecosystem (container + API)
    stop-all        Stop complete ecosystem (container + API)
    restart-all     Restart complete ecosystem
    status          Show status of all components
    help            Show this help message

EXAMPLES:
    ./clio-whisper.sh start-all
    ./clio-whisper.sh status
    ./clio-whisper.sh restart

EOF
}

# Main script logic
case "${1:-help}" in
    start)          start_whisperlive ;;
    stop)           stop_whisperlive ;;
    restart)        restart_whisperlive ;;
    api-start)      start_api ;;
    api-stop)       stop_api ;;
    api-restart)    restart_api ;;
    start-all)      start_all ;;
    stop-all)       stop_all ;;
    restart-all)    restart_all ;;
    status)         show_status ;;
    help|h|?)       show_help ;;
    *)              show_help ;;
esac
