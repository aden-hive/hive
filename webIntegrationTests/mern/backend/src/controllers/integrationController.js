import {
  getAvailableIntegrations,
  loadIntegrationConfig,
  saveIntegrationConfig,
  testIntegrationConnection,
} from "../services/integrationService.js";

export async function listIntegrations(req, res) {
  try {
    const integrations = await getAvailableIntegrations();
    res.json({
      integrations,
      count: integrations.length,
      timestamp: new Date().toISOString(),
    });
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
}

export async function getIntegration(req, res) {
  try {
    const { name } = req.params;
    const config = await loadIntegrationConfig(name);
    res.json({
      name,
      config,
      timestamp: new Date().toISOString(),
    });
  } catch (error) {
    res.status(404).json({ error: `Integration ${name} not found` });
  }
}

export async function configureIntegration(req, res) {
  try {
    const { name } = req.params;
    const { credentials, settings } = req.body;

    if (!credentials || !Object.keys(credentials).length) {
      return res.status(400).json({ error: "Credentials are required" });
    }

    await saveIntegrationConfig(name, { credentials, settings });
    res.json({
      status: "success",
      message: `Integration ${name} configured successfully`,
      timestamp: new Date().toISOString(),
    });
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
}

export async function testIntegration(req, res) {
  try {
    const { name } = req.params;
    const result = await testIntegrationConnection(name);

    res.json({
      name,
      status: result.success ? "connected" : "failed",
      message: result.message,
      timestamp: new Date().toISOString(),
    });
  } catch (error) {
    res.status(500).json({
      name: req.params.name,
      status: "error",
      message: error.message,
    });
  }
}

export async function removeIntegration(req, res) {
  try {
    const { name } = req.params;
    // In a real implementation, this would remove stored credentials
    res.json({
      status: "success",
      message: `Integration ${name} removed`,
      timestamp: new Date().toISOString(),
    });
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
}
