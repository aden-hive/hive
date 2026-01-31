# Agent Explainability Web UI

This is a minimal Flask web dashboard for viewing agent run logs and explainability details.

## Features
- Lists available agent run logs (JSON files in `../agent_logs/runs/`)
- View detailed reasoning, decisions, and outcomes for each run
- Download raw log files

## Usage

1. **Install Flask** (if not already):
   ```bash
   pip install flask
   ```

2. **Run the web server:**
   ```bash
   cd webui
   python app.py
   ```

3. **Open your browser:**
   Visit [http://localhost:5000](http://localhost:5000)

## Customization
- By default, the app looks for run logs in `../agent_logs/runs/` relative to `webui/`.
- You can change the log directory in `app.py` if needed.

---

This UI is a starting point. You can extend it with search, filtering, authentication, or richer visualizations as needed.
