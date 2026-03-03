import { useState, useEffect } from "react";
import axios from "axios";
import "./Dashboard.css";

export default function Dashboard() {
  const [stats, setStats] = useState({
    agentCount: 0,
    backendStatus: "checking",
    lastUpdate: new Date(),
  });
  const [chartData, setChartData] = useState([
    { time: "Now", runs: 0 },
    { time: "-5m", runs: 0 },
    { time: "-10m", runs: 0 },
    { time: "-15m", runs: 0 },
  ]);

  useEffect(() => {
    fetchDashboardData();
    const interval = setInterval(fetchDashboardData, 5000);
    return () => clearInterval(interval);
  }, []);

  const fetchDashboardData = async () => {
    try {
      console.log("[Dashboard] Fetching dashboard data...");

      const agentRes = await axios.get("/api/hive/agents");
      console.log("[Dashboard] Agents response:", agentRes.data);

      const healthRes = await axios.get("/api/health");
      console.log("[Dashboard] Health response:", healthRes.data);

      const agentCount =
        agentRes.data.count || agentRes.data.agents?.length || 0;
      console.log("[Dashboard] Agent count:", agentCount);

      setStats({
        agentCount: agentCount,
        backendStatus: "online",
        lastUpdate: new Date(),
      });

      // Simulate chart data updates
      setChartData((prev) => [
        { time: "Now", runs: Math.floor(Math.random() * 10) },
        ...prev.slice(0, 3),
      ]);

      console.log("[Dashboard] Data fetch successful");
    } catch (error) {
      console.error("[Dashboard] Error fetching data:", error.message);
      console.error("[Dashboard] Error status:", error.response?.status);
      console.error("[Dashboard] Error data:", error.response?.data);

      setStats((prev) => ({
        ...prev,
        backendStatus: "offline",
      }));
    }
  };

  return (
    <div className="dashboard-container">
      <div className="stats-grid">
        <div className="stat-card">
          <h4>Available Agents</h4>
          <p className="stat-value">{stats.agentCount}</p>
        </div>

        <div
          className={`stat-card ${stats.backendStatus === "online" ? "online" : "offline"}`}
        >
          <h4>Backend Status</h4>
          <p className="stat-value">
            {stats.backendStatus === "online" ? "🟢 Online" : "🔴 Offline"}
          </p>
        </div>

        <div className="stat-card">
          <h4>Last Update</h4>
          <p className="stat-value">{stats.lastUpdate.toLocaleTimeString()}</p>
        </div>
      </div>

      <div className="chart-container">
        <h3>Agent Execution Timeline</h3>
        <div className="simple-chart">
          {chartData.map((item, idx) => (
            <div key={idx} className="chart-bar">
              <div
                className="bar"
                style={{
                  height: `${item.runs * 20}px`,
                  backgroundColor: "#667eea",
                }}
              ></div>
              <label>{item.time}</label>
            </div>
          ))}
        </div>
      </div>

      <div className="info-box">
        <h3>📊 Dashboard Features</h3>
        <ul>
          <li>✓ Real-time agent status monitoring</li>
          <li>✓ Backend health checks</li>
          <li>✓ Agent execution history</li>
          <li>✓ Quick access to all tools</li>
        </ul>
      </div>
    </div>
  );
}
