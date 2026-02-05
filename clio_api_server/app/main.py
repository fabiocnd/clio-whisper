import asyncio
import contextlib
from typing import AsyncGenerator

from fastapi import FastAPI, Depends, Request
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


def get_pipeline(request: Request) -> Pipeline:
    return request.app.state.pipeline


app.include_router(control_router)
app.include_router(transcript_router)
app.include_router(streaming_router)


@app.on_event("startup")
async def startup_event():
    log_level = settings.server_log_level
    logger.remove()
    logger.add(
        sink=lambda msg: print(msg, end=""),
        level=log_level,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
    )
    logger.info("Clio Whisper API starting up")
    app.state.pipeline = Pipeline()
    logger.info("Pipeline singleton created")


@app.on_event("shutdown")
async def shutdown_event():
    if hasattr(app.state, "pipeline") and app.state.pipeline:
        await app.state.pipeline.stop()
    logger.info("Clio Whisper API shutdown complete")


@app.get("/health")
async def health_check():
    """Root health check endpoint as per spec."""
    if hasattr(app.state, "pipeline") and app.state.pipeline:
        status = app.state.pipeline.get_status()
        if status.state.value in ("ERROR", "DEGRADED"):
            return {"status": "unhealthy", "reason": status.last_error or "Unknown error"}
        return {"status": "healthy", "whisperlive_connected": status.ws_connection == "connected"}
    return {"status": "healthy", "whisperlive_connected": False}


@app.get("/v1/questions")
async def get_questions():
    """Get extracted questions endpoint as per spec."""
    if hasattr(app.state, "pipeline") and app.state.pipeline:
        questions = app.state.pipeline.aggregator.get_questions()
        return {"questions": questions, "count": len(questions)}
    return {"questions": [], "count": 0}


