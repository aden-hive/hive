/**
 * Aden Hive - DevTool Backend Entry Point
 *
 * LLM observability and control plane service.
 */

import "dotenv/config";

import http from "http";
import { MongoClient } from "mongodb";
import app from "./app";
import config from "./config";
import { initializeSockets, setUserDbService } from "./sockets/control.socket";

const PORT = process.env.PORT || 4000;

// Declare globals for MongoDB (used by services)
// eslint-disable-next-line no-var
declare global {
  // eslint-disable-next-line no-var
  var _ACHO_MG_DB: MongoClient;
  // eslint-disable-next-line no-var
  var _ACHO_MDB_CONFIG: { ERP_DBNAME: string; DBNAME: string };
  // eslint-disable-next-line no-var
  var _ACHO_MDB_COLLECTIONS: {
    ADEN_CONTROL_POLICIES: string;
    ADEN_CONTROL_CONTENT: string;
    LLM_PRICING: string;
  };
}

/**
 * Initialize MongoDB connection
 */
async function initMongoDB(): Promise<void> {
  if (!config.mongodb.url) {
    console.warn(
      "[MongoDB] No MONGODB_URL configured, skipping MongoDB initialization"
    );
    return;
  }

  try {
    const client = new MongoClient(config.mongodb.url);
    await client.connect();

    // Set global MongoDB client and config
    global._ACHO_MG_DB = client;
    global._ACHO_MDB_CONFIG = {
      ERP_DBNAME: config.mongodb.erpDbName,
      DBNAME: config.mongodb.dbName,
    };
    global._ACHO_MDB_COLLECTIONS = {
      ADEN_CONTROL_POLICIES: "aden_control_policies",
      ADEN_CONTROL_CONTENT: "aden_control_content",
      LLM_PRICING: "llm_pricing",
    };

    console.log("[MongoDB] Connected successfully");
  } catch (error) {
    console.error("[MongoDB] Connection error:", error);
    throw error;
  }
}

// Create HTTP server
const server = http.createServer(app);

/**
 * Start the server
 */
async function start(): Promise<void> {
  // Initialize MongoDB
  await initMongoDB();

  // Pass userDbService to socket layer for JWT verification
  if (app.locals.userDbService) {
    setUserDbService(app.locals.userDbService, config.jwt.secret);
  }

  // Initialize WebSockets
  const { controlEmitter } = await initializeSockets(server);

  // Make control emitter available for policy updates
  app.locals.controlEmitter = controlEmitter;
  console.log("[Aden Hive] WebSocket initialized");

  // Start server
  server.listen(PORT, () => {
    console.log(`[Aden Hive] Server running on port ${PORT}`);
    console.log(
      `[Aden Hive] Environment: ${process.env.NODE_ENV || "development"}`
    );
  });
}

// Start the application
start().catch((error) => {
  console.error("[Aden Hive] Failed to start:", error);
  process.exit(1);
});

// Graceful shutdown
process.on("SIGTERM", () => {
  console.log("[Aden Hive] SIGTERM received, shutting down gracefully");
  server.close(() => {
    console.log("[Aden Hive] Server closed");
    process.exit(0);
  });
});

process.on("SIGINT", () => {
  console.log("[Aden Hive] SIGINT received, shutting down gracefully");
  server.close(() => {
    console.log("[Aden Hive] Server closed");
    process.exit(0);
  });
});

export default server;
