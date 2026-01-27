# WebSocket Streaming Guide

Real-time agent execution monitoring via WebSocket streaming of EventBus events.

## Quick Start

**1. Start the WebSocket server:**

```bash
PYTHONPATH=core python -m framework stream --host 0.0.0.0 --port 8765
```

**2. Connect a client and subscribe:**

```javascript
const ws = new WebSocket("ws://localhost:8765");

ws.onopen = () => {
  // Subscribe to all events
  ws.send(JSON.stringify({ action: "subscribe" }));

  // Or filter by stream/execution/event types
  ws.send(
    JSON.stringify({
      action: "subscribe",
      stream_id: "webhook",
      event_types: [
        "EXECUTION_STARTED",
        "EXECUTION_COMPLETED",
        "GOAL_PROGRESS",
      ],
    }),
  );
};

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);

  if (data.type === "event") {
    console.log(`${data.event.type}:`, data.event.data);

    // Update UI, logs, dashboards, etc.
    updateDashboard(data.event);
  }
};
```

## Real-World Integration

### 1. Agent Execution Streaming

When running an agent, the EventBus automatically publishes events if a WebSocket server is connected:

```python
# Your agent code (no changes needed - EventBus is already integrated)
from framework.graph.executor import GraphExecutor
from framework.runtime.event_bus import EventBus

# EventBus is global singleton - server auto-bridges events
executor = GraphExecutor(
    graph=my_graph,
    goal=my_goal,
    runtime=runtime,
    stream_id="webhook"  # Events tagged with this ID
)

result = await executor.execute(input_data)
# Events automatically emitted:
# - EXECUTION_STARTED
# - NODE_EXECUTED (for each node)
# - GOAL_PROGRESS
# - EXECUTION_COMPLETED/FAILED
```

### 2. Web Dashboard Integration

**Frontend (React/Vue/Svelte):**

```javascript
// hooks/useAgentStream.js
import { useEffect, useState } from "react";

export function useAgentStream(streamId) {
  const [events, setEvents] = useState([]);
  const [status, setStatus] = useState("idle");
  const [progress, setProgress] = useState(0);

  useEffect(() => {
    const ws = new WebSocket("ws://localhost:8765");

    ws.onopen = () => {
      ws.send(
        JSON.stringify({
          action: "subscribe",
          stream_id: streamId,
        }),
      );
    };

    ws.onmessage = (msg) => {
      const data = JSON.parse(msg.data);

      if (data.type === "event") {
        const event = data.event;
        setEvents((prev) => [...prev, event]);

        switch (event.type) {
          case "execution_started":
            setStatus("running");
            break;
          case "goal_progress":
            setProgress(event.data.progress * 100);
            break;
          case "execution_completed":
            setStatus("completed");
            break;
          case "execution_failed":
            setStatus("failed");
            break;
        }
      }
    };

    return () => ws.close();
  }, [streamId]);

  return { events, status, progress };
}
```

**Dashboard Component:**

```jsx
function AgentDashboard({ streamId }) {
  const { events, status, progress } = useAgentStream(streamId);

  return (
    <div>
      <h2>Agent Status: {status}</h2>
      <ProgressBar value={progress} />

      <div className="event-log">
        {events.map((event, i) => (
          <EventCard key={i} event={event} />
        ))}
      </div>
    </div>
  );
}
```

### 3. Backend Webhook Integration

Stream agent events to external services:

```python
# webhook_bridge.py
import asyncio
import json
import httpx
import websockets

async def bridge_to_webhook(webhook_url: str, stream_id: str):
    """Forward agent events to external webhook."""
    async with websockets.connect('ws://localhost:8765') as ws:
        # Subscribe
        await ws.send(json.dumps({
            'action': 'subscribe',
            'stream_id': stream_id
        }))

        # Forward events
        async with httpx.AsyncClient() as client:
            async for message in ws:
                data = json.loads(message)

                if data['type'] == 'event':
                    # POST to external webhook
                    await client.post(
                        webhook_url,
                        json=data['event'],
                        headers={'X-Stream-ID': stream_id}
                    )

# Usage
asyncio.run(bridge_to_webhook(
    webhook_url='https://api.example.com/webhooks/agent-events',
    stream_id='production-agent-1'
))
```

### 4. Monitoring & Alerting

