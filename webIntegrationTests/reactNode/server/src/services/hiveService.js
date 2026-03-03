import { execSync } from "child_process";

export function execCommand(command) {
  try {
    const output = execSync(command, { encoding: "utf-8", shell: "/bin/bash" });
    return output;
  } catch (error) {
    throw new Error(`Command failed: ${error.message}`);
  }
}

export async function listAgentsService() {
  try {
    // Try to list agents; if none exist, return empty array
    const output = execCommand("hive list");
    const lines = output.split("\n").filter((line) => line.trim());
    // Parse agent names from output (adjust regex based on actual hive list format)
    const agents = lines
      .filter((line) => !line.includes("Agent") && line.trim())
      .map((line) => ({ name: line.trim() }));
    return agents.length > 0
      ? agents
      : [{ name: "No agents exported yet", example: true }];
  } catch (error) {
    console.warn("Warning listing agents:", error.message);
    return [{ name: "No agents exported yet", example: true }];
  }
}

export async function getAgentInfoService(agentName) {
  try {
    const output = execCommand(`hive info exports/${agentName}`);
    return {
      name: agentName,
      info: output,
      timestamp: new Date().toISOString(),
    };
  } catch (error) {
    throw new Error(
      `Could not fetch info for agent ${agentName}: ${error.message}`,
    );
  }
}

export async function runAgentService(agentName, input = {}) {
  try {
    const inputStr = JSON.stringify(input);
    const command = `hive run exports/${agentName} --input '${inputStr}'`;
    const output = execCommand(command);
    return {
      agentName,
      output,
      status: "success",
      timestamp: new Date().toISOString(),
    };
  } catch (error) {
    return {
      agentName,
      status: "error",
      error: error.message,
      timestamp: new Date().toISOString(),
    };
  }
}
