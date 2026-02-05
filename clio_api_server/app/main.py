import asyncio
import contextlib
from typing import AsyncGenerator

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger
from uvicorn import Config, Server

from clio_api_server.app.api import transcript_router, control_router, streaming_router
from clio_api_server.app.core.config import get_settings
from clio_api_server.app.services.pipeline import Pipeline


settings = get_settings()

app = FastAPI(
    title="Clio Whisper API",
    description="Production-grade WhisperLive client with transcript aggregation",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_pipeline: Pipeline | None = None


def get_pipeline() -> Pipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = Pipeline()
    return _pipeline


app.include_router(control_router)
app.include_router(transcript_router)
app.include_router(streaming_router)


@app.on_event("startup")
async def startup_event():
    log_level = settings.server.log_level
    logger.remove()
    logger.add(
        sink=lambda msg: print(msg, end=""),
        level=log_level,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
    )
    logger.info("Clio Whisper API starting up")


@app.on_event("shutdown")
async def shutdown_event():
    global _pipeline
    if _pipeline:
        await _pipeline.stop()
    logger.info("Clio Whisper API shutdown complete")


@app.get("/", response_class=HTMLResponse)
async def root():
    return """
>
    <html>
    <head>
        <title>Clio Whisper</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 20px; background: #1a1a2e; color: #eee; }
            h1 { color: #00d4ff; }
            .status { padding: 10px; margin: 10px 0; border-radius: 5px; }
            .running { background: #00c853; }
            .stopped { background: #ff1744; }
            .segments { background: #16213e; padding: 15px; margin: 10px 0; border-radius: 5px; max-height: 300px; overflow-y: auto; }
            .consolidated { background: #0f3460; padding: 15px; margin: 10px 0; border-radius: 5px; }
            .events { background: #0a0a0a; padding: 10px; margin: 10px 0; border-radius: 5px; max-height: 200px; overflow-y: auto; font-family: monospace; font-size: 12px; }
            button { padding: 10px 20px; margin: 5px; cursor: pointer; border: none; border-radius: 5px; font-weight: bold; }
            .start-btn { background: #00c853; color: white; }
            .stop-btn { background: #ff1744; color: white; }
            button:hover { opacity: 0.8; }
            #connectionStatus { font-size: 24px; }
        </style>
    </head>
    <body>
        <h1>🎙️ Clio Whisper</h1>
        <div id="connectionStatus" class="status stopped">Disconnected</div>
        <div>
            <button class="start-btn" onclick="startPipeline()">Start Recording</button>
            <button class="stop-btn" onclick="stopPipeline()">Stop Recording</button>
        </div>
        <h2>Live Segments (Unconsolidated)</h2>
        <div id="segments" class="segments">No segments yet...</div>
        <h2>Consolidated Transcript</h2>
        <div id="consolidated" class="consolidated">Waiting for transcript...</div>
        <h2>Streaming Events</h2>
        <div id="events" class="events">No events...</div>
        <script>
            let eventSource = null;
            
            function updateStatus(state, wsStatus) {
                const statusEl = document.getElementById('connectionStatus');
                if (state === 'RUNNING' && wsStatus === 'connected') {
                    statusEl.textContent = '🟢 Recording & Connected';
                    statusEl.className = 'status running';
                } else if (state === 'RUNNING') {
                    statusEl.textContent = '🟡 Recording & Connecting...';
                    statusEl.className = 'status stopped';
                } else {
                    statusEl.textContent = '🔴 Stopped';
                    statusEl.className = 'status stopped';
                }
            }
            
            async function startPipeline() {
                await fetch('/v1/control/start', { method: 'POST' });
                connectSSE();
                setTimeout(checkStatus, 500);
            }
            
            async function stopPipeline() {
                await fetch('/v1/control/stop', { method: 'POST' });
                disconnectSSE();
                setTimeout(checkStatus, 500);
            }
            
            function connectSSE() {
                disconnectSSE();
                eventSource = new EventSource('/v1/stream/transcript');
                eventSource.onmessage = function(e) {
                    try {
                        const event = JSON.parse(e.data);
                        addEvent(event);
                        if (event.event_type === 'partial' || event.event_type === 'final') {
                            updateSegments();
                        }
                        if (event.event_type === 'final') {
                            updateConsolidated();
                        }
                    } catch (err) {
                        console.error('Error parsing event:', err);
                    }
                };
                eventSource.onerror = function() {
                    console.log('SSE connection lost');
                };
            }
            
            function disconnectSSE() {
                if (eventSource) {
                    eventSource.close();
                    eventSource = null;
                }
            }
            
            function addEvent(event) {
                const eventsEl = document.getElementById('events');
                const time = new Date().toLocaleTimeString();
                eventsEl.innerHTML = `[${time}] ${event.event_type}: ${event.text || JSON.stringify(event.data).substring(0, 100)}<br>` + eventsEl.innerHTML;
                if (eventsEl.children.length > 50) {
                    eventsEl.innerHTML = eventsEl.innerHTML.split('<br>').slice(0, 50).join('<br>');
                }
            }
            
            async function updateSegments() {
                const response = await fetch('/v1/transcript/unconsolidated');
                const data = await response.json();
                const segmentsEl = document.getElementById('segments');
                segmentsEl.innerHTML = data.segments.map(s => 
                    `<div>[${s.start_time.toFixed(1)}s - ${s.end_time.toFixed(1)}s] <span style="color: ${s.status === 'final' ? '#00ff00' : '#ffff00'}">${s.status}</span>: ${s.text}</div>`
                ).reverse().join('');
            }
            
            async function updateConsolidated() {
                const response = await fetch('/v1/transcript/consolidated');
                const data = await response.json();
                document.getElementById('consolidated').textContent = data.text || 'Waiting for transcript...';
            }
            
            async function checkStatus() {
                const response = await fetch('/v1/status');
                const data = await response.json();
                updateStatus(data.state, data.ws_connection);
            }
            
            setInterval(checkStatus, 2000);
            checkStatus();
        </script>
    </body>
    </html>
    """


async def lifespan(app: FastAPI) -> AsyncGenerator:
    global _pipeline
    _pipeline = Pipeline()
    yield
    await _pipeline.stop()


def main():
    config = Config(
        app=app,
        host=settings.server.host,
        port=settings.server.port,
        log_level=settings.server.log_level.lower(),
    )
    server = Server(config)
    server.run()


if __name__ == "__main__":
    main()