```python
# monitor.py
import asyncio
import json
import websockets
from datetime import datetime

class AgentMonitor:
    def __init__(self, alert_callback):
        self.alert_callback = alert_callback
        self.executions = {}

    async def monitor(self):
        async with websockets.connect('ws://localhost:8765') as ws:
            # Subscribe to critical events
            await ws.send(json.dumps({
                'action': 'subscribe',
                'event_types': [
                    'EXECUTION_STARTED',
                    'EXECUTION_FAILED',
                    'CONSTRAINT_VIOLATION'
                ]
            }))

            async for message in ws:
                data = json.loads(message)

                if data['type'] == 'event':
                    await self.handle_event(data['event'])

    async def handle_event(self, event):
        event_type = event['type']

        if event_type == 'execution_started':
            self.executions[event['execution_id']] = {
                'started': datetime.now(),
                'stream_id': event['stream_id']
            }

        elif event_type == 'execution_failed':
            # Alert on failures
            await self.alert_callback(
                level='error',
                message=f"Agent failed: {event['data'].get('error')}",
                execution_id=event['execution_id']
            )

        elif event_type == 'constraint_violation':
            # Alert on violations
            await self.alert_callback(
                level='warning',
                message=f"Constraint violated: {event['data']}",
                execution_id=event.get('execution_id')
            )

# Usage with Slack/PagerDuty
async def send_alert(level, message, execution_id):
    # Send to Slack, PagerDuty, email, etc.
    print(f"[{level.upper()}] {message} (exec: {execution_id})")

monitor = AgentMonitor(alert_callback=send_alert)
asyncio.run(monitor.monitor())
```

### 5. Multi-Agent Orchestration

Coordinate multiple agents via event streaming:

```python
# orchestrator.py
import asyncio
import json
import websockets

class AgentOrchestrator:
    def __init__(self):
        self.agent_status = {}

    async def orchestrate(self):
        async with websockets.connect('ws://localhost:8765') as ws:
            await ws.send(json.dumps({'action': 'subscribe'}))

            async for message in ws:
                data = json.loads(message)

                if data['type'] == 'event':
                    event = data['event']
                    stream_id = event['stream_id']

                    # Track agent progress
                    if event['type'] == 'execution_completed':
                        self.agent_status[stream_id] = 'completed'

                        # Trigger dependent agents
                        if stream_id == 'data-collector':
                            await self.start_agent('data-analyzer', event['data'])
                        elif stream_id == 'data-analyzer':
                            await self.start_agent('report-generator', event['data'])

    async def start_agent(self, stream_id: str, input_data: dict):
        # Trigger next agent in pipeline
        print(f"Starting {stream_id} with input: {input_data}")
        # ... execute agent ...
```

## Production Deployment

### 1. Reverse Proxy with Authentication

**Nginx Config:**

```nginx
map $http_upgrade $connection_upgrade {
    default upgrade;
    '' close;
}

upstream websocket {
    server localhost:8765;
}

server {
    listen 443 ssl;
    server_name agents.example.com;

    ssl_certificate /etc/ssl/certs/cert.pem;
    ssl_certificate_key /etc/ssl/private/key.pem;

    location /stream {
        # Authentication
        auth_request /auth;

        # WebSocket proxying
        proxy_pass http://websocket;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_set_header X-Real-IP $remote_addr;

        # Timeouts
        proxy_read_timeout 86400;
        proxy_send_timeout 86400;
    }

    location = /auth {
        internal;
        proxy_pass http://auth-service/verify;
        proxy_pass_request_body off;
        proxy_set_header Content-Length "";
        proxy_set_header X-Original-URI $request_uri;
    }
}
```

### 2. Systemd Service

**`/etc/systemd/system/hive-websocket.service`:**

```ini
[Unit]
Description=Hive WebSocket Streaming Server
After=network.target

[Service]
Type=simple
User=hive
WorkingDirectory=/opt/hive
Environment="PYTHONPATH=/opt/hive/core"
ExecStart=/opt/hive/venv/bin/python -m framework stream --host 127.0.0.1 --port 8765
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable hive-websocket
sudo systemctl start hive-websocket
sudo systemctl status hive-websocket
```

### 3. Docker Deployment

**`docker-compose.yml`:**

