import { useState, useEffect } from "react";
import axios from "axios";
import "./Status.css";

export default function Status() {
  const [status, setStatus] = useState(null);
  const [hiveStatus, setHiveStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetchStatus();
  }, []);

  const fetchStatus = async () => {
    setLoading(true);
    setError(null);
    try {
      console.log("[Status] Fetching status...");

      const [healthRes, hiveRes] = await Promise.all([
        axios.get("/api/health"),
        axios.get("/api/hive/status"),
      ]);

      console.log("[Status] Health response:", healthRes.data);
      console.log("[Status] Hive response:", hiveRes.data);

      setStatus(healthRes.data);
      setHiveStatus(hiveRes.data);
      console.log("[Status] Status fetch successful");
    } catch (err) {
      console.error("[Status] Error fetching status:", err.message);
      console.error("[Status] Error details:", err.response?.data);
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  if (loading)
    return (
      <div className="status-container">
        <div className="spinner"></div> Loading...
      </div>
    );

  return (
    <div className="status-container">
      <div className="status-cards">
        <div
          className={`status-card ${status?.status === "Backend is running" ? "success" : "error"}`}
        >
          <h3>🖥️ Backend</h3>
          <p className="status-value">{status?.status}</p>
          <p className="status-time">
            {new Date(status?.timestamp).toLocaleTimeString()}
          </p>
        </div>

        <div
          className={`status-card ${hiveStatus?.status === "running" ? "success" : "error"}`}
        >
          <h3>🐝 Hive</h3>
          <p className="status-value">
            {hiveStatus?.status === "running" ? "Operational" : "Not Available"}
          </p>
          <p className="status-message">{hiveStatus?.message}</p>
        </div>
      </div>

      {error && <div className="error-box">⚠️ {error}</div>}

      <button className="refresh-btn" onClick={fetchStatus}>
        🔄 Refresh Status
      </button>
    </div>
  );
}
