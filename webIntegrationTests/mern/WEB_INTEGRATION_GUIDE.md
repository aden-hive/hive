# 🌐 Web Dashboard Integration Guide

## Overview

You now have a **web-based interface for the Customer Service Agent** that mirrors the TUI functionality. This guide walks you through the setup, features, and deployment.

---

## Project Structure

```
hive-web-dashboard/
├── backend/                    # Node.js/Express backend
│   ├── src/
│   │   ├── server.js          # Main Express server
│   │   ├── services/
│   │   │   ├── agentWebService.js    # ✨ NEW: Handles agent execution
│   │   │   └── integrationService.js # Third-party integrations
│   │   ├── routes/
│   │   │   └── hiveRoutes.js         # ✨ UPDATED: Agent API endpoints
│   │   └── controllers/
│   │       └── hiveController.js     # Business logic
│   └── package.json
│
├── frontend/                   # React/Vite frontend
│   ├── src/
│   │   ├── components/
│   │   │   ├── AgentRunner.jsx       # ✨ UPDATED: Main agent interface
│   │   │   ├── AgentRunner.css       # ✨ UPDATED: TUI-like styling
│   │   │   ├── Dashboard.jsx         # Main layout
│   │   │   ├── Status.jsx            # System status
│   │   │   └── ... other components
│   │   └── App.jsx
│   └── package.json
│
└── hive/                       # Main agent framework
    ├── examples/templates/
    │   └── customer_service_agent/
    │       ├── agent.py               # Agent definition
    │       ├── config.py              # Configuration
    │       ├── nodes/                 # 6 specialized nodes
    │       └── mcp_servers.json       # Tool configuration
```

---

## ✨ New Features

### 1. Enhanced Backend Service (`agentWebService.js`)

**Capabilities:**

- Execute Customer Service Agent from web requests
- Manage agent lifecycle (start, pause, resume, stop)
- Maintain session history
- Real-time state tracking
- Process management and timeouts

**Key Methods:**

- `startAgent(input)` - Run agent with user input
- `pauseExecution()` - Pause running agent
- `resumeExecution()` - Resume paused agent
- `stopExecution()` - Terminate execution
- `getState()` - Current execution state
- `getHistory(limit)` - Session history
- `listAgents()` - Available agents
- `getAgentInfo(name)` - Agent details

### 2. Updated API Routes (`hiveRoutes.js`)

**Endpoints:**

```
POST   /api/hive/run              # Execute agent
GET    /api/hive/state            # Get execution state
GET    /api/hive/history          # Get session history
POST   /api/hive/pause            # Pause execution
POST   /api/hive/resume           # Resume execution
POST   /api/hive/stop             # Stop execution
POST   /api/hive/clear-history    # Clear all history
GET    /api/hive/agents           # List agents
GET    /api/hive/agents/:name     # Get agent info
```

### 3. Redesigned Agent Runner (`AgentRunner.jsx`)

**Features:**

- TUI-like chat interface
- Live execution state indicator
- Session history sidebar
- Input validation
- Pause/Resume/Stop controls
- Real-time agent state polling
- Responsive design
- Example queries
- Session management

**UI Components:**

- Header with agent status (idle, running, paused)
- History panel showing previous sessions
- Input textarea for user queries
- Control buttons (Send, Pause, Resume, Stop)
- Result display with formatted output
- Empty state with usage examples

---

## 🚀 Setup Instructions

### Backend Setup

```bash
cd hive-web-dashboard/backend

# Install dependencies
npm install

# Start server
npm start
# Server runs on http://localhost:5000
```

**Requirements:**

- Node.js 14+
- Python 3.8+ (for agent execution)
- Express.js
- CORS enabled

### Frontend Setup

```bash
cd hive-web-dashboard/frontend

# Install dependencies
npm install

# Start development server
npm run dev
# Frontend runs on http://localhost:5173
```

**Requirements:**

- Node.js 14+
- React 18+
- Vite
- Axios for API calls

### Environment Setup

