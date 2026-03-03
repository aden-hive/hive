import { useState, useEffect } from "react";
import axios from "axios";
import "./AgentList.css";

export default function AgentList() {
  const [agents, setAgents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [selectedAgent, setSelectedAgent] = useState(null);

  useEffect(() => {
    fetchAgents();
  }, []);

  const fetchAgents = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await axios.get("/api/hive/agents");
      setAgents(res.data.agents || []);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  if (loading)
    return (
      <div className="agents-container">
        <div className="spinner"></div> Loading agents...
      </div>
    );

  return (
    <div className="agents-container">
      <div className="agents-header">
        <h2>Available Agents</h2>
        <button onClick={fetchAgents} className="refresh-btn">
          🔄 Refresh
        </button>
      </div>

      {error && <div className="error-box">⚠️ {error}</div>}

      {agents.length === 0 ? (
        <div className="empty-state">
          <p>📭 No agents available yet</p>
          <small>Export an agent from Hive to see it here</small>
        </div>
      ) : (
        <div className="agents-grid">
          {agents.map((agent, idx) => (
            <div
              key={idx}
              className="agent-card"
              onClick={() => setSelectedAgent(agent.name)}
            >
              <h3>🤖 {agent.name}</h3>
              <p className="agent-status">
                {agent.example ? "Example" : "Active"}
              </p>
            </div>
          ))}
        </div>
      )}

      {selectedAgent && (
        <div className="agent-detail">
          <h3>Agent: {selectedAgent}</h3>
          <button onClick={() => setSelectedAgent(null)} className="close-btn">
            ✕
          </button>
          <p>Use the "Run Agent" tab to execute this agent</p>
        </div>
      )}

      <button
        className="refresh-btn"
        onClick={fetchAgents}
        style={{ marginTop: "20px" }}
      >
        🔄 Refresh List
      </button>
    </div>
  );
}
