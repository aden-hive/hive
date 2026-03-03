/**
 * Agent Web Service
 * Bridges the Hive framework with the web dashboard
 * Handles agent execution, state management, and real-time updates
 */

import { spawn, execSync } from "child_process";
import path from "path";
import os from "os";
import { fileURLToPath } from "url";
import { existsSync } from "fs";

class AgentWebService {
  constructor() {
    this.agentProcess = null;
    this.currentSession = null;
    this.sessionHistory = [];
    this.executionState = "idle"; // idle, running, paused
    this.lastMessage = null;
    this.pythonPath = this.findPython();
  }

  /**
   * Find Python executable in system PATH or common installation locations
   */
  findPython() {
    // Windows: Try direct 'python' command first
    if (os.platform() === "win32") {
      try {
        // Test if 'python' works directly
        execSync("python --version", {
          encoding: "utf-8",
          stdio: ["pipe", "pipe", "pipe"],
        });
        console.log("[Python] Using direct 'python' command");
        return "python";
      } catch (e) {
        console.log("[Python] Direct 'python' command failed");
      }

      try {
        // Test if 'python3' works directly
        execSync("python3 --version", {
          encoding: "utf-8",
          stdio: ["pipe", "pipe", "pipe"],
        });
        console.log("[Python] Using direct 'python3' command");
        return "python3";
      } catch (e) {
        console.log("[Python] Direct 'python3' command failed");
      }

      // Try common Windows paths as fallback
      const pythonPaths = [
        "C:\\Users\\yokas\\AppData\\Local\\Programs\\Python\\Python314\\python.exe",
        "C:\\Users\\yokas\\AppData\\Local\\Programs\\Python\\Python313\\python.exe",
        "C:\\Users\\yokas\\AppData\\Local\\Programs\\Python\\Python312\\python.exe",
        "C:\\Python314\\python.exe",
        "C:\\Python313\\python.exe",
        "C:\\Python312\\python.exe",
      ];

      for (const pythonPath of pythonPaths) {
        if (existsSync(pythonPath)) {
          console.log("[Python] Found at common path:", pythonPath);
          return pythonPath;
        }
      }
    }

    // Unix-like systems
    try {
      const result = execSync("which python", { encoding: "utf-8" }).trim();
      if (result && existsSync(result)) {
        console.log("[Python] Found via 'which python':", result);
        return result;
      }
    } catch (e) {
      console.log("[Python] 'which python' failed:", e.message);
    }

    try {
      const result = execSync("which python3", { encoding: "utf-8" }).trim();
      if (result && existsSync(result)) {
        console.log("[Python] Found via 'which python3':", result);
        return result;
      }
    } catch (e) {
      console.log("[Python] 'which python3' failed:", e.message);
    }

    // Fallback
    console.log("[Python] Using fallback 'python' command");
    return "python";
  }

  /**
   * Start the Customer Service Agent
   */
  async startAgent(agentInput) {
    if (this.executionState === "running") {
      throw new Error("Agent is already running");
    }

    return new Promise((resolve, reject) => {
      try {
        const hiveDir = path.resolve(
          path.dirname(fileURLToPath(import.meta.url)),
          "../../../hive",
        );

        // Add environment variables
        const env = {
          ...process.env,
          PYTHONUNBUFFERED: "1",
        };

        console.log(`[Agent] Using Python: ${this.pythonPath}`);
        console.log(`[Agent] Working directory: ${hiveDir}`);

        // Build the command - use Python directly as the executable
        // This works on Windows, macOS, and Linux
        const args = [
          "-m",
          "framework",
          "run",
          "customer_service_agent",
          "--input",
          agentInput,
        ];

        const options = {
          cwd: hiveDir,
          env: env,
          maxBuffer: 1024 * 1024 * 10, // 10MB buffer
          stdio: ["pipe", "pipe", "pipe"], // Separate pipes for stdin, stdout, stderr
        };

        console.log(`[Agent] Command: ${this.pythonPath} ${args.join(" ")}`);
        this.agentProcess = spawn(this.pythonPath, args, options);

        this.executionState = "running";
        let output = "";
        let errorOutput = "";

        // Capture stdout
        this.agentProcess.stdout.on("data", (data) => {
          const dataStr = data.toString();
          output += dataStr;
          console.log(`[Agent Output] stdout: ${dataStr}`);
        });

        // Capture stderr
        this.agentProcess.stderr.on("data", (data) => {
          const dataStr = data.toString();
          errorOutput += dataStr;
          console.log(`[Agent Output] stderr: ${dataStr}`);
        });

        // Handle process exit
        this.agentProcess.on("close", (code) => {
          this.executionState = "idle";
          console.log(`[Agent] Process closed with code: ${code}`);
          console.log(`[Agent] Total output length: ${output.length} bytes`);
          console.log(
            `[Agent] Total error length: ${errorOutput.length} bytes`,
          );

          if (code === 0) {
            const result = {
              status: "success",
              input: agentInput,
              output: output,
              timestamp: new Date().toISOString(),
              sessionId: this.generateSessionId(),
            };

            // Store in history
            this.sessionHistory.push(result);
            this.lastMessage = result;
            console.log(`[Agent] Session stored with ID: ${result.sessionId}`);

            resolve(result);
          } else {
            const error = new Error(
              `Agent process exited with code ${code}. Error: ${errorOutput}`,
            );
            console.error(`[Agent] Process error: ${error.message}`);
            reject(error);
          }
        });

        // Handle process errors
        this.agentProcess.on("error", (error) => {
          this.executionState = "idle";
          console.error("[Agent] CRITICAL Process spawn error:", error);
          console.error("[Agent] Error code:", error.code);
          console.error("[Agent] Error errno:", error.errno);
          console.error("[Agent] Error syscall:", error.syscall);
          console.error("[Agent] Error path:", error.path);
          console.error("[Agent] Possible causes:");
          console.error(
            "  1. Python not in PATH - Install Python or add to PATH",
          );
          console.error("  2. Shell command not found (bash/sh not available)");
          console.error(
            "  3. Hive framework not installed - run 'pip install hive-framework'",
          );
          reject(error);
        });

        // Set timeout (10 minutes max)
        setTimeout(() => {
          if (this.executionState === "running") {
            this.agentProcess.kill();
            reject(new Error("Agent execution timeout"));
          }
        }, 600000);
      } catch (error) {
        this.executionState = "idle";
        reject(error);
      }
    });
  }

