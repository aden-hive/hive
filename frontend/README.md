# Hive Dashboard (Frontend)

A simple HTML/CSS/JS dashboard for monitoring Hive agents.

## Features

- Agent status cards with real-time metrics
- Status filtering (online/degraded/offline)
- Sparkline charts for request history
- Activity log
- Auto-refresh every 30 seconds
- Responsive design

## Running Locally

No build step required. Just open `index.html` in your browser:

```bash
# Option 1: Open directly
open frontend/index.html

# Option 2: Use Python's built-in server
cd frontend
python -m http.server 8080
# Then visit http://localhost:8080

# Option 3: Use Node's http-server
npx http-server frontend -p 8080
```

## Current State

This is an MVP using **mock data**. The following features are ready to be connected to real APIs:

### Ready for Integration

1. **Agent List API** - Replace `mockAgents` with fetch from `/api/agents`
2. **WebSocket Updates** - Connect to real-time agent status stream
3. **Activity Feed** - Fetch from `/api/activity` endpoint

### Placeholder Functions

See `app.js` for:
- `fetchAgents()` - Stub for REST API integration
- `connectWebSocket()` - Stub for real-time updates

## File Structure

```
frontend/
├── index.html    # Main HTML structure
├── styles.css    # All styling (dark theme)
├── app.js        # JavaScript logic + mock data
└── README.md     # This file
```

## Customization

### Adding New Agents

Edit the `mockAgents` array in `app.js`:

```javascript
{
    id: 'agent-007',
    name: 'My New Agent',
    status: 'online', // online | degraded | offline | unknown
    metrics: {
        requestsPerMinute: 50,
        successRate: 95.0,
        avgLatency: 200,
        costToday: 10.00,
        requestHistory: generateSparklineData()
    }
}
```

### Changing Colors

Edit CSS variables in `styles.css`:
- Online: `#22c55e` (green)
- Degraded: `#eab308` (yellow)
- Offline: `#ef4444` (red)
- Primary: `#3b82f6` (blue)

## Next Steps

1. [ ] Connect to real agent API endpoint
2. [ ] Add WebSocket for live updates
3. [ ] Add agent creation form
4. [ ] Add cost breakdown charts
5. [ ] Add agent graph visualization
