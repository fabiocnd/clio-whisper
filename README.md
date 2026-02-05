# Clio Whisper

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.109.0+-00a393.svg)](https://fastapi.tiangolo.com/)
[![Docker](https://img.shields.io/badge/Docker-2496ed.svg)](https://www.docker.com/)

Production-grade real-time transcription system powered by OpenAI's Whisper models through [WhisperLive](https://github.com/collabora/WhisperLive).

## Overview

Clio Whisper is a Windows-hosted ecosystem that provides:

- **Real-time Speech-to-Text**: Captures audio from microphone and streams to Whisper for transcription
- **Deterministic Transcript Aggregation**: Maintains clean, deduplicated transcript history
- **REST API & Streaming**: Exposes endpoints via [FastAPI](https://fastapi.tiangolo.com/) with SSE/WebSocket support
- **Question Extraction**: Automatically detects and extracts questions from transcripts
- **GPU Acceleration**: Leverages CUDA-enabled Docker container for fast inference

## Technology Stack

| Component | Technology | Description |
|-----------|------------|-------------|
| **Transcription Engine** | [WhisperLive](https://github.com/collabora/WhisperLive) | OpenAI Whisper speech recognition in Docker |
| **Audio Capture** | [SoundDevice](https://python-sounddevice.readthedocs.io/) | Cross-platform audio input handling |
| **Web Framework** | [FastAPI](https://fastapi.tiangolo.com/) | High-performance async API framework |
| **Real-time Streaming** | [SSE (Server-Sent Events)](https://developer.mozilla.org/en-US/docs/Web/Server-Sent_Events) & [WebSocket](https://websockets.readthedocs.io/) | Bidirectional event streaming |
| **Data Validation** | [Pydantic](https://docs.pydantic.dev/) | Runtime data validation with Python types |
| **Logging** | [Loguru](https://loguru.readthedocs.io/) | Structured logging with colors |
| **Containerization** | [Docker](https://www.docker.com/) | GPU-accelerated Whisper deployment |
| **Code Quality** | [Ruff](https://docs.astral.sh/ruff/) & [MyPy](https://mypy-lang.org/) | Linting and type checking |

## Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────────────┐
│   Audio Input   │────▶│  clio-api-server│────▶│  WhisperLive GPU       │
│  (Microphone)   │     │   (FastAPI)     │     │  (Docker/CUDA)         │
└─────────────────┘     └────────┬────────┘     └─────────────────────────┘
                                  │
                                  ▼
                         ┌─────────────────┐
                         │   Aggregator    │
                         │ (Transcript Store)│
                         └────────┬────────┘
                                  │
            ┌────────────────────┼────────────────────┐
            ▼                    ▼                    ▼
     ┌─────────────┐      ┌─────────────┐      ┌─────────────┐
     │  REST API   │      │  SSE Stream │      │ WebSocket   │
     └─────────────┘      └─────────────┘      └─────────────┘
```

## Use Cases

Clio Whisper is ideal for:

- **Meeting Transcription**: Automatically transcribe meetings in real-time
- **Interview Documentation**: Create searchable text from audio recordings
- **Accessibility**: Provide live captions for events or presentations
- **Content Creation**: Generate transcripts for podcasts, videos, or broadcasts
- **Voice Analytics**: Extract questions and insights from conversations
- **Legal/Medical Dictation**: Capture spoken content for documentation

## Quick Start

### Prerequisites

| Requirement | Minimum | Recommended |
|------------|---------|-------------|
| OS | Windows 11 | Windows 11 |
| Python | 3.11+ | 3.11+ |
| RAM | 8GB | 16GB+ |
| GPU | Optional (CPU works) | NVIDIA CUDA-capable |
| Docker | Desktop with GPU | Desktop with RTX GPU |

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
# Start all services (WhisperLive Docker + API Server)
.\scripts\clio-whisper.ps1 start-all

# Check status
.\scripts\clio-whisper.ps1 status

# Stop all services
.\scripts\clio-whisper.ps1 stop-all
```

Or manually:

```powershell
# Start WhisperLive GPU container
docker run -d --gpus all -p 9090:9090 --name clio-whisperlive ghcr.io/collabora/whisperlive-gpu:latest

# Start API server
uvicorn clio_api_server.app.main:app --host 0.0.0.0 --port 8000
```

### Access

- **UI Dashboard**: http://localhost:8000/
- **API Documentation**: http://localhost:8000/docs
- **Health Check**: http://localhost:8000/health

### Start Recording

```powershell
# Via API
curl -X POST http://localhost:8000/v1/control/start

# Via UI - click "Start Recording"
```

## API Reference

### Control Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check |
| GET | `/v1/status` | Pipeline status |
| POST | `/v1/control/start` | Start recording |
| POST | `/v1/control/stop` | Stop recording |
| GET | `/v1/metrics` | Operational metrics |

### Transcript Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/v1/transcript/unconsolidated` | Segmented transcript |
| GET | `/v1/transcript/consolidated` | Single paragraph |
| GET | `/v1/questions` | Extracted questions |

### Streaming Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/v1/stream/transcript` | SSE stream |
| WS | `/v1/stream/transcript` | WebSocket stream |

## WhisperLive Integration

Clio Whisper uses the [WhisperLive project](https://github.com/collabora/WhisperLive) which provides:

> "WhisperLive is a realtime transcription app using OpenAI's Whisper. It works with faster-whisper backend which is 4x faster than openai-whisper."

### WebSocket Protocol

```json
// Connect to: ws://localhost:9090

// Send configuration:
{
  "uid": "unique-client-id",
  "language": "en",
  "task": "transcribe",
  "model": "base",
  "use_vad": true,
  "send_last_n_segments": 10
}

// Receive events:
{
  "message": "SERVER_READY",
  "segments": [
    {
      "start": 0.0,
      "end": 3.5,
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
| Format | 16-bit PCM |
| Chunk Size | 4096 samples (256ms) |

## Configuration

All configuration is managed via `.env`:

```env
# WhisperLive
WHISPERLIVE_HOST=localhost
WHISPERLIVE_PORT=9090
WHISPERLIVE_LANGUAGE=en
WHISPERLIVE_MODEL=base

# Audio
AUDIO_INPUT_MODE=microphone
AUDIO_DEVICE_INDEX=-1
AUDIO_SAMPLE_RATE=16000
AUDIO_CHUNK_SIZE=4096

# Server
SERVER_PORT=8000
LOG_LEVEL=INFO
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
│   │   │   ├── pipeline.py   # Main orchestration pipeline
│   │   │   ├── audio_capture.py    # Audio input handling
│   │   │   ├── whisperlive_client.py # WhisperLive WebSocket client
│   │   │   └── transcript_aggregator.py # Deduplication engine
│   │   └── models/           # Pydantic data models
│   │       ├── transcript.py # Transcript segment models
│   │       ├── events.py      # Streaming event models
│   │       ├── metrics.py     # Performance metrics
│   │       └── control.py    # Control state models
│   └── tests/
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

- Contains all individual segments
- Tracks partial, final, and committed states
- Maintains revision history for updates

### Consolidated Transcript

- Single flowing paragraph
- Automatic deduplication (exact, substring, similarity >80%)
- Hash-based replay prevention for reconnects
- Non-overlapping word stitching

### Aggregation Flow

```
PARTIAL → FINAL → COMMITTED → CONSOLIDATED
```

## Question Extraction

Automatically extracts questions from English transcripts:

**Explicit Questions**:
- Contains `?`
- Interrogatives: what/how/why/when/where/who/which/whose

**Implicit Prompts**:
- "Imagine..."
- "Describe..."
- "Tell me..."
- "Consider..."

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

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- [WhisperLive](https://github.com/collabora/WhisperLive) - Real-time Whisper transcription
- [OpenAI Whisper](https://github.com/openai/whisper) - Speech recognition model
- [Faster-Whisper](https://github.com/guillaumekln/faster-whisper) - Optimized Whisper implementation
- [Collabora](https://www.collabora.com/) - WhisperLive maintainers
