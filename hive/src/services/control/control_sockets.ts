/**
 * Aden Control Sockets
 *
 * WebSocket namespace for real-time control plane communication.
 * Handles:
 * - SDK connections and authentication
 * - Real-time policy updates
 * - Event ingestion
 * - Heartbeat monitoring
 */

import jwt from "jsonwebtoken";
// Note: userDB.findSaltByToken will be injected via initialization
import controlService from "./control_service";
import llmEventBatcher from "./llm_event_batcher";
import type { Server, Socket, Namespace } from "socket.io";

interface UserDbService {
  findSaltByToken: (token: string) => Promise<string | null>;
}

let userDbService: UserDbService | null = null;
let jwtSecret: string = "";

/**
 * Set user DB service for JWT verification
 * @param service - User DB service with findSaltByToken method
 * @param secret - JWT secret for token verification
 */
function setUserDbService(service: UserDbService, secret?: string): void {
  userDbService = service;
  if (secret) {
    jwtSecret = secret;
  }
}

interface InstanceInfo {
  socket: Socket;
  instanceId: string;
  policyId: string | null;
  connectedAt: Date;
  lastHeartbeat: Date;
}

// HTTP-only agents (no socket connection)
interface HttpInstanceInfo {
  instanceId: string;
  policyId: string | null;
  agentName: string | null;
  status: string;
  firstSeen: Date;
  lastHeartbeat: Date;
}

// Track connected SDK instances (WebSocket)
// teamId -> Map<socketId, { socket, instanceId, policyId, connectedAt }>
const connectedInstances = new Map<string, Map<string, InstanceInfo>>();

// Track HTTP-only SDK instances (no WebSocket, identified by heartbeats)
// teamId -> Map<instanceId, { instanceId, policyId, status, firstSeen, lastHeartbeat }>
const httpInstances = new Map<string, Map<string, HttpInstanceInfo>>();

// TTL for HTTP agents (remove if no heartbeat for this duration)
const HTTP_AGENT_TTL_MS = 60000; // 60 seconds

// Store the control emitter globally for agent status broadcasts
let globalControlEmitter: ControlEmitterInner | null = null;

// Track which teams have active subscriptions for agent status (team -> subscriber count)
const teamSubscriberCounts = new Map<string, number>();

// Helper to get teams with active subscribers
function getTeamsWithSubscribers(): string[] {
  return Array.from(teamSubscriberCounts.entries())
    .filter(([, count]) => count > 0)
    .map(([teamId]) => teamId);
}

// Interval for periodic agent status broadcasts
let agentStatusInterval: ReturnType<typeof setInterval> | null = null;

/**
 * Register or update an HTTP-only agent from heartbeat
 * Called from control_service when processing heartbeat events
 */
function registerHttpAgent(
  teamId: string | number,
  instanceId: string,
  policyId: string | null,
  agentName: string | null,
  status: string
): void {
  const teamKey = String(teamId);

  // Check if this instance is already connected via WebSocket
  const wsInstances = connectedInstances.get(teamKey);
  if (wsInstances) {
    for (const info of wsInstances.values()) {
      if (info.instanceId === instanceId) {
        // Already tracked via WebSocket, just update heartbeat there
        info.lastHeartbeat = new Date();
        return;
      }
    }
  }

  // Track as HTTP-only agent
  if (!httpInstances.has(teamKey)) {
    httpInstances.set(teamKey, new Map());
  }

  const existing = httpInstances.get(teamKey)!.get(instanceId);
  if (existing) {
    // Update existing
    existing.lastHeartbeat = new Date();
    existing.status = status;
    existing.policyId = policyId;
    existing.agentName = agentName;
  } else {
    // New HTTP agent
    httpInstances.get(teamKey)!.set(instanceId, {
      instanceId,
      policyId,
      agentName,
      status,
      firstSeen: new Date(),
      lastHeartbeat: new Date(),
    });
    console.log(
      `[Aden Control] HTTP agent registered: ${agentName || instanceId.slice(0, 8)}... (team: ${teamKey})`
    );

    // Broadcast updated agent status to subscribers
    broadcastAgentStatus(teamKey);
  }
}

/**
 * Clean up stale HTTP agents that haven't sent heartbeats
 */
