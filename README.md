# Clio Whisper

Production-grade WhisperLive client with transcript aggregation, REST API, and real-time streaming.

## Overview

Clio Whisper is a Windows-hosted ecosystem that:

1. Runs WhisperLive GPU Server in Docker on port 9090
2. Captures audio from the default microphone (configurable)
3. Streams audio to WhisperLive for transcription
4. Maintains clean, deterministic transcript history
5. Exposes REST endpoints and real-time streaming APIs (SSE/WebSocket)
6. Extracts and accumulates English-only questions/prompts
7. Provides a minimal English UI

## Prerequisites

- Windows 11 with Docker Desktop (GPU support)
- Python 3.11+
- 8GB+ RAM (for Whisper models)
- GPU with CUDA support (optional but recommended)

## Quick Start

### 1. Clone and Setup

```powershell
cd D:\repo
git clone https://github.com/flopescnd/clio-whisper.git
cd clio-whisper

# Create virtual environment
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e .
```

### 2. Configure Environment

```powershell
copy .env.example .env
# Edit .env with your preferences
```

### 3. Start the Ecosystem

```powershell
.\scripts\start-ecosystemThis will:
- Start.ps1
```

 WhisperLive GPU container on port 9090
- Wait for readiness
- Start the API server on port 8000

### 4. Access the UI

Open http://localhost:8000/ in your browser.

### 5. Start Recording

Click "Start Recording" in the UI or:

```powershell
curl -X POST http://localhost:8000/v1/control/start
```

## Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   Audio Input   │────▶│  clio-api-server│────▶│  WhisperLive    │
│  (Microphone)   │     │   (FastAPI)     │     │   (Docker)      │
└─────────────────┘     └────────┬────────┘     └─────────────────┘
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

## API Endpoints

### Control

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check |
| GET | `/v1/status` | Pipeline status |
| POST | `/v1/control/start` | Start recording |
| POST | `/v1/control/stop` | Stop recording |
| GET | `/v1/metrics` | Operational metrics |

### Transcript

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/v1/transcript/unconsolidated` | Segmented transcript |
| GET | `/v1/transcript/consolidated` | Single paragraph |
| GET | `/v1/questions` | Extracted questions |

### Streaming

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/v1/stream/transcript` | SSE stream |
| GET | `/v1/stream/transcript` | WebSocket stream |

## WhisperLive Protocol

Clio Whisper implements the WhisperLive WebSocket protocol:

### WebSocket URL
```
ws://localhost:9090
```

### Initial Configuration
```json
{
  "uid": "c3f7a1b2-d4e5-6789-abcd-ef0123456789",
  "language": "en",
  "task": "transcribe",
  "model": "base",
  "use_vad": true,
  "send_last_n_segments": 10
}
```

### Audio Format
- Sample Rate: 16000 Hz
- Channels: 1 (Mono)
- Format: 16-bit PCM
- Chunk Size: 4096 samples (256ms)

### Server Events
- `SERVER_READY`: Server is ready for audio
- `language_detected`: Language detection result
- `partial`: Partial transcription segment
- `final`: Final transcription segment
- `WAIT`: Server is busy
- `DISCONNECT`: Server closed connection

## Configuration

All configuration is managed via `.env`:

```env
# WhisperLive
WHISPERLIVE_HOST=localhost
WHISPERLIVE_PORT=9090
WHISPERLIVE_LANGUAGE=en
WHISPERLIVE_MODEL=base

# Audio
AUDIO_INPUT_MODE=microphone  # or 'file'
AUDIO_DEVICE_INDEX=-1        # -1 for default
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
│   │   ├── main.py           # FastAPI application
│   │   ├── api/              # REST endpoints
│   │   ├── core/             # Configuration
│   │   ├── services/         # Business logic
│   │   └── models/           # Pydantic models
│   └── tests/
├── scripts/
│   ├── start-ecosystem.ps1   # Start script
│   └── stop-ecosystem.ps1   # Stop script
├── ui/                       # Web UI
├── pyproject.toml           # Project config
└── README.md
```

## Transcript Aggregation

Clio Whisper maintains two transcript stores:

1. **Unconsolidated**: Segmented transcript with partial and final segments
2. **Consolidated**: Single running paragraph with no duplicates or overlaps

### Aggregation Policy

- Segments transition: `PARTIAL` → `FINAL` → `COMMITTED`
- Consolidated transcript updates only on `COMMITTED` segments
- Deterministic ordering by timestamp
- Automatic deduplication and revision tracking

## Question Extraction

Extracts English-only questions from final transcripts:

- **Explicit**: Questions with `?` or interrogatives (what/how/why/when/where/who)
- **Implicit**: Prompts like "Imagine...", "Describe...", "Tell me..."

## Logging

Structured JSON logging with configurable levels:

```powershell
LOG_LEVEL=DEBUG  # Verbose logging
LOG_LEVEL=INFO    # Standard logging
LOG_LEVEL=WARN    # Warnings only
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

## License

MIT License