@app.get("/", response_class=HTMLResponse)
async def root():
    return """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Clio Whisper - Real-time Transcription</title>
    <style>
        :root {
            --bg-primary: #0d1117;
            --bg-secondary: #161b22;
            --bg-tertiary: #21262d;
            --border-color: #30363d;
            --text-primary: #e6edf3;
            --text-secondary: #8b949e;
            --accent-blue: #58a6ff;
            --accent-green: #3fb950;
            --accent-red: #f85149;
            --accent-yellow: #d29922;
            --accent-purple: #a371f7;
        }

        * { box-sizing: border-box; margin: 0; padding: 0; }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            background: var(--bg-primary);
            color: var(--text-primary);
            min-height: 100vh;
            line-height: 1.6;
        }

        .header {
            background: var(--bg-secondary);
            border-bottom: 1px solid var(--border-color);
            padding: 16px 24px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            position: sticky;
            top: 0;
            z-index: 100;
        }

        .logo {
            display: flex;
            align-items: center;
            gap: 12px;
        }

        .logo-icon {
            width: 36px;
            height: 36px;
            background: linear-gradient(135deg, var(--accent-blue), var(--accent-purple));
            border-radius: 8px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: bold;
            font-size: 18px;
        }

        .logo h1 {
            font-size: 20px;
            font-weight: 600;
        }

        .status-bar {
            display: flex;
            gap: 16px;
            align-items: center;
        }

        .status-badge {
            display: flex;
            align-items: center;
            gap: 6px;
            padding: 6px 12px;
            background: var(--bg-tertiary);
            border-radius: 20px;
            font-size: 13px;
        }

        .status-dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            animation: pulse 2s infinite;
        }

        .status-dot.connected { background: var(--accent-green); }
        .status-dot.disconnected { background: var(--accent-red); }
        .status-dot.connecting { background: var(--accent-yellow); }

        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }

        .main-container {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
            padding: 20px;
            max-width: 1600px;
            margin: 0 auto;
        }

        @media (max-width: 1200px) {
            .main-container { grid-template-columns: 1fr; }
        }

        .panel {
            background: var(--bg-secondary);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            overflow: hidden;
        }

        .panel-header {
            padding: 16px 20px;
            border-bottom: 1px solid var(--border-color);
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .panel-title {
            font-size: 14px;
            font-weight: 600;
            color: var(--text-secondary);
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        .panel-body {
            padding: 16px 20px;
            max-height: 400px;
            overflow-y: auto;
        }

        .segments-list {
            display: flex;
            flex-direction: column;
            gap: 8px;
        }

        .segment-item {
            padding: 12px 16px;
            background: var(--bg-tertiary);
            border-radius: 8px;
            border-left: 3px solid var(--accent-blue);
            transition: all 0.2s ease;
        }

        .segment-item.final {
            border-left-color: var(--accent-green);
            background: rgba(63, 185, 80, 0.1);
        }

        .segment-item.committed {
            border-left-color: var(--accent-purple);
            background: rgba(163, 113, 247, 0.1);
        }

        .segment-header {
            display: flex;
            justify-content: space-between;
            margin-bottom: 6px;
            font-size: 12px;
            color: var(--text-secondary);
        }

        .segment-status {
            font-weight: 600;
            text-transform: uppercase;
            font-size: 10px;
            padding: 2px 8px;
            border-radius: 4px;
        }

        .segment-status.partial { background: var(--accent-yellow); color: #000; }
        .segment-status.final { background: var(--accent-green); color: #000; }
        .segment-status.committed { background: var(--accent-purple); color: #fff; }

        .segment-text {
            font-size: 14px;
            line-height: 1.5;
        }

        .consolidated-text {
            font-size: 16px;
            line-height: 1.8;
            color: var(--text-primary);
            white-space: pre-wrap;
        }

        .questions-grid {
            display: grid;
            gap: 10px;
        }

        .question-item {
            padding: 14px 16px;
            background: var(--bg-tertiary);
            border-radius: 8px;
            border-left: 3px solid var(--accent-yellow);
        }

        .question-text {
            font-size: 14px;
            margin-bottom: 8px;
        }

        .question-meta {
            display: flex;
            gap: 12px;
            font-size: 12px;
            color: var(--text-secondary);
        }

        .metrics-grid {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 12px;
        }

        .metric-card {
            padding: 16px;
            background: var(--bg-tertiary);
            border-radius: 8px;
            text-align: center;
        }

        .metric-value {
            font-size: 28px;
            font-weight: 700;
            color: var(--accent-blue);
            margin-bottom: 4px;
        }

        .metric-label {
            font-size: 12px;
            color: var(--text-secondary);
            text-transform: uppercase;
        }

        .events-log {
            font-family: 'SF Mono', 'Fira Code', monospace;
            font-size: 12px;
            background: #0d1117;
            border-radius: 8px;
            padding: 12px;
            max-height: 200px;
            overflow-y: auto;
        }

        .event-item {
            padding: 4px 0;
            border-bottom: 1px solid var(--border-color);
        }

        .event-time { color: var(--text-secondary); margin-right: 8px; }
        .event-type { font-weight: 600; margin-right: 8px; }
        .event-type.partial { color: var(--accent-yellow); }
        .event-type.final { color: var(--accent-green); }
        .event-type.system { color: var(--accent-blue); }
        .event-type.server_ready { color: var(--accent-purple); }

        .controls {
            padding: 20px 24px;
            background: var(--bg-secondary);
            border-top: 1px solid var(--border-color);
            display: flex;
            gap: 12px;
        }

        .btn {
            padding: 12px 24px;
            border: none;
            border-radius: 8px;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s ease;
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .btn:hover { transform: translateY(-1px); opacity: 0.9; }
        .btn:active { transform: translateY(0); }

        .btn-start {
            background: linear-gradient(135deg, var(--accent-green), #2ea043);
            color: white;
        }

        .btn-stop {
            background: linear-gradient(135deg, var(--accent-red), #da3633);
            color: white;
        }

        .btn:disabled {
            opacity: 0.5;
            cursor: not-allowed;
            transform: none;
        }

        .empty-state {
            text-align: center;
            padding: 40px 20px;
            color: var(--text-secondary);
        }

        .empty-state svg {
            width: 48px;
            height: 48px;
            margin-bottom: 16px;
            opacity: 0.5;
        }
    </style>
</head>
<body>
    <header class="header">
        <div class="logo">
            <div class="logo-icon">CW</div>
            <h1>Clio Whisper</h1>
        </div>
        <div class="status-bar">
            <div class="status-badge">
                <div class="status-dot disconnected" id="wsStatusDot"></div>
                <span id="wsStatusText">Disconnected</span>
            </div>
            <div class="status-badge">
                <span id="segmentsCount">0</span> segments
            </div>
            <div class="status-badge">
                <span id="questionsCount">0</span> questions
            </div>
        </div>
    </header>

    <div class="main-container">
        <div class="panel">
            <div class="panel-header">
                <span class="panel-title">Live Segments (Unconsolidated)</span>
                <span style="font-size: 12px; color: var(--text-secondary);" id="lastUpdate"></span>
            </div>
            <div class="panel-body">
                <div id="segmentsList" class="segments-list">
                    <div class="empty-state">
                        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
                        </svg>
                        <p>No segments yet. Start recording to see live transcription.</p>
                    </div>
                </div>
            </div>
        </div>

        <div class="panel">
            <div class="panel-header">
                <span class="panel-title">Consolidated Transcript</span>
                <span style="font-size: 12px; color: var(--text-secondary);" id="consolidatedRev"></span>
            </div>
            <div class="panel-body">
                <div id="consolidatedText" class="consolidated-text">Waiting for transcript...</div>
            </div>
        </div>

        <div class="panel">
            <div class="panel-header">
                <span class="panel-title">Questions Extracted</span>
            </div>
            <div class="panel-body">
                <div id="questionsList" class="questions-grid">
                    <div class="empty-state">
                        <p>No questions extracted yet.</p>
                    </div>
                </div>
            </div>
        </div>

        <div class="panel">
            <div class="panel-header">
                <span class="panel-title">Metrics</span>
            </div>
            <div class="panel-body">
                <div class="metrics-grid">
                    <div class="metric-card">
                        <div class="metric-value" id="metricReceived">0</div>
                        <div class="metric-label">Received</div>
                    </div>
                    <div class="metric-card">
                        <div class="metric-value" id="metricCommitted">0</div>
                        <div class="metric-label">Committed</div>
                    </div>
                    <div class="metric-card">
                        <div class="metric-value" id="metricDropped">0</div>
                        <div class="metric-label">Dropped</div>
                    </div>
                    <div class="metric-card">
                        <div class="metric-value" id="metricReconnects">0</div>
                        <div class="metric-label">Reconnects</div>
                    </div>
                    <div class="metric-card">
                        <div class="metric-value" id="metricSSE">0</div>
                        <div class="metric-label">SSE Clients</div>
                    </div>
                    <div class="metric-card">
                        <div class="metric-value" id="metricQueue">0</div>
                        <div class="metric-label">Queue Depth</div>
                    </div>
                </div>
            </div>
        </div>

        <div class="panel">
            <div class="panel-header">
                <span class="panel-title">Streaming Events Log</span>
            </div>
            <div class="panel-body">
                <div id="eventsLog" class="events-log">
                    <div class="event-item"><span class="event-time">--:--:--</span><span class="event-type">system</span>Waiting for events...</div>
                </div>
            </div>
        </div>
    </div>

    <div class="controls">
        <button class="btn btn-start" id="startBtn" onclick="startPipeline()">
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="currentColor" viewBox="0 0 16 16">
                <path d="M11.596 8.697l-6.363 3.692c-.54.313-1.233-.066-1.233-.697V4.308c0-.63.693-1.01 1.233-.696l6.363 3.692a.802.802 0 0 1 0 1.393z"/>
            </svg>
            Start Recording
        </button>
        <button class="btn btn-stop" id="stopBtn" onclick="stopPipeline()" disabled>
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="currentColor" viewBox="0 0 16 16">
                <path d="M5.5 3.5A1.5 1.5 0 0 1 7 5v6a1.5 1.5 0 0 1-3 0V5a1.5 1.5 0 0 1 1.5-1.5zm5 0A1.5 1.5 0 0 1 12 5v6a1.5 1.5 0 0 1-3 0V5a1.5 1.5 0 0 1 1.5-1.5z"/>
            </svg>
            Stop Recording
        </button>
    </div>

    <script>
        let eventSource = null;
        let segments = [];
        let events = [];

        function updateStatus(state, wsStatus) {
            const wsDot = document.getElementById('wsStatusDot');
            const wsText = document.getElementById('wsStatusText');
            const startBtn = document.getElementById('startBtn');
            const stopBtn = document.getElementById('stopBtn');

            wsDot.className = 'status-dot';

            if (state === 'RUNNING') {
                if (wsStatus === 'connected') {
                    wsDot.classList.add('connected');
                    wsText.textContent = 'Recording & Connected';
                    startBtn.disabled = true;
                    stopBtn.disabled = false;
                } else {
                    wsDot.classList.add('connecting');
                    wsText.textContent = 'Recording & Connecting...';
                    startBtn.disabled = true;
                    stopBtn.disabled = false;
                }
            } else {
                wsDot.classList.add('disconnected');
                wsText.textContent = 'Stopped';
                startBtn.disabled = false;
                stopBtn.disabled = true;
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
                        updateQuestions();
                    }
                    if (event.event_type === 'server_ready' || event.event_type === 'disconnect') {
                        checkStatus();
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
            const eventsEl = document.getElementById('eventsLog');
            const time = new Date().toLocaleTimeString();
            const typeClass = event.event_type || 'system';
            events.unshift({ time, type: event.event_type, text: event.text || JSON.stringify(event.data).substring(0, 80) });

            if (events.length > 50) events.pop();

            const eventsHtml = events.map(function(ev) {
                return '<div class="event-item"><span class="event-time">' + ev.time + '</span><span class="event-type ' + ev.type + '">' + (ev.type || 'system') + '</span>' + ev.text + '</div>';
            }).join('');

            if (document.getElementById('eventsLog')) {
                document.getElementById('eventsLog').innerHTML = eventsHtml;
            }
        }

        async function updateSegments() {
            try {
                const response = await fetch('/v1/transcript/unconsolidated');
                const data = await response.json();
                segments = data.segments || [];

                document.getElementById('segmentsCount').textContent = data.total_segments || 0;
                document.getElementById('lastUpdate').textContent = data.last_update ? new Date(data.last_update).toLocaleTimeString() : '';

                const segmentsEl = document.getElementById('segmentsList');

                if (segments.length === 0) {
                    segmentsEl.innerHTML = '<div class="empty-state"><p>No segments yet.</p></div>';
                    return;
                }

                const html = segments.slice(-20).reverse().map(function(s) {
                    var statusClass = s.status === 'final' ? 'final' : (s.status === 'committed' ? 'committed' : 'partial');
                    return '<div class="segment-item ' + statusClass + '"><div class="segment-header"><span>' + (s.start_time ? s.start_time.toFixed(1) : '0.0') + 's - ' + (s.end_time ? s.end_time.toFixed(1) : '0.0') + 's</span><span class="segment-status ' + s.status + '">' + s.status + '</span></div><div class="segment-text">' + (s.text || '') + '</div></div>';
                }).join('');

                segmentsEl.innerHTML = html;
            } catch (err) {
                console.error('Error updating segments:', err);
            }
        }

        async function updateConsolidated() {
            try {
                const response = await fetch('/v1/transcript/consolidated');
                const data = await response.json();

                document.getElementById('consolidatedText').textContent = data.text || 'Waiting for transcript...';
                document.getElementById('consolidatedRev').textContent = 'v' + data.revision + ' | ' + (data.segment_count || 0) + ' segments';
            } catch (err) {
                console.error('Error updating consolidated:', err);
            }
        }

        async function updateQuestions() {
            try {
                const response = await fetch('/v1/questions');
                const data = await response.json();
                const questions = data.questions || [];

                document.getElementById('questionsCount').textContent = data.count || 0;

                const questionsEl = document.getElementById('questionsList');

                if (questions.length === 0) {
                    questionsEl.innerHTML = '<div class="empty-state"><p>No questions extracted yet.</p></div>';
                    return;
                }

                const html = questions.slice(-10).reverse().map(function(q) {
                    return '<div class="question-item"><div class="question-text">' + q.text + '</div><div class="question-meta"><span>' + (q.is_explicit ? 'Explicit' : 'Implicit') + '</span><span>First: ' + new Date(q.first_seen).toLocaleTimeString() + '</span></div></div>';
                }).join('');

                questionsEl.innerHTML = html;
            } catch (err) {
                console.error('Error updating questions:', err);
            }
        }

        async function checkStatus() {
            try {
                const response = await fetch('/v1/status');
                const data = await response.json();

                updateStatus(data.state, data.ws_connection);

                const queues = data.queue_depths || {};
                document.getElementById('metricReceived').textContent = queues.segments_received || 0;
                document.getElementById('metricCommitted').textContent = queues.segments_committed || 0;
                document.getElementById('metricDropped').textContent = queues.segments_dropped || 0;
                document.getElementById('metricReconnects').textContent = queues.reconnect_count || 0;
                document.getElementById('metricSSE').textContent = queues.connected_sse_clients || 0;
                document.getElementById('metricQueue').textContent = (queues.audio_queue_depth || 0) + (queues.event_queue_depth || 0);

                if (data.state === 'RUNNING') {
                    updateSegments();
                    updateConsolidated();
                    updateQuestions();
                }
            } catch (err) {
                console.error('Error checking status:', err);
            }
        }

        setInterval(checkStatus, 2000);
        checkStatus();
    </script>
</body>
</html>
"""


def main():
    config = Config(
        app=app,
        host=settings.server_host,
        port=settings.server_port,
        log_level=settings.server_log_level.lower(),
    )
    server = Server(config)
    server.run()


if __name__ == "__main__":
    main()