function cleanupStaleHttpAgents(): void {
  const now = Date.now();
  const teamsWithRemovedAgents: string[] = [];

  for (const [teamId, instances] of httpInstances) {
    let removed = false;
    for (const [instanceId, info] of instances) {
      if (now - info.lastHeartbeat.getTime() > HTTP_AGENT_TTL_MS) {
        instances.delete(instanceId);
        removed = true;
        console.log(
          `[Aden Control] HTTP agent expired: ${instanceId.slice(0, 8)}... (team: ${teamId})`
        );
      }
    }

    if (removed) {
      teamsWithRemovedAgents.push(teamId);
    }

    // Clean up empty team maps
    if (instances.size === 0) {
      httpInstances.delete(teamId);
    }
  }

  // Broadcast updated status to teams that had agents removed
  for (const teamId of teamsWithRemovedAgents) {
    broadcastAgentStatus(teamId);
  }
}

// Run cleanup every 30 seconds
setInterval(cleanupStaleHttpAgents, 30000);

/**
 * Get agent status for a team
 */
function getAgentStatusForTeam(teamId: string): {
  type: string;
  active: boolean;
  count: number;
  instances: Array<{
    instance_id: string;
    policy_id: string | null;
    agent_name: string | null;
    connected_at: string;
    last_heartbeat: string;
    connection_type: "websocket" | "http";
    status?: string;
  }>;
  timestamp: string;
} {
  const wsInstances = connectedInstances.get(teamId);
  const httpInsts = httpInstances.get(teamId);

  const instances: Array<{
    instance_id: string;
    policy_id: string | null;
    agent_name: string | null;
    connected_at: string;
    last_heartbeat: string;
    connection_type: "websocket" | "http";
    status?: string;
  }> = [];

  // Add WebSocket-connected instances
  if (wsInstances) {
    for (const info of wsInstances.values()) {
      instances.push({
        instance_id: info.instanceId,
        policy_id: info.policyId,
        agent_name: null,
        connected_at: info.connectedAt.toISOString(),
        last_heartbeat: info.lastHeartbeat.toISOString(),
        connection_type: "websocket",
      });
    }
  }

  // Add HTTP-only instances
  if (httpInsts) {
    for (const info of httpInsts.values()) {
      instances.push({
        instance_id: info.instanceId,
        policy_id: info.policyId,
        agent_name: info.agentName,
        connected_at: info.firstSeen.toISOString(),
        last_heartbeat: info.lastHeartbeat.toISOString(),
        connection_type: "http",
        status: info.status,
      });
    }
  }

  const count = instances.length;

  return {
    type: "agent-status",
    active: count > 0,
    count,
    instances,
    timestamp: new Date().toISOString(),
  };
}

/**
 * Broadcast agent status to all subscribed clients for a team
 */
function broadcastAgentStatus(teamId: string): void {
  if (!globalControlEmitter) return;

  const status = getAgentStatusForTeam(teamId);
  const room = `team:${teamId}:llm-events`;
  globalControlEmitter.to(room).emit("message", status);
}

/**
 * Broadcast agent status to all teams with subscribers
 */
function broadcastAgentStatusToAllTeams(): void {
  const teams = getTeamsWithSubscribers();
  for (const teamId of teams) {
    broadcastAgentStatus(teamId);
  }
}

interface AdenSocket extends Socket {
  user?: Record<string, unknown>;
  teamId?: string;
  policyId?: string | null;
  sdkInstanceId?: string;
}

interface RedisEmitter {
  of: (namespace: string) => ControlEmitterInner;
}

interface ControlEmitterInner {
  to: (room: string) => { emit: (event: string, payload: unknown) => void };
  emit: (event: string, payload: unknown) => void;
}

interface MessageData {
  event_type?: string;
  [key: string]: unknown;
}

interface ControlEmitter {
  emitPolicyUpdate: (teamId: string | number, policyId: string | null, policy: unknown) => void;
  emitCommand: (teamId: string | number, command: { action: string; [key: string]: unknown }) => void;
  emitAlert: (teamId: string | number, policyId: string | null, alert: unknown) => void;
  emitToInstance: (teamId: string | number, instanceId: string, message: unknown) => boolean;
  getConnectedCount: (teamId: string | number) => number;
  getConnectedInstances: (teamId: string | number) => Array<{
    instance_id: string;
    policy_id: string | null;
    agent_name: string | null;
    connected_at: string;
    last_heartbeat: string;
    connection_type: "websocket" | "http";
    status?: string;
  }>;
  getTotalConnectedCount: () => number;
}

