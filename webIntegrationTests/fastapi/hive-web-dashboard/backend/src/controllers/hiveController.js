import {
  execCommand,
  listAgentsService,
  getAgentInfoService,
  runAgentService,
} from "../services/hiveService.js";

export async function getHiveStatus(req, res) {
  try {
    const result = await execCommand("hive --help");
    res.json({
      status: "running",
      message: "Hive is installed and operational",
      timestamp: new Date().toISOString(),
    });
  } catch (error) {
    res.status(500).json({
      status: "error",
      message: "Hive is not accessible",
      error: error.message,
    });
  }
}

export async function listAgents(req, res) {
  try {
    const agents = await listAgentsService();
    res.json({ agents, count: agents.length });
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
}

export async function getAgentInfo(req, res) {
  try {
    const { name } = req.params;
    const info = await getAgentInfoService(name);
    res.json(info);
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
}

export async function runAgent(req, res) {
  try {
    const { agentName, input } = req.body;
    if (!agentName) {
      return res.status(400).json({ error: "agentName is required" });
    }
    const result = await runAgentService(agentName, input);
    res.json(result);
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
}
