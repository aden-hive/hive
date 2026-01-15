import { useEffect, useState } from 'react';
import { apiClient } from '../services/api';

interface HealthStatus {
  status: string;
  timestamp: string;
}

export function HomePage() {
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiClient
      .get<HealthStatus>('/health')
      .then(setHealth)
      .catch((err) => setError(err.message));
  }, []);

  return (
    <div className="container">
      <header className="header">
        <h1>Welcome to Hive</h1>
        <p>AI agent observability and control</p>
      </header>

      <main className="main">
        <section className="status-card">
          <h2>API Status</h2>
          {error && <p className="error">Error: {error}</p>}
          {health && (
            <div className="status-info">
              <p>
                Status: <span className="status-badge">{health.status}</span>
              </p>
              <p>Last checked: {new Date(health.timestamp).toLocaleString()}</p>
            </div>
          )}
          {!health && !error && <p>Checking API status...</p>}
        </section>
      </main>

      <footer className="footer">
        <p>Hive &copy; {new Date().getFullYear()}</p>
      </footer>
    </div>
  );
}
