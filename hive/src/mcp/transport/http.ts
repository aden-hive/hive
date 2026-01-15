/**
 * HTTP/SSE Transport for Aden Hive MCP Server
 *
 * Provides HTTP-based transport for autonomous LLM agents:
 * - GET /mcp - SSE stream for server-to-client messages
 * - POST /mcp/message - Client-to-server messages
 */
import express, { Request, Response, Router } from "express";
import passport from "passport";
import { SSEServerTransport } from "@modelcontextprotocol/sdk/server/sse.js";
import { createHiveMcpServer, type HiveMcpServerOptions } from "../server";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";

interface AuthenticatedRequest extends Request {
  user?: {
    id: string;
    current_team_id: string;
  };
}

interface McpSession {
  server: McpServer;
  transport: SSEServerTransport;
  teamId: string;
  userId: string;
  createdAt: Date;
}

// Active MCP sessions by session ID
const sessions = new Map<string, McpSession>();

/**
 * Create MCP HTTP router
 */
export function createMcpRouter(
  getControlEmitter?: HiveMcpServerOptions["getControlEmitter"]
): Router {
  const router = express.Router();

  // All MCP routes require authentication
  const authMiddleware = passport.authenticate("jwt", { session: false });

  /**
   * GET /mcp
   * SSE endpoint - establishes persistent connection for server-to-client messages
   */
  router.get(
    "/",
    authMiddleware,
    async (req: AuthenticatedRequest, res: Response) => {
      const teamId = req.user?.current_team_id;
      const userId = req.user?.id;

      if (!teamId) {
        res.status(401).json({ error: "Team ID required" });
        return;
      }

      // Set custom headers (SSE headers are set by the transport)
      res.setHeader("X-Accel-Buffering", "no");

      // Create MCP server for this session
      const server = createHiveMcpServer({
        context: {
          teamId,
          userId,
        },
        getControlEmitter,
      });

      // Create SSE transport - it generates its own sessionId internally
      const transport = new SSEServerTransport("/mcp/message", res);

      // Get the SDK's session ID (used in query params for POST requests)
      const sdkSessionId = transport.sessionId;

      console.log(`[MCP] New SSE connection: session=${sdkSessionId}, team=${teamId}`);

      // Store session by the SDK's session ID
      sessions.set(sdkSessionId, {
        server,
        transport,
        teamId,
        userId: userId || "unknown",
        createdAt: new Date(),
      });

      // Connect server to transport
      await server.connect(transport);

      // Handle client disconnect
      req.on("close", () => {
        console.log(`[MCP] SSE connection closed: session=${sdkSessionId}`);
        sessions.delete(sdkSessionId);
        server.close();
      });
    }
  );

  /**
   * POST /mcp/message
   * Receives messages from client
   */
  // Note: Do NOT use express.json() here - handlePostMessage reads the raw body stream
  router.post(
    "/message",
    authMiddleware,
    async (req: AuthenticatedRequest, res: Response) => {
      // SDK passes session ID as query parameter: /mcp/message?sessionId=xxx
      const sessionId = req.query.sessionId as string;

      if (!sessionId) {
        res.status(400).json({ error: "sessionId query parameter required" });
        return;
      }

      const session = sessions.get(sessionId);

      if (!session) {
        res.status(404).json({
          error: "Session not found",
          hint: "Establish SSE connection first via GET /mcp",
        });
        return;
      }

      // Verify team ID matches
      if (session.teamId !== req.user?.current_team_id) {
        res.status(403).json({ error: "Session team mismatch" });
        return;
      }

      try {
        // Handle the message through the transport
        await session.transport.handlePostMessage(req, res);
      } catch (error) {
        console.error(`[MCP] Error handling message:`, error);
        res.status(500).json({
          error: "Failed to process message",
          details: error instanceof Error ? error.message : "Unknown error",
        });
      }
    }
  );

  /**
   * GET /mcp/sessions
   * List active MCP sessions (admin/debug endpoint)
   */
  router.get(
    "/sessions",
    authMiddleware,
    (req: AuthenticatedRequest, res: Response) => {
      const teamId = req.user?.current_team_id;

      // Only show sessions for the requesting team
      const teamSessions = Array.from(sessions.entries())
        .filter(([, session]) => session.teamId === teamId)
        .map(([id, session]) => ({
          session_id: id,
          team_id: session.teamId,
          user_id: session.userId,
          created_at: session.createdAt.toISOString(),
          age_seconds: Math.round(
            (Date.now() - session.createdAt.getTime()) / 1000
          ),
        }));

      res.json({
        count: teamSessions.length,
        sessions: teamSessions,
      });
    }
  );

  /**
   * DELETE /mcp/sessions/:sessionId
   * Close a specific MCP session
   */
  router.delete(
    "/sessions/:sessionId",
    authMiddleware,
    (req: AuthenticatedRequest, res: Response) => {
      const { sessionId } = req.params;
      const teamId = req.user?.current_team_id;

      const session = sessions.get(sessionId);

      if (!session) {
        res.status(404).json({ error: "Session not found" });
        return;
      }

      // Verify team ID matches
      if (session.teamId !== teamId) {
        res.status(403).json({ error: "Cannot close session from another team" });
        return;
      }

      // Close the session
      session.server.close();
      sessions.delete(sessionId);

      res.json({
        success: true,
        message: `Session ${sessionId} closed`,
      });
    }
  );

  /**
   * GET /mcp/health
   * Health check endpoint
   */
  router.get("/health", (_req: Request, res: Response) => {
    res.json({
      status: "healthy",
      active_sessions: sessions.size,
      timestamp: new Date().toISOString(),
    });
  });

  return router;
}

/**
 * Get count of active MCP sessions
 */
export function getActiveMcpSessionCount(): number {
  return sessions.size;
}

/**
 * Get active sessions for a specific team
 */
export function getTeamMcpSessions(teamId: string): McpSession[] {
  return Array.from(sessions.values()).filter((s) => s.teamId === teamId);
}
