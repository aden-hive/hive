// Hive Dashboard - Simple Frontend
// This uses mock data for now - can be connected to real APIs later

// Mock data for agents
const mockAgents = [
    {
        id: 'agent-001',
        name: 'Marketing Agent',
        status: 'online',
        metrics: {
            requestsPerMinute: 45,
            successRate: 98.5,
            avgLatency: 230,
            costToday: 12.50,
            requestHistory: generateSparklineData()
        }
    },
    {
        id: 'agent-002',
        name: 'Knowledge Agent',
        status: 'online',
        metrics: {
            requestsPerMinute: 120,
            successRate: 99.2,
            avgLatency: 180,
            costToday: 28.75,
            requestHistory: generateSparklineData()
        }
    },
    {
        id: 'agent-003',
        name: 'Blog Writer',
        status: 'degraded',
        metrics: {
            requestsPerMinute: 8,
            successRate: 85.0,
            avgLatency: 890,
            costToday: 5.20,
            requestHistory: generateSparklineData()
        }
    },
    {
        id: 'agent-004',
        name: 'SDR Agent',
        status: 'online',
        metrics: {
            requestsPerMinute: 32,
            successRate: 96.8,
            avgLatency: 310,
            costToday: 18.90,
            requestHistory: generateSparklineData()
        }
    },
    {
        id: 'agent-005',
        name: 'Data Analyst',
        status: 'offline',
        metrics: {
            requestsPerMinute: 0,
            successRate: 0,
            avgLatency: 0,
            costToday: 2.10,
            requestHistory: generateSparklineData(true)
        }
    },
    {
        id: 'agent-006',
        name: 'Support Bot',
        status: 'online',
        metrics: {
            requestsPerMinute: 78,
            successRate: 97.5,
            avgLatency: 145,
            costToday: 22.30,
            requestHistory: generateSparklineData()
        }
    }
];

// Mock activity data
const mockActivity = [
    { type: 'success', message: 'Marketing Agent completed campaign analysis', time: '2 min ago' },
    { type: 'info', message: 'Knowledge Agent indexed 150 new documents', time: '5 min ago' },
    { type: 'warning', message: 'Blog Writer experiencing high latency', time: '8 min ago' },
    { type: 'success', message: 'SDR Agent sent 45 outreach emails', time: '12 min ago' },
    { type: 'error', message: 'Data Analyst went offline - connection timeout', time: '15 min ago' },
    { type: 'info', message: 'Support Bot resolved 23 tickets', time: '20 min ago' },
    { type: 'success', message: 'System backup completed successfully', time: '1 hour ago' }
];

// Generate random sparkline data
function generateSparklineData(offline = false) {
    const data = [];
    for (let i = 0; i < 20; i++) {
        if (offline && i > 15) {
            data.push(0);
        } else {
            data.push(Math.floor(Math.random() * 80) + 20);
        }
    }
    return data;
}

// State
let currentFilter = 'all';
let agents = [...mockAgents];

// DOM Elements
const agentsGrid = document.getElementById('agents-grid');
const activityLog = document.getElementById('activity-log');
const statusFilter = document.getElementById('status-filter');
const refreshBtn = document.getElementById('refresh-btn');
const lastUpdated = document.getElementById('last-updated');

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    renderAgents();
    renderActivity();
    updateStats();
    updateTimestamp();

    // Event listeners
    statusFilter.addEventListener('change', handleFilterChange);
    refreshBtn.addEventListener('click', handleRefresh);

    // Auto-refresh every 30 seconds
    setInterval(() => {
        simulateDataUpdate();
        renderAgents();
        updateStats();
        updateTimestamp();
    }, 30000);
});

// Render agent cards
function renderAgents() {
    const filteredAgents = currentFilter === 'all'
        ? agents
        : agents.filter(a => a.status === currentFilter);

    if (filteredAgents.length === 0) {
        agentsGrid.innerHTML = `
            <div class="empty-state">
                <h3>No agents found</h3>
                <p>No agents match the current filter.</p>
            </div>
        `;
        return;
    }

    agentsGrid.innerHTML = filteredAgents.map(agent => createAgentCard(agent)).join('');
}

