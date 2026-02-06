# Clio Whisper

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.109.0+-00a393.svg)](https://fastapi.tiangolo.com/)
[![Docker](https://img.shields.io/badge/Docker-2496ed.svg)](https://www.docker.com/)

Real-time transcription system powered by OpenAI's Whisper through [WhisperLive](https://github.com/collabora/WhisperLive).

## Overview

Clio Whisper is a Windows-hosted ecosystem providing:

- **Real-time Speech-to-Text**: Captures microphone audio and streams to Whisper for transcription
- **Deterministic Transcript Aggregation**: Maintains clean, deduplicated transcript history
- **REST API & Streaming**: FastAPI endpoints with SSE/WebSocket support for real-time updates
- **Question Extraction**: Automatically detects and extracts questions from transcripts
- **GPU Acceleration**: CUDA-enabled Docker container for fast inference

## Technology Stack

| Component | Technology | Description |
|-----------|------------|-------------|
| **Transcription Engine** | [WhisperLive](https://github.com/collabora/WhisperLive) | OpenAI Whisper speech recognition in Docker |
| **Backend** | Faster-Whisper | CTranslate2-optimized Whisper (4x faster) |
| **Audio Capture** | [SoundDevice](https://python-sounddevice.readthedocs.io/) | Cross-platform audio input handling |
| **Web Framework** | [FastAPI](https://fastapi.tiangolo.com/) | High-performance async API framework |
| **Real-time Streaming** | SSE & WebSocket | Bidirectional event streaming |
| **Data Validation** | [Pydantic](https://docs.pydantic.dev/) | Runtime data validation with Python types |
| **Logging** | [Loguru](https://loguru.readthedocs.io/) | Structured logging with colors |
| **Containerization** | [Docker](https://www.docker.com/) | GPU-accelerated Whisper deployment |
| **Code Quality** | Ruff & MyPy | Linting and type checking |

## Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────────────┐
│   Microphone    │────▶│  clio-api-server│────▶│  WhisperLive GPU       │
│  (16kHz Mono)   │     │   (FastAPI)     │     │  (Docker/CUDA fp16)     │
└─────────────────┘     └────────┬────────┘     └─────────────────────────┘
                                  │
                                  ▼
                         ┌─────────────────┐
                         │   Aggregator    │
                         │ (Deduplication) │
                         └────────┬────────┘
                                  │
            ┌────────────────────┼────────────────────┐
            ▼                    ▼                    ▼
     ┌─────────────┐      ┌─────────────┐      ┌─────────────┐
     │  REST API   │      │  SSE Stream │      │ WebSocket   │
     └─────────────┘      └─────────────┘      └─────────────┘
```

## Current Status

| Component | Status |
|-----------|--------|
| WhisperLive GPU Server | ✅ Running (port 9090) |
| Redis (Windows) | ✅ Running (port 6379) |
| API Server | ✅ Running (port 8000) |
| Microphone Capture | ✅ 16kHz mono |
| WebSocket Client | ✅ Connected |
| Transcription | ✅ Processing (50K+ segments) |
| Question Extraction | ✅ Working (82+ extracted) |

## Quick Start

### Prerequisites

| Requirement | Minimum | Recommended |
|------------|---------|-------------|
| OS | Windows 11 | Windows 11 |
| Python | 3.11+ | 3.11+ |
| RAM | 8GB | 16GB+ |
| GPU | Optional (CPU works) | NVIDIA RTX |
| Docker | Desktop with GPU support | Desktop with RTX |

### Installation

```powershell
# Clone the repository
git clone https://github.com/fabiocnd/clio-whisper.git
cd clio-whisper

# Create virtual environment
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1

# Install dependencies
pip install -e .
```

### Running the Ecosystem

Using the management script:

```powershell
# Start all services
.\scripts\clio-whisper.ps1 start-all

# Check status
.\scripts\clio-whisper.ps1 status

# Stop all services
.\scripts\clio-whisper.ps1 stop-all
```

Or manually:

```powershell
# Start Redis (Windows)
D:\redis\redis-server.exe

# Start WhisperLive GPU container
docker run -d --gpus all -p 9090:9090 --name clio-whisperlive ghcr.io/collabora/whisperlive-gpu:latest

# Start API server
uvicorn clio_api_server.app.main:app --host 0.0.0.0 --port 8000
```

### Access

- **UI Dashboard**: http://localhost:8000/
- **API Documentation**: http://localhost:8000/docs
- **Health Check**: http://localhost:8000/v1/health

### Start Recording

```powershell
# Via API
curl -X POST http://localhost:8000/v1/control/start

# Via UI - click "Start Pipeline"
```

### Stop Recording

```powershell
# Via API
curl -X POST http://localhost:8000/v1/control/stop

# Via UI - click "Stop Pipeline"
```

## API Reference

### Control Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/v1/health` | Health check |
| GET | `/v1/status` | Pipeline status |
| POST | `/v1/control/start` | Start recording |
| POST | `/v1/control/stop` | Stop recording |
| GET | `/v1/metrics` | Operational metrics |

### Transcript Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/v1/transcript/unconsolidated` | All segments with states |
| GET | `/v1/transcript/consolidated` | Single paragraph (deduplicated) |
| GET | `/v1/questions` | Extracted questions |

### Streaming Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/v1/stream/transcript` | SSE stream of events |
| WS | `/v1/stream/transcript` | WebSocket stream |

## WhisperLive Integration

Clio Whisper integrates with [WhisperLive](https://github.com/collabora/WhisperLive) which uses:

- **Faster-Whisper**: CTranslate2-optimized implementation (4x faster than openai-whisper)
- **VAD Filtering**: Silero VAD to skip non-speech audio
- **GPU Acceleration**: CUDA fp16 inference

### WebSocket Protocol

```json
// Connect to: ws://localhost:9090

// Send configuration:
{
  "uid": "unique-client-id",
  "language": "en",
  "task": "transcribe",
  "model": "small",
  "use_vad": true,
  "send_last_n_segments": 10
}

// Receive events:
{
  "uid": "client-id",
  "segments": [
    {
      "start": "0.000",
      "end": "3.500",
      "text": "Hello world",
      "completed": false
    }
  ]
}
```

### Audio Format

| Parameter | Value |
|-----------|-------|
| Sample Rate | 16,000 Hz |
| Channels | 1 (Mono) |
| Format | 16-bit PCM (int16) |
| Chunk Size | 4096 samples (256ms) |
| Normalization | float32 / 32768.0 |

### Critical: END_OF_AUDIO Signal

When ending audio transmission, **must send bytes**:

```python
# CORRECT (bytes)
await websocket.send(b"END_OF_AUDIO")

# WRONG (string - will fail)
await websocket.send("END_OF_AUDIO")
```

## Configuration

All configuration is managed via `.env`:

```env
# WhisperLive
WHISPERLIVE_HOST=localhost
WHISPERLIVE_PORT=9090
WHISPERLIVE_LANGUAGE=en
WHISPERLIVE_MODEL=small
WHISPERLIVE_USE_VAD=false

# Audio
AUDIO_INPUT_MODE=microphone
AUDIO_DEVICE_INDEX=-1
AUDIO_DEVICE_NAME=
AUDIO_SAMPLE_RATE=16000
AUDIO_CHUNK_SIZE=4096

# Server
SERVER_PORT=8000
LOG_LEVEL=INFO

# UI
UI_CONSOLIDATED_MAX_CHARS=500
UI_SHOW_MULTIPLE_SEGMENT_BOXES=false

# Redis (optional)
REDIS_ENABLED=false
```

## Development

### Running Tests

```powershell
pytest
```

### Type Checking

```powershell
mypy clio_api_server
```

### Code Formatting

```powershell
ruff check .
ruff format .
```

### Running in Development Mode

```powershell
uvicorn clio_api_server.app.main:app --reload --port 8000
```

## Project Structure

```
clio-whisper/
├── clio_api_server/
│   ├── app/
│   │   ├── main.py           # FastAPI application entry point
│   │   ├── api/              # REST API endpoints
│   │   │   ├── control.py    # Pipeline control endpoints
│   │   │   ├── transcript.py # Transcript retrieval endpoints
│   │   │   └── streaming.py  # SSE/WebSocket streaming
│   │   ├── core/             # Configuration management
│   │   ├── services/         # Business logic
│   │   │   ├── pipeline.py           # Main orchestration pipeline
│   │   │   ├── audio_capture.py      # Audio input handling
│   │   │   ├── whisperlive_client.py # WhisperLive WebSocket client
│   │   │   └── transcript_aggregator.py # Deduplication engine
│   │   └── models/           # Pydantic data models
│   │       ├── transcript.py # Transcript segment models
│   │       ├── events.py      # Streaming event models
│   │       ├── metrics.py     # Performance metrics
│   │       └── control.py     # Control state models
│   └── tests/
├── whisper_live/              # Copied WhisperLive source (reference)
├── scripts/
│   ├── clio-whisper.ps1      # PowerShell management script
│   └── clio-whisper.sh        # Bash management script
├── ui/                        # Web UI assets
├── pyproject.toml            # Project configuration
└── README.md
```

## Transcript Aggregation

Clio Whisper maintains two transcript stores:

### Unconsolidated Transcript

- Contains all individual segments from WhisperLive
- Tracks states: partial → final → committed
- Maintains revision history for updates
- Includes timestamps and confidence scores

### Consolidated Transcript

- Single flowing paragraph
- Automatic deduplication:
  - Exact match removal
  - Substring detection
  - Similarity > 80% removal
- Hash-based replay prevention for reconnects
- Non-overlapping word stitching

### Aggregation Flow

```
PARTIAL → FINAL → COMMITTED → CONSOLIDATED
        (streaming)   (stable)    (deduplicated)
```

## Question Extraction

Automatically extracts questions from English transcripts:

**Explicit Questions**:
- Contains `?` character
- Interrogatives: what/how/why/when/where/who/which/whose

**Implicit Prompts**:
- "Imagine..."
- "Describe..."
- "Tell me..."
- "Consider..."
- "Think about..."

## Testing

### Official WhisperLive Client Test

```powershell
.venv\Scripts\python.exe test_whisperlive_official.py
```

### Streaming Integration Test

```powershell
.venv\Scripts\python.exe test_edge_streaming.py
```

### Simple Integration Test

```powershell
.venv\Scripts\python.exe test_simple_integration.py
```

## Troubleshooting

### Docker GPU Not Available

```powershell
# Verify GPU access
docker run --gpus all nvidia/cuda:12.0-base-ubuntu22.04 nvidia-smi
```

### Audio Device Not Found

```powershell
# List available devices
python -c "import sounddevice; print(sounddevice.query_devices())"
```

### WhisperLive Connection Failed

- Ensure container is running: `docker ps`
- Check logs: `docker logs clio-whisperlive`
- Verify port 9090 is not blocked

### No Audio Being Sent

If `audio_frames_sent: 0` in status:

1. Check audio queue reference in pipeline
2. Verify microphone permissions
3. Check audio device is not in use by another application

### Transcripts Not Appearing

1. Verify WhisperLive is processing: `docker logs clio-whisperlive`
2. Check pipeline state: `curl http://localhost:8000/v1/status`
3. Review consolidated transcript: `curl http://localhost:8000/v1/transcript/consolidated`

### Known Issues

1. **VAD Filtering**: With `use_vad=true`, non-speech audio (tones, silence) is filtered out. Use `use_vad=false` for testing with non-speech audio.

2. **Real-time Streaming**: Audio must be sent in real-time chunks (256ms delay between chunks) for proper processing. Sending all audio at once causes issues.

3. **Queue Overflow**: If audio queue fills faster than processed, frames are dropped. Increase queue maxsize in config if needed.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- [WhisperLive](https://github.com/collabora/WhisperLive) - Real-time Whisper transcription
- [OpenAI Whisper](https://github.com/openai/whisper) - Speech recognition model
- [Faster-Whisper](https://github.com/guillaumekln/faster-whisper) - Optimized Whisper implementation
- [Collabora](https://www.collabora.com/) - WhisperLive maintainers