  /**
   * Get the current execution state
   */
  getState() {
    return {
      executionState: this.executionState,
      lastMessage: this.lastMessage,
      sessionCount: this.sessionHistory.length,
    };
  }

  /**
   * Get session history
   */
  getHistory(limit = 10) {
    return this.sessionHistory.slice(-limit);
  }

  /**
   * Pause the current execution
   */
  pauseExecution() {
    if (this.executionState === "running" && this.agentProcess) {
      this.executionState = "paused";
      // Send SIGSTOP signal
      process.kill(this.agentProcess.pid, "SIGSTOP");
    }
  }

  /**
   * Resume execution
   */
  resumeExecution() {
    if (this.executionState === "paused" && this.agentProcess) {
      this.executionState = "running";
      // Send SIGCONT signal
      process.kill(this.agentProcess.pid, "SIGCONT");
    }
  }

  /**
   * Stop the current execution
   */
  stopExecution() {
    if (this.agentProcess) {
      this.agentProcess.kill();
      this.executionState = "idle";
    }
  }

  /**
   * Clear session history
   */
  clearHistory() {
    this.sessionHistory = [];
  }

  /**
   * Generate a unique session ID
   */
  generateSessionId() {
    return `session-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
  }

  /**
   * List available agents
   */
  async listAgents() {
    return new Promise((resolve, reject) => {
      const args = ["-m", "framework", "list"];

      const hiveDir = path.resolve(
        path.dirname(fileURLToPath(import.meta.url)),
        "../../../hive",
      );

      console.log(`[ListAgents] Using Python: ${this.pythonPath}`);
      console.log(`[ListAgents] Working directory: ${hiveDir}`);

      const options = {
        cwd: hiveDir,
        env: { ...process.env, PYTHONUNBUFFERED: "1" },
        maxBuffer: 1024 * 1024 * 10,
        stdio: ["pipe", "pipe", "pipe"],
      };

      console.log(`[ListAgents] Command: ${this.pythonPath} ${args.join(" ")}`);

      const agentProcess = spawn(this.pythonPath, args, options);

      let output = "";
      let errorOutput = "";

      agentProcess.stdout.on("data", (data) => {
        const dataStr = data.toString();
        output += dataStr;
        console.log(`[ListAgents] stdout: ${dataStr}`);
      });

      agentProcess.stderr.on("data", (data) => {
        const dataStr = data.toString();
        errorOutput += dataStr;
        console.log(`[ListAgents] stderr: ${dataStr}`);
      });

      agentProcess.on("close", (code) => {
        console.log(`[ListAgents] Process closed with code: ${code}`);
        if (code === 0) {
          console.log(`[ListAgents] Agents output length: ${output.length}`);
          resolve({
            agents: output,
            timestamp: new Date().toISOString(),
          });
        } else {
          const error = new Error(
            `Failed to list agents (code ${code}): ${errorOutput}`,
          );
          console.error(`[ListAgents] ${error.message}`);
          reject(error);
        }
      });

      agentProcess.on("error", (error) => {
        console.error("[ListAgents] Spawn error:", error);
        console.error("[ListAgents] Error code:", error.code);
        console.error("[ListAgents] Error syscall:", error.syscall);
        reject(error);
      });
    });
  }

  /**
   * Get agent information
   */
  async getAgentInfo(agentName) {
    return new Promise((resolve, reject) => {
      const hiveDir = path.resolve(
        path.dirname(fileURLToPath(import.meta.url)),
        "../../../hive",
      );

      const args = ["-m", "framework", "info", agentName];

      const options = {
        cwd: hiveDir,
        env: { ...process.env, PYTHONUNBUFFERED: "1" },
        maxBuffer: 1024 * 1024 * 10,
        stdio: ["pipe", "pipe", "pipe"],
      };

      const agentProcess = spawn(this.pythonPath, args, options);

      let output = "";

      agentProcess.stdout.on("data", (data) => {
        output += data.toString();
      });

      agentProcess.on("close", (code) => {
        if (code === 0) {
          resolve({
            info: output,
            agent: agentName,
            timestamp: new Date().toISOString(),
          });
        } else {
          reject(new Error(`Failed to get info for ${agentName}`));
        }
      });
    });
  }
}

export default new AgentWebService();
