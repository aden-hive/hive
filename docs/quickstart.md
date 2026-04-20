# Hive Quickstart Guide

This guide helps you install Hive and build your first worker agent.

---

## 1. Clone the Repository

git clone https://github.com/aden-hive/hive.git
cd hive

---

## 2. Run the Setup Script

Run the automated setup script:

./quickstart.sh

This script installs:

- Python dependencies
- Hive framework environment
- Aden tools
- Credential storage
- LLM provider configuration

During setup you will:

1. Choose your LLM provider
2. Add your API key
3. Enable browser automation (optional)

---

## 3. Launch Hive

After setup Hive launches automatically:

http://localhost:8787

You should see the Hive dashboard.

---

## 4. Create Your First Agent

In the dashboard input box type:

Research the latest AI agent frameworks and summarize them.

Hive will automatically generate an agent graph.

---

## 5. Run the Agent

Click **Run** or ask the Queen agent to run the task.

The worker agents will:

1. Search the web
2. Collect information
3. Generate a summary

---

## 6. Monitor Execution

Hive provides real-time monitoring including:

- node execution
- agent decisions
- tool usage
- logs

---

## Next Steps

- Create custom worker agents
- Connect APIs as tools
- Build autonomous workflows
