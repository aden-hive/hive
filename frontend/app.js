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

// Task modal state
let pollingInterval = null;

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    renderAgents();
    renderActivity();
    updateStats();
    updateTimestamp();

    // Event listeners
    statusFilter.addEventListener('change', handleFilterChange);
    refreshBtn.addEventListener('click', handleRefresh);

    // Task modal event listeners
    document.getElementById('modal-close').addEventListener('click', closeModal);
    document.getElementById('modal-cancel').addEventListener('click', closeModal);
    document.getElementById('modal-submit').addEventListener('click', submitBlogTask);
    document.getElementById('task-modal').addEventListener('click', (e) => {
        if (e.target === e.currentTarget) closeModal();
    });
    document.getElementById('blog-topic').addEventListener('keydown', (e) => {
        if (e.key === 'Enter') submitBlogTask();
    });

    // Post reader modal event listeners
    document.getElementById('post-modal-close').addEventListener('click', closePostModal);
    document.getElementById('post-modal').addEventListener('click', (e) => {
        if (e.target === e.currentTarget) closePostModal();
    });

    // Blog posts section
    document.getElementById('refresh-posts-btn').addEventListener('click', loadPosts);
    loadPosts();

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

    const sendTaskBtn = agent.name === 'Blog Writer'
        ? `<button class="send-task-btn" onclick="openBlogTaskModal()">Send Task</button>`
        : '';

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
            ${sendTaskBtn}
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

// Blog Writer Task Modal
function openBlogTaskModal() {
    const modal = document.getElementById('task-modal');
    const input = document.getElementById('blog-topic');
    const status = document.getElementById('task-status');
    const submitBtn = document.getElementById('modal-submit');

    input.value = '';
    status.style.display = 'none';
    status.className = 'task-status';
    status.textContent = '';
    submitBtn.disabled = false;
    submitBtn.textContent = 'Send Task';
    modal.style.display = 'flex';
    setTimeout(() => input.focus(), 50);
}

function closeModal() {
    document.getElementById('task-modal').style.display = 'none';
    if (pollingInterval) {
        clearInterval(pollingInterval);
        pollingInterval = null;
    }
}

async function submitBlogTask() {
    const topic = document.getElementById('blog-topic').value.trim();
    if (!topic) return;

    const submitBtn = document.getElementById('modal-submit');
    const status = document.getElementById('task-status');

    submitBtn.disabled = true;
    submitBtn.textContent = 'Sending...';
    status.style.display = 'block';
    status.className = 'task-status running';
    status.textContent = 'Sending task to Blog Writer...';

    try {
        const res = await fetch('http://localhost:8080/api/tasks/blog', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ topic }),
        });

        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.error || `Server error ${res.status}`);
        }

        const data = await res.json();
        const taskId = data.task_id;

        status.textContent = `Task started (ID: ${taskId}). Writing blog post...`;
        addActivityItem('info', `Blog Writer received task: "${topic}"`, 'just now');

        pollingInterval = setInterval(async () => {
            try {
                const pollRes = await fetch(`http://localhost:8080/api/tasks/${taskId}`);
                const task = await pollRes.json();

                if (task.status === 'completed') {
                    clearInterval(pollingInterval);
                    pollingInterval = null;
                    status.className = 'task-status completed';
                    const filePath = task.output?.output?.file_path || task.output?.file_path;
                    status.textContent = filePath
                        ? `Done! Saved to: ${filePath}`
                        : 'Blog post written successfully!';
                    submitBtn.textContent = 'Close';
                    submitBtn.disabled = false;
                    submitBtn.onclick = closeModal;
                    addActivityItem('success', `Blog Writer completed: "${topic}"`, 'just now');
                    loadPosts();
                } else if (task.status === 'failed') {
                    clearInterval(pollingInterval);
                    pollingInterval = null;
                    status.className = 'task-status failed';
                    status.textContent = `Failed: ${task.error || 'Unknown error'}`;
                    submitBtn.textContent = 'Close';
                    submitBtn.disabled = false;
                    submitBtn.onclick = closeModal;
                    addActivityItem('error', `Blog Writer failed: "${topic}"`, 'just now');
                }
            } catch (e) {
                // polling error — keep trying
            }
        }, 3000);

    } catch (err) {
        status.className = 'task-status failed';
        status.textContent = `Error: ${err.message}. Is the server running? (python frontend/server.py)`;
        submitBtn.disabled = false;
        submitBtn.textContent = 'Send Task';
    }
}

function addActivityItem(type, message, time) {
    const icons = { success: '✓', warning: '⚠', error: '✕', info: 'ℹ' };
    const item = document.createElement('div');
    item.className = 'activity-item';
    item.innerHTML = `
        <div class="activity-icon ${type}">${icons[type]}</div>
        <div class="activity-content">
            <div class="activity-message">${message}</div>
            <div class="activity-time">${time}</div>
        </div>
    `;
    activityLog.insertBefore(item, activityLog.firstChild);
}

// Blog Posts Section
async function loadPosts() {
    const list = document.getElementById('posts-list');
    try {
        const res = await fetch('http://localhost:8080/api/posts', { cache: 'no-store' });
        const data = await res.json();
        if (data.posts.length === 0) {
            list.innerHTML = '<p class="posts-empty">No blog posts yet. Send a task to the Blog Writer to get started.</p>';
            return;
        }
        list.innerHTML = data.posts.map(filename => {
            const label = filename
                .replace(/^blog_\d{4}-\d{2}-\d{2}_/, '')
                .replace(/\.md$/, '')
                .replace(/-/g, ' ');
            const date = filename.match(/blog_(\d{4}-\d{2}-\d{2})_/)?.[1] || '';
            return `
                <div class="post-item">
                    <div class="post-info">
                        <div class="post-title">${label}</div>
                        <div class="post-date">${date}</div>
                    </div>
                    <button class="view-post-btn" onclick="openPost('${filename}')">View Post</button>
                </div>
            `;
        }).join('');
    } catch (e) {
        list.innerHTML = '<p class="posts-empty">Could not load posts. Is the server running?</p>';
    }
}

async function openPost(filename) {
    const modal = document.getElementById('post-modal');
    const content = document.getElementById('post-modal-content');
    const title = document.getElementById('post-modal-title');

    content.innerHTML = '<div class="post-loading">Loading...</div>';
    title.textContent = 'Blog Post';
    modal.style.display = 'flex';

    try {
        const res = await fetch(`http://localhost:8080/api/posts/${filename}`);
        const data = await res.json();
        const html = marked.parse(data.content);
        content.innerHTML = `<div class="post-rendered">${html}</div>`;
        // Extract title from first h1
        const h1 = content.querySelector('h1');
        if (h1) title.textContent = h1.textContent;
    } catch (e) {
        content.innerHTML = '<p style="color:#ef4444">Failed to load post.</p>';
    }
}

function closePostModal() {
    document.getElementById('post-modal').style.display = 'none';
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