**Backend (.env file needed):**

```env
PORT=5000
NODE_ENV=development
ANTHROPIC_API_KEY=sk-ant-...
PYTHON_PATH=/usr/bin/python3
HIVE_DIR=../hive
```

**Frontend (.env not needed, uses http://localhost:5000)**

---

## 🎯 How It Works

### Execution Flow

```
┌─────────────────────────────────────────────────────────┐
│  User enters query in web interface                      │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│  Frontend: Send POST /api/hive/run with input           │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│  Backend: agentWebService.startAgent(input)             │
│  - Spawn Python process                                 │
│  - Run: python -m framework run customer_service_agent  │
│  - Capture stdout/stderr                                │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│  Hive Framework: Execute agent                          │
│  - Load customer_service_agent                          │
│  - Initialize 6 nodes                                   │
│  - Process input through graph                          │
│  - Generate response                                    │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│  Backend: Capture response output                       │
│  - Wait for process completion                          │
│  - Return status + output + sessionId                   │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│  Frontend: Display response                             │
│  - Show agent output                                    │
│  - Add to history                                       │
│  - Update status indicator                              │
└─────────────────────────────────────────────────────────┘
```

### State Management

**Frontend tracks:**

- `executionState` - idle, running, paused
- `input` - User's current input
- `result` - Last execution result
- `loading` - Is execution in progress?
- `history` - Previous sessions
- `error` - Error messages

**Backend tracks:**

- `agentProcess` - Running subprocess
- `executionState` - Current state
- `sessionHistory` - All sessions
- `lastMessage` - Most recent result

---

## 📱 Web UI Features

### Chat-Style Interface

```
┌─────────────────────────────────────────────┐
│ 🤖 Customer Service Agent       [History]   │
│ Status: ● Running                           │
├─────────────────────────────────────────────┤
│                                             │
│  Enter your customer service request...    │
│                                             │
│  [___________________________________]      │
│  [✉️ Send] [⏸ Pause] [⏹ Stop]            │
│                                             │
├─────────────────────────────────────────────┤
│ Agent Response                              │
│                                             │
│ Input: I forgot my password                 │
│                                             │
│ Output:                                     │
│ You have been routed to the password...    │
│                                             │
│ [✕ Close] [🔄 Re-ask]                     │
└─────────────────────────────────────────────┘
```

### Status Indicator

- 🟢 Idle - Ready to accept input
- 🟠 Running - Agent is processing
- 🟡 Paused - Execution paused
- 🔴 Error - Something went wrong

### Session History

- Lists up to 20 previous sessions
- Click to view full response
- Shows timestamp for each query
- Quick access to frequently asked questions

### Control Buttons

- **Send** - Execute agent with input
- **Pause** - Pause running execution
- **Resume** - Continue paused execution
- **Stop** - Terminate current execution
- **History** - Toggle history sidebar
- **Clear** - Remove all history

---

## 🔧 Configuration

### Agent Selection

To use a different agent, update `agentWebService.js`:

```javascript
// Change from:
const args = ["-m", "framework", "run", "customer_service_agent", ...]

// To:
const args = ["-m", "framework", "run", "different_agent_name", ...]
```

### Timeout Configuration

```javascript
// Default: 10 minutes
setTimeout(() => {
  if (this.executionState === "running") {
    this.agentProcess.kill();
    reject(new Error("Agent execution timeout"));
  }
}, 600000); // milliseconds
```

### Environment Variables

```javascript
const env = {
  ...process.env,
  PYTHONUNBUFFERED: "1", // Unbuffered Python output
  // Add more env vars here:
  // ANTHROPIC_API_KEY: process.env.ANTHROPIC_API_KEY,
  // MCP_SERVERS: "./mcp_servers.json",
};
```

---

## 🧪 Testing

### Manual Testing

1. **Start Backend:**

   ```bash
   cd backend
   npm start
   ```

2. **Start Frontend:**

   ```bash
   cd frontend
   npm run dev
   ```

3. **Test in Browser:**
   - Navigate to http://localhost:5173
   - Click on "Agent Runner" tab
   - Enter a query: "I forgot my password"
   - Click "Send"
   - Observe agent processing

### API Testing with cURL

```bash
# Execute agent
curl -X POST http://localhost:5000/api/hive/run \
  -H "Content-Type: application/json" \
  -d '{"input":"I forgot my password"}'

# Get state
curl http://localhost:5000/api/hive/state

# Get history
curl http://localhost:5000/api/hive/history?limit=10

# Pause
curl -X POST http://localhost:5000/api/hive/pause

# Clear history
curl -X POST http://localhost:5000/api/hive/clear-history
```

---

## 📊 Performance Considerations

### Backend

- Uses child processes (`spawn`) for agent execution
- Captures output incrementally
- Implements timeout protection (10 minutes)
- Maintains in-memory session history

### Frontend

- Polls agent state every 2 seconds
- Auto-scrolls output to latest message
- Disables input during execution
- Responsive CSS with mobile support

### Optimization Tips

1. Increase timeout for complex agents
2. Limit history size (currently 20 sessions)
3. Implement pagination for large outputs
4. Add output streaming for real-time updates

---

## 🚨 Error Handling

### Common Errors

**"Agent is already running"**

- User clicked Send while agent was executing
- Solution: Disable button during execution (done)

**"Agent execution timeout"**

- Agent took longer than 10 minutes
- Check Python process logs
- Increase timeout value in code

**"Failed to connect to backend"**

- Backend server not running
- Port 5000 in use
- Network connectivity issue

**"ANTHROPIC_API_KEY not set"**

- API key not in environment
- Add to .env file or set environment variable

### Error Display

- Shows error messages in yellow warning box
- Logs details to browser console
- Logs details to backend console
- Execution state resets to idle

---

## 📈 Future Enhancements

### Planned Features

1. **WebSocket Support**
   - Real-time output streaming
   - Replace polling with push updates
   - Faster response display

2. **Output Formatting**
   - Syntax highlighting for JSON
   - Markdown support for responses
   - Copy-to-clipboard button

3. **Advanced History**
   - Search/filter previous sessions
   - Export session as PDF/JSON
   - Mark favorite sessions

4. **Multiple Agents**
   - Dropdown to select agent
   - Agent comparison view
   - Batch execution

5. **Authentication**
   - User login/profiles
   - Per-user session history
   - Rate limiting

6. **Analytics**
   - Usage statistics
   - Performance metrics
   - Error tracking

---

## 📚 Related Documentation

- **Backend Service**: See `agentWebService.js`
- **API Routes**: See `hiveRoutes.js`
- **Frontend Component**: See `AgentRunner.jsx`
- **Agent Definition**: See `customer_service_agent/agent.py`
- **Framework Docs**: See `../../hive/` directory

---

## 🎓 Example Use Cases

### 1. Customer Support Portal

```
User Query: "I want to reset my password"
↓
Agent processes through:
  intake → classify → task_handler → followup
↓
Response: "I've sent you a password reset link"
```

### 2. FAQ System

```
User Query: "What are your business hours?"
↓
Agent processes through:
  intake → classify → faq → followup
↓
Response: "We're open 9 AM - 5 PM EST"
```

### 3. Order Management

```
User Query: "Where is my order?"
↓
Agent processes through:
  intake → classify → task_handler → followup
↓
Response: "Your order #12345 is being delivered today"
```

---

## ✅ Deployment Checklist

- [ ] Backend `.env` file configured
- [ ] ANTHROPIC_API_KEY set
- [ ] Frontend pointing to correct backend URL
- [ ] Both servers running
- [ ] Test with sample query
- [ ] Check browser console for errors
- [ ] Check backend console for logs
- [ ] History persistence (optional)
- [ ] Error boundaries in React (optional)
- [ ] Rate limiting (optional)

---

**Status**: ✅ Ready for development and testing!

Start the servers and try it out: http://localhost:5173
