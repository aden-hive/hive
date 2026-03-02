import { useState, useEffect, useRef } from "react";
import axios from "axios";
import "./AgentRunner.css";

export default function AgentRunner() {
  const [input, setInput] = useState("");
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [executionState, setExecutionState] = useState("idle");
  const [history, setHistory] = useState([]);
  const [showHistory, setShowHistory] = useState(false);
  const inputRef = useRef(null);
  const outputRef = useRef(null);

  useEffect(() => {
    checkAgentState();
    loadHistory();
    const interval = setInterval(checkAgentState, 2000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    if (outputRef.current) {
      outputRef.current.scrollTop = outputRef.current.scrollHeight;
    }
  }, [result]);

  const checkAgentState = async () => {
    try {
      console.log("[Web] Checking agent state...");
      const res = await axios.get("/api/hive/state");
      console.log("[Web] Agent state:", res.data);
      setExecutionState(res.data.executionState);
    } catch (err) {
      console.error("[Web] Failed to check agent state:", err.message);
    }
  };

  const loadHistory = async () => {
    try {
      console.log("[Web] Loading execution history...");
      const res = await axios.get("/api/hive/history?limit=20");
      console.log(
        "[Web] History loaded:",
        res.data.history?.length || 0,
        "items",
      );
      setHistory(res.data.history);
    } catch (err) {
      console.error("[Web] Failed to load history:", err.message);
    }
  };

  const handleRunAgent = async (e) => {
    e.preventDefault();
    if (!input.trim()) {
      console.warn("[Web] Empty input - validation failed");
      setError("Please enter a question or request");
      return;
    }

    setLoading(true);
    setError(null);

    try {
      console.log("[Web] ========== AGENT RUN START ==========");
      console.log(`[Web] Input: "${input}"`);
      console.log(`[Web] Input length: ${input.length}`);
      console.log(`[Web] Execution state: ${executionState}`);

      const requestData = { input: input };
      console.log("[Web] Request payload:", requestData);

      const res = await axios.post("/api/hive/run", requestData);

      console.log("[Web] ========== AGENT RUN SUCCESS ==========");
      console.log("[Web] Response received:", res.data);
      console.log("[Web] Result status:", res.data.status);
      console.log("[Web] Output length:", res.data.output?.length || 0);
      console.log("[Web] Session ID:", res.data.sessionId);

      setResult(res.data);
      setInput("");
      loadHistory();
      inputRef.current?.focus();
    } catch (err) {
      console.log("[Web] ========== AGENT RUN FAILED ==========");
      console.error("[Web] Full error object:", err);
      console.error("[Web] Error status:", err.response?.status);
      console.error("[Web] Error headers:", err.response?.headers);
      console.error("[Web] Error data:", err.response?.data);
      console.error("[Web] Error message:", err.message);

      const errorMsg =
        err.response?.data?.error || err.message || "Unknown error occurred";
      console.error("[Web] Final error message:", errorMsg);

      setError(errorMsg);
    } finally {
      setLoading(false);
      console.log("[Web] handleRunAgent completed");
    }
  };

  const handlePause = async () => {
    try {
      await axios.post("/api/hive/pause");
      setExecutionState("paused");
    } catch (err) {
      setError("Failed to pause agent");
    }
  };

  const handleResume = async () => {
    try {
      await axios.post("/api/hive/resume");
      setExecutionState("running");
    } catch (err) {
      setError("Failed to resume agent");
    }
  };

  const handleStop = async () => {
    try {
      await axios.post("/api/hive/stop");
      setExecutionState("idle");
    } catch (err) {
      setError("Failed to stop agent");
    }
  };

  const handleClearHistory = async () => {
    if (window.confirm("Are you sure you want to clear all history?")) {
      try {
        await axios.post("/api/hive/clear-history");
        setHistory([]);
        setResult(null);
      } catch (err) {
        setError("Failed to clear history");
      }
    }
  };

  const getStateColor = () => {
    switch (executionState) {
      case "running":
        return "#ff9500";
      case "paused":
        return "#ffcc00";
      case "idle":
        return "#34c759";
      default:
        return "#8e8e93";
    }
  };

  return (
    <div className="agent-runner">
      <div className="runner-header">
        <div className="header-info">
          <h2>🤖 Customer Service Agent</h2>
          <div className="agent-status">
            <span
              className="status-dot"
              style={{ backgroundColor: getStateColor() }}
            ></span>
            <span className="status-text">
              {executionState.charAt(0).toUpperCase() + executionState.slice(1)}
            </span>
          </div>
        </div>
        <div className="header-controls">
          <button
            onClick={() => setShowHistory(!showHistory)}
            className="btn-secondary"
            title="Show session history"
          >
            📋 History ({history.length})
          </button>
          {history.length > 0 && (
            <button
              onClick={handleClearHistory}
              className="btn-danger"
              title="Clear all history"
            >
              🗑️ Clear
            </button>
          )}
        </div>
      </div>

      {showHistory && (
        <div className="history-panel">
          <div className="history-header">
            <h3>Session History</h3>
            <button className="btn-close" onClick={() => setShowHistory(false)}>
              ✕
            </button>
          </div>
          <div className="history-list">
            {history.length === 0 ? (
              <p className="empty-state">No session history yet</p>
            ) : (
              history.map((session, idx) => (
                <div
                  key={idx}
                  className="history-item"
                  onClick={() => {
                    setResult(session);
                    setShowHistory(false);
                  }}
                >
                  <div className="history-input">
                    <strong>Q:</strong> {session.input.substring(0, 50)}
                    {session.input.length > 50 ? "..." : ""}
                  </div>
                  <div className="history-time">
                    {new Date(session.timestamp).toLocaleTimeString()}
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      )}

      <form onSubmit={handleRunAgent} className="runner-form">
        <div className="form-input-group">
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            disabled={loading || executionState === "paused"}
            placeholder="Enter your customer service request or question..."
            className="agent-input"
            rows="3"
          />
        </div>

        {error && <div className="error-message">⚠️ {error}</div>}

        <div className="form-buttons">
          <button
            type="submit"
            disabled={loading || executionState !== "idle"}
            className={`btn-primary ${loading ? "loading" : ""}`}
            title={
              executionState !== "idle"
                ? "Agent is currently executing"
                : "Send request to agent"
            }
          >
            {loading ? (
              <>
                <span className="spinner"></span> Processing...
              </>
            ) : (
              <>✉️ Send Message</>
            )}
          </button>

          {executionState === "running" && (
            <>
              <button
                type="button"
                onClick={handlePause}
                className="btn-secondary"
                title="Pause execution"
              >
                ⏸ Pause
              </button>
              <button
                type="button"
                onClick={handleStop}
                className="btn-danger"
                title="Stop execution"
              >
                ⏹ Stop
              </button>
            </>
          )}

          {executionState === "paused" && (
            <button
              type="button"
              onClick={handleResume}
              className="btn-secondary"
              title="Resume execution"
            >
              ▶️ Resume
            </button>
          )}
        </div>
      </form>

      {result && (
        <div className="result-section">
          <div className="result-header">
            <h3>Agent Response</h3>
            <div className="result-meta">
              <span className="result-time">
                {new Date(result.timestamp).toLocaleTimeString()}
              </span>
              {result.sessionId && (
                <span className="result-session">ID: {result.sessionId}</span>
              )}
            </div>
          </div>

          <div className="result-container">
            <div className="result-input-box">
              <h4>📥 Your Input:</h4>
              <p>{result.input}</p>
            </div>

            <div className="result-output-box">
              <h4>📤 Agent Output:</h4>
              <pre ref={outputRef} className="result-output">
                {result.output || "[No output]"}
              </pre>
            </div>
          </div>

          <div className="result-footer">
            <button
              onClick={() => setResult(null)}
              className="btn-secondary"
              title="Close response"
            >
              ✕ Close
            </button>
            <button
              onClick={() => setInput(result.input)}
              className="btn-secondary"
              title="Send similar request"
            >
              🔄 Re-ask
            </button>
          </div>
        </div>
      )}

      {!result && !loading && executionState === "idle" && (
        <div className="empty-state-container">
          <div className="empty-state">
            <h3>👋 Welcome to the Customer Service Agent</h3>
            <p>Ask questions like:</p>
            <ul className="example-queries">
              <li>"I forgot my password"</li>
              <li>"How much does Product X cost?"</li>
              <li>"What's in my shopping cart?"</li>
              <li>"Where is my order?"</li>
            </ul>
          </div>
        </div>
      )}
    </div>
  );
}
