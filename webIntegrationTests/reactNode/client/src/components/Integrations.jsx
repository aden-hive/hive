import { useState, useEffect } from "react";
import axios from "axios";
import "./Integrations.css";

export default function Integrations() {
  const [integrations, setIntegrations] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [selectedIntegration, setSelectedIntegration] = useState(null);
  const [credentials, setCredentials] = useState({});
  const [testResult, setTestResult] = useState(null);

  useEffect(() => {
    fetchIntegrations();
  }, []);

  const fetchIntegrations = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await axios.get("/api/integrations");
      setIntegrations(res.data.integrations || []);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleSelectIntegration = (integration) => {
    setSelectedIntegration(integration);
    setCredentials({});
    setTestResult(null);
  };

  const handleCredentialChange = (field, value) => {
    setCredentials((prev) => ({
      ...prev,
      [field]: value,
    }));
  };

  const handleConfigure = async () => {
    if (!selectedIntegration || !Object.keys(credentials).length) {
      setError("Please fill in all required credentials");
      return;
    }

    try {
      await axios.post(
        `/api/integrations/${selectedIntegration.name}/configure`,
        {
          credentials,
          settings: {},
        },
      );
      setError(null);
      setTestResult({
        status: "success",
        message: `${selectedIntegration.displayName} configured successfully!`,
      });
      fetchIntegrations();
    } catch (err) {
      setError(err.response?.data?.error || err.message);
    }
  };

  const handleTest = async () => {
    if (!selectedIntegration) {
      setError("Please select an integration");
      return;
    }

    try {
      const res = await axios.post(
        `/api/integrations/${selectedIntegration.name}/test`,
      );
      setTestResult(res.data);
    } catch (err) {
      setTestResult({
        status: "error",
        message: err.response?.data?.message || err.message,
      });
    }
  };

  if (loading) {
    return (
      <div className="integrations-container">
        <div className="spinner"></div> Loading integrations...
      </div>
    );
  }

  return (
    <div className="integrations-container">
      <div className="integrations-header">
        <h2>🔌 Integrations</h2>
        <p className="subtitle">
          Connect your Hive agents to external services and APIs
        </p>
      </div>

      {error && !testResult && <div className="error-box">⚠️ {error}</div>}

      <div className="integrations-layout">
        <div className="integrations-list">
          <h3>Available Integrations</h3>
          <div className="integration-grid">
            {integrations.map((integration) => (
              <div
                key={integration.name}
                className={`integration-card ${
                  selectedIntegration?.name === integration.name
                    ? "selected"
                    : ""
                } ${integration.configured ? "configured" : ""}`}
                onClick={() => handleSelectIntegration(integration)}
              >
                <div className="integration-icon">{integration.icon}</div>
                <h4>{integration.displayName}</h4>
                <p className="integration-description">
                  {integration.description}
                </p>
                {integration.configured && (
                  <span className="configured-badge">✓ Configured</span>
                )}
              </div>
            ))}
          </div>
        </div>

        <div className="integrations-detail">
          {selectedIntegration ? (
            <>
              <div className="detail-header">
                <h3>
                  {selectedIntegration.icon} {selectedIntegration.displayName}
                </h3>
                <p className="detail-description">
                  {selectedIntegration.description}
                </p>
              </div>

              <div className="credentials-form">
                <h4>Credentials</h4>
                {selectedIntegration.credentials.map((field) => (
                  <div key={field} className="form-group">
                    <label>{field}</label>
                    <input
                      type={
                        field.includes("password") ||
                        field.includes("secret") ||
                        field.includes("token")
                          ? "password"
                          : "text"
                      }
                      placeholder={`Enter ${field}`}
                      value={credentials[field] || ""}
                      onChange={(e) =>
                        handleCredentialChange(field, e.target.value)
                      }
                    />
                  </div>
                ))}

                <div className="action-buttons">
                  <button
                    className="btn-configure"
                    onClick={handleConfigure}
                    disabled={
                      !Object.keys(credentials).length ||
                      Object.values(credentials).some((v) => !v)
                    }
                  >
                    💾 Save Configuration
                  </button>
                  <button
                    className="btn-test"
                    onClick={handleTest}
                    disabled={!selectedIntegration.configured}
                  >
                    🧪 Test Connection
                  </button>
                </div>
              </div>

              {testResult && (
                <div
                  className={`test-result ${
                    testResult.status === "success" ? "success" : "error"
                  }`}
                >
                  <h4>
                    {testResult.status === "success"
                      ? "✓ Test Passed"
                      : "✗ Test Failed"}
                  </h4>
                  <p>{testResult.message}</p>
                </div>
              )}
            </>
          ) : (
            <div className="empty-state">
              <p>👈 Select an integration to configure</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
