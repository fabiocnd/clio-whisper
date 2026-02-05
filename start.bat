@echo off
REM WhisperLive Startup Script
REM Starts both servers for real-time transcription

echo ============================================================
echo WhisperLive Real-Time Transcription System
echo ============================================================
echo.

REM Check if venv exists
if not exist ".\venv\Scripts\python.exe" (
    echo ERROR: Virtual environment not found!
    echo Please run: python -m venv .venv
    exit /b 1
)

echo [1/2] Starting Whisper Server (Port 9090)...
start "Whisper Server" .venv\Scripts\python.exe run_server.py --port 9090 --backend faster_whisper

echo.
echo [2/2] Starting API Server (Port 8000)...
timeout /t 3 /nobreak > nul
start "API Server" .venv\Scripts\python.exe run_api.py

echo.
echo ============================================================
echo Servers started successfully!
echo ============================================================
echo.
echo To use:
echo   - Start transcription: curl -X POST http://localhost:8000/start
echo   - Get text:        curl http://localhost:8000/transcription/consolidated
echo   - Stop:            curl -X POST http://localhost:8000/stop
echo.
echo Press Ctrl+C to stop both servers.
pause
