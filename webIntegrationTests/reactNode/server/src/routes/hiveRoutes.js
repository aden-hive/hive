/**
 * Hive Agent Routes
 * RESTful endpoints for agent interaction via web dashboard
 */

import express from "express";
import agentWebService from "../services/agentWebService.js";

const router = express.Router();

/**
 * POST /api/hive/run
 * Execute an agent with user input
 *
 * Body: { input: string }
 * Response: { status, input, output, sessionId, timestamp }
 */
router.post("/run", async (req, res) => {
  try {
    const { input } = req.body;

    if (!input || input.trim() === "") {
      console.warn(`[Route] /run: Empty input received`);
      return res.status(400).json({ error: "Input is required" });
    }

    console.log(`[Route] POST /api/hive/run received`);
    console.log(`[Route] Input: "${input}"`);
    console.log(
      `[Route] Current execution state: ${agentWebService.executionState}`,
    );

    const result = await agentWebService.startAgent(input);

    console.log(`[Route] Agent execution completed successfully`);
    console.log(`[Route] Result status: ${result.status}`);
    console.log(`[Route] Result output length: ${result.output.length}`);
    console.log(`[Route] Session ID: ${result.sessionId}`);

    res.json(result);
  } catch (error) {
    console.error("[Route] ERROR in /run:", error.message);
    console.error("[Route] Error stack:", error.stack);
    res.status(500).json({
      error: error.message,
      details: error.stack,
    });
  }
});

/**
 * GET /api/hive/state
 * Get current agent execution state
 */
router.get("/state", (req, res) => {
  try {
    console.log(`[Route] GET /api/hive/state`);
    const state = agentWebService.getState();
    console.log(`[Route] Current state: ${JSON.stringify(state)}`);
    res.json(state);
  } catch (error) {
    console.error("[Route] Error in /state:", error);
    res.status(500).json({ error: error.message });
  }
});

/**
 * GET /api/hive/history
 * Get session history
 */
router.get("/history", (req, res) => {
  try {
    const limit = parseInt(req.query.limit) || 10;
    const history = agentWebService.getHistory(limit);
    res.json({
      history: history,
      total: history.length,
    });
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

/**
 * POST /api/hive/pause
 * Pause current agent execution
 */
router.post("/pause", (req, res) => {
  try {
    agentWebService.pauseExecution();
    res.json({ status: "paused" });
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

/**
 * POST /api/hive/resume
 * Resume paused agent execution
 */
router.post("/resume", (req, res) => {
  try {
    agentWebService.resumeExecution();
    res.json({ status: "resumed" });
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

/**
 * POST /api/hive/stop
 * Stop current agent execution
 */
router.post("/stop", (req, res) => {
  try {
    agentWebService.stopExecution();
    res.json({ status: "stopped" });
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

/**
 * POST /api/hive/clear-history
 * Clear session history
 */
router.post("/clear-history", (req, res) => {
  try {
    agentWebService.clearHistory();
    res.json({ status: "history cleared" });
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

/**
 * GET /api/hive/agents
 * List available agents
 */
router.get("/agents", async (req, res) => {
  try {
    console.log(`[Route] GET /api/hive/agents`);
    const agents = await agentWebService.listAgents();
    console.log(
      `[Route] Agents retrieved: ${agents.agents.substring(0, 100)}...`,
    );
    res.json(agents);
  } catch (error) {
    console.error("[Route] Error in /agents:", error.message);
    console.error("[Route] Stack:", error.stack);
    res.status(500).json({
      error: error.message,
      details: error.stack,
    });
  }
});

/**
 * GET /api/hive/agents/:name
 * Get agent information
 */
router.get("/agents/:name", async (req, res) => {
  try {
    const { name } = req.params;
    const info = await agentWebService.getAgentInfo(name);
    res.json(info);
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

export default router;