// Create agent card HTML
function createAgentCard(agent) {
    const maxValue = Math.max(...agent.metrics.requestHistory);
    const sparklineBars = agent.metrics.requestHistory
        .map(value => {
            const height = maxValue > 0 ? (value / maxValue) * 100 : 0;
            return `<div class="sparkline-bar" style="height: ${height}%" title="${value} req"></div>`;
        })
        .join('');

    return `
        <div class="agent-card">
            <div class="agent-header">
                <div>
                    <div class="agent-name">${agent.name}</div>
                    <div class="agent-id">${agent.id}</div>
                </div>
                <span class="status-badge ${agent.status}">${agent.status}</span>
            </div>
            <div class="agent-metrics">
                <div class="metric">
                    <div class="metric-value">${agent.metrics.requestsPerMinute}</div>
                    <div class="metric-label">Req/min</div>
                </div>
                <div class="metric">
                    <div class="metric-value">${agent.metrics.successRate}%</div>
                    <div class="metric-label">Success</div>
                </div>
                <div class="metric">
                    <div class="metric-value">${agent.metrics.avgLatency}ms</div>
                    <div class="metric-label">Latency</div>
                </div>
                <div class="metric">
                    <div class="metric-value">$${agent.metrics.costToday.toFixed(2)}</div>
                    <div class="metric-label">Cost Today</div>
                </div>
            </div>
            <div class="sparkline">
                <div class="sparkline-label">Requests (last 20 min)</div>
                <div class="sparkline-chart">
                    ${sparklineBars}
                </div>
            </div>
        </div>
    `;
}

// Render activity log
function renderActivity() {
    const icons = {
        success: '✓',
        warning: '⚠',
        error: '✕',
        info: 'ℹ'
    };

    activityLog.innerHTML = mockActivity.map(item => `
        <div class="activity-item">
            <div class="activity-icon ${item.type}">${icons[item.type]}</div>
            <div class="activity-content">
                <div class="activity-message">${item.message}</div>
                <div class="activity-time">${item.time}</div>
            </div>
        </div>
    `).join('');
}

// Update stats bar
function updateStats() {
    const total = agents.length;
    const online = agents.filter(a => a.status === 'online').length;
    const degraded = agents.filter(a => a.status === 'degraded').length;
    const offline = agents.filter(a => a.status === 'offline').length;
    const totalCost = agents.reduce((sum, a) => sum + a.metrics.costToday, 0);

    document.getElementById('total-agents').textContent = total;
    document.getElementById('online-count').textContent = online;
    document.getElementById('degraded-count').textContent = degraded;
    document.getElementById('offline-count').textContent = offline;
    document.getElementById('total-cost').textContent = `$${totalCost.toFixed(2)}`;
}

// Update timestamp
function updateTimestamp() {
    const now = new Date();
    lastUpdated.textContent = `Last updated: ${now.toLocaleTimeString()}`;
}

// Handle filter change
function handleFilterChange(e) {
    currentFilter = e.target.value;
    renderAgents();
}

// Handle refresh
function handleRefresh() {
    refreshBtn.textContent = 'Refreshing...';
    refreshBtn.disabled = true;

    setTimeout(() => {
        simulateDataUpdate();
        renderAgents();
        updateStats();
        updateTimestamp();
        refreshBtn.textContent = 'Refresh';
        refreshBtn.disabled = false;
    }, 500);
}

// Simulate data updates (for demo purposes)
function simulateDataUpdate() {
    agents = agents.map(agent => {
        // Randomly update metrics slightly
        const newMetrics = { ...agent.metrics };

        if (agent.status !== 'offline') {
            newMetrics.requestsPerMinute = Math.max(0, agent.metrics.requestsPerMinute + Math.floor(Math.random() * 20) - 10);
            newMetrics.successRate = Math.min(100, Math.max(80, agent.metrics.successRate + (Math.random() * 2 - 1)));
            newMetrics.avgLatency = Math.max(50, agent.metrics.avgLatency + Math.floor(Math.random() * 50) - 25);
            newMetrics.costToday = agent.metrics.costToday + (Math.random() * 0.5);

            // Shift sparkline data
            newMetrics.requestHistory = [
                ...agent.metrics.requestHistory.slice(1),
                Math.floor(Math.random() * 80) + 20
            ];
        }

        return { ...agent, metrics: newMetrics };
    });
}

// Future: Connect to real API
async function fetchAgents() {
    try {
        // Replace with real API endpoint when available
        // const response = await fetch('/api/agents');
        // const data = await response.json();
        // agents = data;
        // renderAgents();
        // updateStats();
        console.log('API fetch would happen here');
    } catch (error) {
        console.error('Failed to fetch agents:', error);
    }
}

// Future: WebSocket connection for real-time updates
function connectWebSocket() {
    // Replace with real WebSocket endpoint when available
    // const ws = new WebSocket('ws://localhost:4001/ws');
    // ws.onmessage = (event) => {
    //     const data = JSON.parse(event.data);
    //     updateAgentData(data);
    // };
    console.log('WebSocket connection would happen here');
}