```yaml
version: "3.8"

services:
  websocket-server:
    build: .
    command: python -m framework stream --host 0.0.0.0 --port 8765
    ports:
      - "8765:8765"
    environment:
      - PYTHONPATH=/app/core
    restart: unless-stopped
    healthcheck:
      test:
        [
          "CMD",
          "python",
          "-c",
          "import websockets; import asyncio; asyncio.run(websockets.connect('ws://localhost:8765'))",
        ]
      interval: 30s
      timeout: 10s
      retries: 3

  nginx:
    image: nginx:alpine
    ports:
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf:ro
      - ./ssl:/etc/ssl:ro
    depends_on:
      - websocket-server
```

### 4. Authentication & Authorization

Add JWT authentication to the WebSocket server:

```python
# core/framework/runtime/websocket_auth.py
import jwt
from datetime import datetime, timedelta

class WebSocketAuth:
    def __init__(self, secret_key: str):
        self.secret_key = secret_key

    def generate_token(self, user_id: str, streams: list[str]) -> str:
        """Generate JWT token with stream access."""
        payload = {
            'user_id': user_id,
            'streams': streams,
            'exp': datetime.utcnow() + timedelta(hours=24)
        }
        return jwt.encode(payload, self.secret_key, algorithm='HS256')

    def verify_token(self, token: str) -> dict:
        """Verify and decode JWT token."""
        try:
            return jwt.decode(token, self.secret_key, algorithms=['HS256'])
        except jwt.ExpiredSignatureError:
            raise ValueError("Token expired")
        except jwt.InvalidTokenError:
            raise ValueError("Invalid token")

    def can_access_stream(self, token: str, stream_id: str) -> bool:
        """Check if token allows access to stream."""
        payload = self.verify_token(token)
        allowed_streams = payload.get('streams', [])
        return '*' in allowed_streams or stream_id in allowed_streams
```

**Modified WebSocket handler:**

```python
async def _handle_client(self, websocket: WebSocketServerProtocol) -> None:
    """Handle client with authentication."""
    try:
        # First message must be authentication
        auth_msg = await asyncio.wait_for(websocket.recv(), timeout=5.0)
        data = json.loads(auth_msg)

        if data.get('action') != 'auth':
            await websocket.close(1008, "Auth required")
            return

        token = data.get('token')
        payload = self.auth.verify_token(token)

        # Store user context
        self._user_contexts[websocket] = {
            'user_id': payload['user_id'],
            'allowed_streams': payload['streams']
        }

        # Continue with normal flow...
        await websocket.send(json.dumps({'type': 'authenticated'}))

    except (asyncio.TimeoutError, ValueError) as e:
        await websocket.close(1008, f"Auth failed: {e}")
        return
```

## Event Types Reference

| Event Type            | When Emitted          | Data Fields                               |
| --------------------- | --------------------- | ----------------------------------------- |
| `EXECUTION_STARTED`   | Agent starts          | `input_data`, `stream_id`, `execution_id` |
| `EXECUTION_COMPLETED` | Agent succeeds        | `output`, `execution_id`                  |
| `EXECUTION_FAILED`    | Agent fails           | `error`, `execution_id`                   |
| `GOAL_PROGRESS`       | Goal criteria updated | `progress`, `criteria_status`             |
| `GOAL_ACHIEVED`       | Goal completed        | `final_status`                            |
| `STATE_CHANGED`       | Shared state modified | `key`, `old_value`, `new_value`           |
| `EXECUTION_PAUSED`    | HITL pause            | `node_id`, `reason`                       |
| `EXECUTION_RESUMED`   | HITL resume           | `node_id`, `decision`                     |

## Client Libraries

**Python:**

```bash
pip install websockets
```

**JavaScript/TypeScript:**

```bash
npm install ws  # Node.js
# Browser: native WebSocket API
```

**Go:**

```bash
go get github.com/gorilla/websocket
```

## Troubleshooting

**Connection refused:**

- Check server is running: `ps aux | grep "framework stream"`
- Verify port: `lsof -i :8765`
- Check firewall: `sudo ufw status`

**Events not streaming:**

- Ensure EventBus is global singleton (not multiple instances)
- Verify `stream_id` matches subscription filter
- Check server logs for errors

**High latency:**

- Run server on same machine/network as agents
- Use binary WebSocket frames for large payloads
- Implement client-side buffering

## See Also

- [WebSocket Server Implementation](../core/framework/runtime/websocket_server.py)
- [EventBus API](../core/framework/runtime/event_bus.py)
- [Integration Tests](../tools/tests/integration/test_websocket_integration.py)
