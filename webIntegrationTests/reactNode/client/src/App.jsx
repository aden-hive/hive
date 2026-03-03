import { useState, useEffect } from "react";
import axios from "axios";
import "./App.css";
import Dashboard from "./components/Dashboard";
import Status from "./components/Status";
import AgentList from "./components/AgentList";
import AgentRunner from "./components/AgentRunner";
import Integrations from "./components/Integrations";

function App() {
  const [activeTab, setActiveTab] = useState("status");
  const [backendStatus, setBackendStatus] = useState("checking");

  useEffect(() => {
    checkBackendHealth();
  }, []);

  const checkBackendHealth = async () => {
    try {
      await axios.get("/api/health", { timeout: 5000 });
      setBackendStatus("online");
    } catch (error) {
      setBackendStatus("offline");
    }
  };

  return (
    <div className="app">
      <header className="app-header">
        <div className="header-content">
          <h1>🐝 Hive Agent Dashboard</h1>
          <div className={`status-badge ${backendStatus}`}>
            {backendStatus === "online"
              ? "✓ Backend Online"
              : "✗ Backend Offline"}
          </div>
        </div>
      </header>

      <nav className="app-nav">
        <button
          className={`nav-btn ${activeTab === "status" ? "active" : ""}`}
          onClick={() => setActiveTab("status")}
        >
          📊 Status
        </button>
        <button
          className={`nav-btn ${activeTab === "agents" ? "active" : ""}`}
          onClick={() => setActiveTab("agents")}
        >
          🤖 Agents
        </button>
        <button
          className={`nav-btn ${activeTab === "run" ? "active" : ""}`}
          onClick={() => setActiveTab("run")}
        >
          ▶️ Run Agent
        </button>
        <button
          className={`nav-btn ${activeTab === "integrations" ? "active" : ""}`}
          onClick={() => setActiveTab("integrations")}
        >
          🔌 Integrations
        </button>
        <button
          className={`nav-btn ${activeTab === "dashboard" ? "active" : ""}`}
          onClick={() => setActiveTab("dashboard")}
        >
          📈 Dashboard
        </button>
      </nav>

      <main className="app-main">
        {activeTab === "status" && <Status />}
        {activeTab === "agents" && <AgentList />}
        {activeTab === "run" && <AgentRunner />}
        {activeTab === "integrations" && <Integrations />}
        {activeTab === "dashboard" && <Dashboard />}
      </main>

      <footer className="app-footer">
        <p>Hive Web Dashboard • Built with React + Vite + Node.js</p>
      </footer>
    </div>
  );
}

export default App;
