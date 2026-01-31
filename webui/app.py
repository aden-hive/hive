from flask import Flask, render_template, request, send_from_directory, abort
import os
import json

app = Flask(__name__)

# Path to agent run logs
def get_logs_dir():
    # Default: ../agent_logs/runs relative to webui/
    return os.path.abspath(os.path.join(os.path.dirname(__file__), '../agent_logs/runs'))

@app.route('/')
def index():
    logs_dir = get_logs_dir()
    try:
        files = [f for f in os.listdir(logs_dir) if f.endswith('.json')]
        files.sort(reverse=True)
    except Exception:
        files = []
    return render_template('index.html', files=files)

@app.route('/log/<filename>')
def show_log(filename):
    logs_dir = get_logs_dir()
    if not filename.endswith('.json'):
        abort(404)
    log_path = os.path.join(logs_dir, filename)
    if not os.path.exists(log_path):
        abort(404)
    with open(log_path, 'r') as f:
        run = json.load(f)
    return render_template('log.html', run=run, filename=filename)

@app.route('/logs/<filename>')
def download_log(filename):
    logs_dir = get_logs_dir()
    return send_from_directory(logs_dir, filename, as_attachment=True)

if __name__ == '__main__':
    app.run(debug=True)
