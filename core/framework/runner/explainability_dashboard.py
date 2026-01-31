from flask import Flask, render_template_string, request, abort
import os
import json

app = Flask(__name__)

# Directory where run logs are stored (update if needed)
LOG_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../core/framework/runner/logs'))

@app.route('/')
def index():
    # List all log files
    if not os.path.exists(LOG_DIR):
        return f"Log directory not found: {LOG_DIR}", 404
    files = [f for f in os.listdir(LOG_DIR) if f.startswith('run_') and f.endswith('.json')]
    files.sort(reverse=True)
    return render_template_string('''
        <h2>Agent Run Logs</h2>
        <ul>
        {% for file in files %}
            <li><a href="/log/{{ file }}">{{ file }}</a></li>
        {% endfor %}
        </ul>
    ''', files=files)

@app.route('/log/<logfile>')
def show_log(logfile):
    if not logfile.startswith('run_') or not logfile.endswith('.json'):
        abort(400)
    log_path = os.path.join(LOG_DIR, logfile)
    if not os.path.exists(log_path):
        abort(404)
    with open(log_path) as f:
        data = json.load(f)
    # Pretty print the log as HTML
    return render_template_string('''
        <h2>Log: {{ logfile }}</h2>
        <pre style="background:#f5f5f5;padding:1em;border-radius:6px;">{{ data | tojson(indent=2) }}</pre>
        <a href="/">Back to log list</a>
    ''', logfile=logfile, data=data)

if __name__ == '__main__':
    app.run(debug=True)