/**
 * Initialize Aden Control WebSocket namespace
 * @param io - Socket.IO server instance
 * @param rootEmitter - Redis emitter for cross-instance communication
 * @returns Control emitter for sending updates
 */
function initAdenControlSockets(io: Server, rootEmitter: RedisEmitter): ControlEmitter {
  // Create namespace for control plane
  const controlNamespace: Namespace = io.of("/v1/control/ws");

  // Create emitter for this namespace
  const controlEmitter: ControlEmitterInner = rootEmitter.of("/v1/control/ws");

  // Store globally for agent status broadcasts
  globalControlEmitter = controlEmitter;

  // Start periodic agent status broadcast (every 2 seconds)
  if (agentStatusInterval) {
    clearInterval(agentStatusInterval);
  }
  agentStatusInterval = setInterval(broadcastAgentStatusToAllTeams, 2000);

  // Initialize LLM event batcher with emitter for real-time streaming
  llmEventBatcher.setEmitter(controlEmitter as unknown as { to: (room: string) => { emit: (event: string, payload: unknown) => void } });

  // Authentication middleware - verify JWT token
  controlNamespace.use(async (socket: AdenSocket, next: (err?: Error) => void) => {
    try {
      let token: string | undefined =
        socket.handshake.auth?.token ||
        socket.handshake.headers?.authorization ||
        (socket.handshake.query?.token as string | undefined);

      if (!token) {
        console.error("[Aden Control WS] No authorization provided");
        return next(new Error("Authentication required"));
      }

      // Extract token (support "Bearer <token>" and "jwt <token>" formats)
      if (token.startsWith("Bearer ")) {
        token = token.slice(7);
      } else if (token.startsWith("jwt ")) {
        token = token.slice(4);
      }

      if (!token) {
        return next(new Error("Invalid token"));
      }

      // Verify JWT token using user's salt
      if (!userDbService) {
        console.error("[Aden Control WS] userDbService not initialized");
        return next(new Error("Server configuration error"));
      }
      const salt = await userDbService.findSaltByToken(token);
      if (!salt) {
        console.error("[Aden Control WS] No salt found for token");
        return next(new Error("Invalid token"));
      }
      // Token is signed with jwtSecret + salt
      const verifySecret = jwtSecret ? jwtSecret + salt : salt;
      const decoded = await new Promise<Record<string, unknown>>((resolve, reject) => {
        jwt.verify(token!, verifySecret, (err, decoded) => {
          if (err) reject(err);
          else resolve(decoded as Record<string, unknown>);
        });
      });

      // Store user info on socket
      socket.user = decoded;
      socket.teamId = decoded.current_team_id as string;
      socket.policyId =
        (socket.handshake.headers?.["x-policy-id"] as string) ||
        (socket.handshake.query?.policy_id as string) ||
        null;
      socket.sdkInstanceId =
        (socket.handshake.headers?.["x-sdk-instance-id"] as string) ||
        (socket.handshake.query?.instance_id as string) ||
        socket.id;

      console.log(
        `[Aden Control WS] SDK connecting: ${socket.sdkInstanceId!.slice(0, 8)}... (team: ${socket.teamId})`
      );

      next();
    } catch (error) {
      console.error("[Aden Control WS] Auth error:", (error as Error).message);
      next(new Error("Authentication failed"));
    }
  });

  // Handle connections
  controlNamespace.on("connection", async (socket: AdenSocket) => {
    const { teamId, policyId, sdkInstanceId } = socket;

    console.log(
      `[Aden Control WS] SDK connected: ${sdkInstanceId!.slice(0, 8)}... (socket: ${socket.id}, team: ${teamId})`
    );

    // Track this instance by team
    if (!connectedInstances.has(teamId!)) {
      connectedInstances.set(teamId!, new Map());
    }
    connectedInstances.get(teamId!)!.set(socket.id, {
      socket,
      instanceId: sdkInstanceId!,
      policyId: policyId || null,
      connectedAt: new Date(),
      lastHeartbeat: new Date(),
    });

    // Join room for this team (for policy broadcasts)
    socket.join(`team:${teamId}`);
    // Also join policy-specific room if policy specified
    if (policyId) {
      socket.join(`team:${teamId}:policy:${policyId}`);
    }

    // Send current policy immediately
    try {
      const policy = await controlService.getPolicy(teamId!, policyId || null);
      socket.emit("message", {
        type: "policy",
        policy,
      });
    } catch (error) {
      console.error("[Aden Control WS] Error sending initial policy:", error);
    }

    // Handle incoming messages from SDK
    socket.on("message", async (data: MessageData | string) => {
      try {
        await handleSdkMessage(socket, data);
      } catch (error) {
        console.error("[Aden Control WS] Error handling message:", error);
        socket.emit("message", {
          type: "error",
          error: (error as Error).message,
        });
      }
    });

    // Handle direct event submission (alternative to message)
    socket.on("event", async (event: Record<string, unknown>) => {
      try {
        await controlService.processEvents(teamId!, policyId || null, [event as any]);
      } catch (error) {
        console.error("[Aden Control WS] Error processing event:", error);
      }
    });

    // Handle disconnection
    socket.on("disconnect", (reason: string) => {
      console.log(
        `[Aden Control WS] SDK disconnected: ${sdkInstanceId!.slice(0, 8)}... (reason: ${reason})`
      );

      // Remove from tracking
      const instances = connectedInstances.get(teamId!);
      if (instances) {
        instances.delete(socket.id);
        if (instances.size === 0) {
          connectedInstances.delete(teamId!);
        }
      }
    });

    // Handle errors
    socket.on("error", (error: Error) => {
      console.error(
        `[Aden Control WS] Socket error for ${sdkInstanceId!.slice(0, 8)}...:`,
        error.message
      );
    });

    // Handle LLM events stream subscription (for dashboard real-time updates)
    socket.on("subscribe-llm-events", () => {
      const room = `team:${teamId}:llm-events`;
      socket.join(room);
      console.log(`[Aden Control WS] Socket ${socket.id} subscribed to ${room}`);

      // Track subscriber count for this team
      const currentCount = teamSubscriberCounts.get(teamId!) || 0;
      teamSubscriberCounts.set(teamId!, currentCount + 1);

      socket.emit("message", {
        type: "subscribed",
        stream: "llm-events",
        teamId: teamId,
      });

      // Send initial agent status
      const status = getAgentStatusForTeam(teamId!);
      socket.emit("message", status);
    });

    socket.on("unsubscribe-llm-events", () => {
      const room = `team:${teamId}:llm-events`;
      socket.leave(room);
      console.log(`[Aden Control WS] Socket ${socket.id} unsubscribed from ${room}`);

      // Decrement subscriber count
      const currentCount = teamSubscriberCounts.get(teamId!) || 0;
      if (currentCount > 0) {
        teamSubscriberCounts.set(teamId!, currentCount - 1);
      }

      socket.emit("message", {
        type: "unsubscribed",
        stream: "llm-events",
        teamId: teamId,
      });
    });
  });

  /**
   * Handle incoming message from SDK
   */
  async function handleSdkMessage(socket: AdenSocket, data: MessageData | string): Promise<void> {
    // Parse if string
    let parsedData: MessageData;
    if (typeof data === "string") {
      parsedData = JSON.parse(data);
    } else {
      parsedData = data;
    }

    const { teamId, policyId, sdkInstanceId } = socket;

    // Route based on event type
    switch (parsedData.event_type) {
      case "metric":
      case "control":
      case "heartbeat":
      case "error":
        // Process as event
        await controlService.processEvents(teamId!, policyId || null, [parsedData as any]);

        // Update last heartbeat time
        if (parsedData.event_type === "heartbeat") {
          const instances = connectedInstances.get(teamId!);
          const instance = instances?.get(socket.id);
          if (instance) {
            instance.lastHeartbeat = new Date();
          }
        }
        break;

      case "get_policy": {
        // Request for current policy
        const policy = await controlService.getPolicy(teamId!, policyId || null);
        socket.emit("message", {
          type: "policy",
          policy,
        });
        break;
      }

      default:
        console.warn(
          `[Aden Control WS] Unknown event type from ${sdkInstanceId!.slice(0, 8)}...: ${parsedData.event_type}`
        );
    }
  }

  /**
   * Create emitter object for external use
   */
  const emitter: ControlEmitter = {
    /**
     * Emit policy update to all SDK instances for a team/policy
     * @param teamId - The team ID
     * @param policyId - The policy ID (optional, broadcasts to all team instances if not specified)
     * @param policy - The policy object
     */
    emitPolicyUpdate(teamId: string | number, policyId: string | null, policy: unknown): void {
      console.log(`[Aden Control WS] Broadcasting policy update for team ${teamId}`);

      // If policyId specified, emit only to instances using that policy
      if (policyId) {
        controlEmitter.to(`team:${teamId}:policy:${policyId}`).emit("message", {
          type: "policy",
          policy,
        });
      } else {
        // Broadcast to all team instances
        controlEmitter.to(`team:${teamId}`).emit("message", {
          type: "policy",
          policy,
        });
      }
    },

    /**
     * Emit a command to all SDK instances for a team
     */
    emitCommand(teamId: string | number, command: { action: string; [key: string]: unknown }): void {
      console.log(`[Aden Control WS] Broadcasting command: ${command.action}`);

      controlEmitter.to(`team:${teamId}`).emit("message", {
        type: "command",
        command,
      });
    },

    /**
     * Emit alert to team instances
     */
    emitAlert(teamId: string | number, policyId: string | null, alert: unknown): void {
      console.log(`[Aden Control WS] Broadcasting alert for team ${teamId}`);

      const room = policyId ? `team:${teamId}:policy:${policyId}` : `team:${teamId}`;
      controlEmitter.to(room).emit("message", {
        type: "alert",
        alert,
      });
    },

    /**
     * Emit to a specific SDK instance
     */
    emitToInstance(teamId: string | number, instanceId: string, message: unknown): boolean {
      const instances = connectedInstances.get(String(teamId));
      if (!instances) return false;

      for (const [, info] of instances) {
        if (info.instanceId === instanceId) {
          info.socket.emit("message", message);
          return true;
        }
      }
      return false;
    },

    /**
     * Get connected instance count for a team (WebSocket + HTTP)
     */
    getConnectedCount(teamId: string | number): number {
      const teamKey = String(teamId);
      const wsCount = connectedInstances.get(teamKey)?.size || 0;
      const httpCount = httpInstances.get(teamKey)?.size || 0;
      return wsCount + httpCount;
    },

    /**
     * Get all connected instances info (for dashboard)
     * Includes both WebSocket and HTTP-only agents
     */
    getConnectedInstances(teamId: string | number): Array<{
      instance_id: string;
      policy_id: string | null;
      agent_name: string | null;
      connected_at: string;
      last_heartbeat: string;
      connection_type: "websocket" | "http";
      status?: string;
    }> {
      const teamKey = String(teamId);
      const results: Array<{
        instance_id: string;
        policy_id: string | null;
        agent_name: string | null;
        connected_at: string;
        last_heartbeat: string;
        connection_type: "websocket" | "http";
        status?: string;
      }> = [];

      // Add WebSocket-connected instances
      const wsInstances = connectedInstances.get(teamKey);
      if (wsInstances) {
        for (const info of wsInstances.values()) {
          results.push({
            instance_id: info.instanceId,
            policy_id: info.policyId,
            agent_name: null, // WebSocket connections don't have agent_name yet
            connected_at: info.connectedAt.toISOString(),
            last_heartbeat: info.lastHeartbeat.toISOString(),
            connection_type: "websocket",
          });
        }
      }

      // Add HTTP-only instances
      const httpInsts = httpInstances.get(teamKey);
      if (httpInsts) {
        for (const info of httpInsts.values()) {
          results.push({
            instance_id: info.instanceId,
            policy_id: info.policyId,
            agent_name: info.agentName,
            connected_at: info.firstSeen.toISOString(),
            last_heartbeat: info.lastHeartbeat.toISOString(),
            connection_type: "http",
            status: info.status,
          });
        }
      }

      return results;
    },

    /**
     * Get total connected SDK count across all teams (WebSocket + HTTP)
     */
    getTotalConnectedCount(): number {
      let total = 0;
      for (const instances of connectedInstances.values()) {
        total += instances.size;
      }
      for (const instances of httpInstances.values()) {
        total += instances.size;
      }
      return total;
    },
  };

  // Note: Emitter is returned instead of stored globally
  // Use app.locals.controlEmitter to access in routes

  console.log("[Aden Control WS] WebSocket namespace initialized at /v1/control/ws");

  return emitter;
}

export default initAdenControlSockets;
export { setUserDbService, registerHttpAgent };
