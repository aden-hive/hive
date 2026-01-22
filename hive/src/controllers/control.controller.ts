/**
 * Aden Control Controller
 *
 * HTTP endpoints for Aden SDK control plane:
 * - GET  /v1/control/policy  - Get current policy
 * - POST /v1/control/events  - Submit events (batch)
 * - POST /v1/control/content - Store large content items
 * - GET  /v1/control/events  - Get events (dashboard)
 * - PUT  /v1/control/policy  - Update policy (dashboard)
 */

import express, { Request, Response, NextFunction } from "express";
import createError from "http-errors";
import passport from "passport";
import { getErrorMessage } from "../utils/error";

import controlService from "../services/control/control_service";
import pricingService from "../services/tsdb/pricing_service";
import * as tsdbService from "../services/tsdb/tsdb_service";
import { getTeamPool, buildSchemaName } from "../services/tsdb/team_context";

const router = express.Router();

// Passport is initialized in app.js

interface UserPayload {
  id: string;
  current_team_id: string;
  [key: string]: unknown;
}

interface UserContext {
  user_id: string;
  team_id: string;
}

interface AuthenticatedRequest extends Request {
  user?: UserPayload;
}

interface BudgetAlert {
  threshold: number;
  enabled: boolean;
}

interface BudgetNotifications {
  inApp: boolean;
  email: boolean;
  emailRecipients: string[];
  webhook: boolean;
}

interface BudgetRule {
  id: string;
  name: string;
  type: string;
  tags?: string[];
  limit: number;
  spent: number;
  limitAction: string;
  degradeToModel?: string;
  degradeToProvider?: string;
  alerts: BudgetAlert[];
  notifications: BudgetNotifications;
}

interface ValidationContext {
  agent?: string;
  tenant_id?: string;
  customer_id?: string;
  feature?: string;
  tags?: string[];
}

declare const global: {
  _ADEN_CONTROL_EMITTER?: {
    emitPolicyUpdate: (
      teamId: string,
      policyId: string | null,
      policy: unknown
    ) => void;
  };
};

/**
 * Extract user context from JWT payload for audit/scoping
 * @param req - Express request with req.user from passport
 * @returns User context { user_id, team_id }
 */
function getUserContext(req: AuthenticatedRequest): UserContext | null {
  if (!req.user) return null;
  return {
    user_id: req.user.id,
    team_id: req.user.current_team_id,
  };
}

/**
 * Get policy ID from request (header or query param)
 * Returns null if not specified (will use default policy)
 */
function getPolicyId(req: Request): string | null {
  return (
    (req.headers["x-policy-id"] as string) ||
    (req.query.policy_id as string) ||
    null
  );
}

/**
 * Resolve policy ID - handles "default" as special value
 * Returns null for "default" which tells service to use team's default policy
 */
function resolvePolicyId(policyId: string): string | null {
  if (!policyId || policyId === "default") {
    return null;
  }
  return policyId;
}

// =============================================================================
// SDK Endpoints (used by Aden SDK)
// =============================================================================

/**
 * GET /v1/control/policy
 * Get the current control policy for the SDK
 * Optional X-Policy-ID header to specify policy (uses default if not specified)
 */
router.get(
  "/policy",
  passport.authenticate("jwt", { session: false }),
  async (req: AuthenticatedRequest, res: Response, next: NextFunction) => {
    try {
      const userContext = getUserContext(req);
      if (!userContext?.team_id) {
        return next(createError(400, "Team context required"));
      }

      const policyId = getPolicyId(req);
      const policy = await controlService.getPolicy(
        userContext.team_id,
        policyId
      );
      res.json(policy);
    } catch (error: unknown) {
      console.error("[Aden Control] Error getting policy:", getErrorMessage(error));
      next(createError(500, "Failed to get policy"));
    }
  }
);

/**
 * POST /v1/control/events
 * Submit events from the SDK (batch)
 * Optional X-Policy-ID header to specify policy (uses default if not specified)
 */
router.post(
  "/events",
  passport.authenticate("jwt", { session: false }),
  async (req: AuthenticatedRequest, res: Response, next: NextFunction) => {
    try {
      const userContext = getUserContext(req);
      if (!userContext?.team_id) {
        return next(createError(400, "Team context required"));
      }

      const { events } = req.body;

      if (!events || !Array.isArray(events)) {
        return next(createError(400, "events array required"));
      }

      const policyId = getPolicyId(req);
      await controlService.processEvents(
        userContext.team_id,
        policyId,
        events,
        userContext
      );

      res.json({ success: true, processed: events.length });
    } catch (error: unknown) {
      console.error("[Aden Control] Error processing events:", getErrorMessage(error));
      next(createError(500, "Failed to process events"));
    }
  }
);

/**
 * POST /v1/control/content
 * Store large content items from the SDK (Layer 0 content capture)
 * Used for content that exceeds max_content_bytes threshold
 *
 * Body: { items: Array<{ content_id, content_hash, content, byte_size }> }
 */
router.post(
  "/content",
  passport.authenticate("jwt", { session: false }),
  async (req: AuthenticatedRequest, res: Response, next: NextFunction) => {
    try {
      console.log("[Aden Control] Received content storage request");
      const userContext = getUserContext(req);
      if (!userContext?.team_id) {
        return next(createError(400, "Team context required"));
      }

      const { items } = req.body;

      if (!items || !Array.isArray(items)) {
        return next(createError(400, "items array required"));
      }

      // Validate each item has required fields
      for (let i = 0; i < items.length; i++) {
        const item = items[i];
        if (!item.content_id || typeof item.content_id !== "string") {
          return next(
            createError(400, `items[${i}].content_id (string) is required`)
          );
        }
        if (!item.content_hash || typeof item.content_hash !== "string") {
          return next(
            createError(400, `items[${i}].content_hash (string) is required`)
          );
        }
        if (item.content === undefined || item.content === null) {
          return next(createError(400, `items[${i}].content is required`));
        }
        if (typeof item.byte_size !== "number" || item.byte_size < 0) {
          return next(
            createError(
              400,
              `items[${i}].byte_size must be a non-negative number`
            )
          );
        }
      }

      const result = await controlService.storeContent(
        userContext.team_id,
        items
      );

      res.json({ success: true, stored: result.stored });
    } catch (error: unknown) {
      console.error("[Aden Control] Error storing content:", getErrorMessage(error));
      next(createError(500, "Failed to store content"));
    }
  }
);

/**
 * GET /v1/control/content/:contentId
 * Retrieve content by ID
 */
router.get(
  "/content/:contentId",
  passport.authenticate("jwt", { session: false }),
  async (req: AuthenticatedRequest, res: Response, next: NextFunction) => {
    try {
      const userContext = getUserContext(req);
      if (!userContext?.team_id) {
        return next(createError(400, "Team context required"));
      }

      const { contentId } = req.params;
      const content = await controlService.getContent(
        userContext.team_id,
        contentId
      );

      if (!content) {
        return next(createError(404, "Content not found"));
      }

      res.json(content);
    } catch (error: unknown) {
      console.error("[Aden Control] Error getting content:", getErrorMessage(error));
      next(createError(500, "Failed to get content"));
    }
  }
);

// =============================================================================
// TSDB Content Retrieval Endpoints (warm/cold storage)
// =============================================================================

/**
 * GET /v1/control/events/:traceId/:callSequence/content
 * Get all content for a specific event from warm/cold storage
 * Returns content references with full content from cold store
 */
router.get(
  "/events/:traceId/:callSequence/content",
  passport.authenticate("jwt", { session: false }),
  async (req: AuthenticatedRequest, res: Response, next: NextFunction) => {
    try {
      const userContext = getUserContext(req);
      if (!userContext?.team_id) {
        return next(createError(400, "Team context required"));
      }

      const { traceId, callSequence } = req.params;
      const callSeq = parseInt(callSequence);

      if (!traceId || isNaN(callSeq)) {
        return next(createError(400, "Valid traceId and callSequence required"));
      }

      // Get team pool and set schema
      const pool = await getTeamPool(userContext.team_id);
      const schema = buildSchemaName(userContext.team_id);
      const client = await pool.connect();

      try {
        await client.query(`SET search_path TO ${schema}, public`);
        await tsdbService.ensureSchema(client);

        const content = await tsdbService.getEventContent(
          userContext.team_id,
          traceId,
          callSeq,
          client
        );

        res.json({
          trace_id: traceId,
          call_sequence: callSeq,
          content_items: content,
          count: content.length,
        });
      } finally {
        client.release();
      }
    } catch (error: unknown) {
      console.error("[Aden Control] Error getting event content:", getErrorMessage(error));
      next(createError(500, "Failed to get event content"));
    }
  }
);

/**
 * GET /v1/control/content/hash/:contentHash
 * Get content from cold storage by hash
 * Useful for fetching deduplicated content directly
 */
router.get(
  "/content/hash/:contentHash",
  passport.authenticate("jwt", { session: false }),
  async (req: AuthenticatedRequest, res: Response, next: NextFunction) => {
    try {
      const userContext = getUserContext(req);
      if (!userContext?.team_id) {
        return next(createError(400, "Team context required"));
      }

      const { contentHash } = req.params;

      if (!contentHash || contentHash.length !== 64) {
        return next(createError(400, "Valid SHA-256 content hash required"));
      }

      // Get team pool and set schema
      const pool = await getTeamPool(userContext.team_id);
      const schema = buildSchemaName(userContext.team_id);
      const client = await pool.connect();

      try {
        await client.query(`SET search_path TO ${schema}, public`);
        await tsdbService.ensureSchema(client);

        const content = await tsdbService.getContentByHash(
          userContext.team_id,
          contentHash,
          client
        );

        if (!content) {
          return next(createError(404, "Content not found"));
        }

        res.json({
          content_hash: contentHash,
          content,
          byte_size: Buffer.byteLength(content, "utf8"),
        });
      } finally {
        client.release();
      }
    } catch (error: unknown) {
      console.error("[Aden Control] Error getting content by hash:", getErrorMessage(error));
      next(createError(500, "Failed to get content"));
    }
  }
);

// =============================================================================
// Dashboard Endpoints (used by Aden Dashboard)
// =============================================================================

/**
 * GET /v1/control/events
 * Get events for the dashboard (queries TSDB)
 * Query params: limit, offset, start_date, end_date, policy_id
 */
router.get(
  "/events",
  passport.authenticate("jwt", { session: false }),
  async (req: AuthenticatedRequest, res: Response, next: NextFunction) => {
    try {
      const { limit, offset, start_date, end_date, policy_id } = req.query;
      const userContext = getUserContext(req);

      if (!userContext?.team_id) {
        return next(createError(400, "Team context required"));
      }

      const events = await controlService.getEvents(
        userContext.team_id,
        (policy_id as string) || null,
        {
          limit: parseInt(limit as string) || 100,
          offset: parseInt(offset as string) || 0,
          start_date: start_date as string | undefined,
          end_date: end_date as string | undefined,
        }
      );

      res.json({ events, count: events.length });
    } catch (error: unknown) {
      console.error("[Aden Control] Error getting events:", getErrorMessage(error));
      next(createError(500, "Failed to get events"));
    }
  }
);

/**
 * PUT /v1/control/policies/:policyId
 * Update the control policy (from dashboard)
 * Use "default" as policyId to update the team's default policy
 */
router.put(
  "/policies/:policyId",
  passport.authenticate("jwt", { session: false }),
  async (req: AuthenticatedRequest, res: Response, next: NextFunction) => {
    try {
      const policyId = resolvePolicyId(req.params.policyId);
      const policyUpdate = req.body;
      const userContext = getUserContext(req);

      if (!userContext?.team_id) {
        return next(createError(400, "Team context required"));
      }

      // Validate policy structure
      const validKeys = [
        "name",
        "budgets",
        "throttles",
        "blocks",
        "degradations",
        "alerts",
      ];
      const invalidKeys = Object.keys(policyUpdate).filter(
        (k) => !validKeys.includes(k)
      );
      if (invalidKeys.length > 0) {
        return next(
          createError(400, `Invalid policy keys: ${invalidKeys.join(", ")}`)
        );
      }

      const policy = await controlService.updatePolicy(
        userContext.team_id,
        policyId,
        policyUpdate,
        userContext
      );

      // Notify connected SDK instances via WebSocket
      if (global._ADEN_CONTROL_EMITTER) {
        global._ADEN_CONTROL_EMITTER.emitPolicyUpdate(
          userContext.team_id,
          policyId,
          policy
        );
      }

      res.json(policy);
    } catch (error: unknown) {
      console.error("[Aden Control] Error updating policy:", getErrorMessage(error));
      next(createError(500, "Failed to update policy"));
    }
  }
);

/**
 * DELETE /v1/control/policies/:policyId/rules
 * Clear all rules from the policy (keeps the policy itself)
 * Use "default" as policyId to clear the team's default policy
 */
router.delete(
  "/policies/:policyId/rules",
  passport.authenticate("jwt", { session: false }),
  async (req: AuthenticatedRequest, res: Response, next: NextFunction) => {
    try {
      const policyId = resolvePolicyId(req.params.policyId);
      const userContext = getUserContext(req);

      if (!userContext?.team_id) {
        return next(createError(400, "Team context required"));
      }

      const policy = await controlService.clearPolicy(
        userContext.team_id,
        policyId,
        userContext
      );

      // Notify connected SDK instances via WebSocket
      if (global._ADEN_CONTROL_EMITTER) {
        global._ADEN_CONTROL_EMITTER.emitPolicyUpdate(
          userContext.team_id,
          policyId,
          policy
        );
      }

      res.json(policy);
    } catch (error: unknown) {
      console.error("[Aden Control] Error clearing policy:", getErrorMessage(error));
      next(createError(500, "Failed to clear policy"));
    }
  }
);

// =============================================================================
// Rule Management Endpoints
// =============================================================================

/**
 * Valid budget types matching frontend BudgetType enum
 */
const VALID_BUDGET_TYPES = [
  "global",
  "agent",
  "tenant",
  "customer",
  "feature",
  "tag",
];

/**
 * Valid limit actions matching frontend LimitAction enum
 */
const VALID_LIMIT_ACTIONS = ["kill", "throttle", "degrade"];

/**
 * Validate BudgetAlert structure
 */
function isValidBudgetAlert(alert: unknown): alert is BudgetAlert {
  return (
    alert !== null &&
    typeof alert === "object" &&
    typeof (alert as BudgetAlert).threshold === "number" &&
    (alert as BudgetAlert).threshold >= 0 &&
    (alert as BudgetAlert).threshold <= 100 &&
    typeof (alert as BudgetAlert).enabled === "boolean"
  );
}

/**
 * Validate BudgetNotifications structure
 */
function isValidBudgetNotifications(
  notifications: unknown
): notifications is BudgetNotifications {
  if (!notifications || typeof notifications !== "object") return false;
  const n = notifications as BudgetNotifications;
  if (typeof n.inApp !== "boolean") return false;
  if (typeof n.email !== "boolean") return false;
  if (!Array.isArray(n.emailRecipients)) return false;
  if (typeof n.webhook !== "boolean") return false;
  return true;
}

/**
 * POST /v1/control/policies/:policyId/budgets
 * Add a budget rule
 *
 * Expected body (BudgetConfig):
 * {
 *   id: string,
 *   name: string,
 *   type: 'global' | 'agent' | 'tenant' | 'customer' | 'feature' | 'tag',
 *   tagCategory?: string,
 *   limit: number,
 *   spent: number,
 *   limitAction: 'kill' | 'throttle' | 'degrade',
 *   degradeToModel?: string,     // required when limitAction is 'degrade'
 *   degradeToProvider?: string,  // required when limitAction is 'degrade'
 *   alerts: Array<{ threshold: number, enabled: boolean }>,
 *   notifications: { inApp: boolean, email: boolean, emailRecipients: string[], webhook: boolean }
 * }
 */
router.post(
  "/policies/:policyId/budgets",
  passport.authenticate("jwt", { session: false }),
  async (req: AuthenticatedRequest, res: Response, next: NextFunction) => {
    try {
      const policyId = resolvePolicyId(req.params.policyId);
      const rule = req.body as BudgetRule;
      const userContext = getUserContext(req);

      if (!userContext?.team_id) {
        return next(createError(400, "Team context required"));
      }

      // Validate required fields
      if (!rule.id || typeof rule.id !== "string") {
        return next(createError(400, "id (string) is required"));
      }

      if (!rule.name || typeof rule.name !== "string") {
        return next(createError(400, "name (string) is required"));
      }

      if (!rule.type || !VALID_BUDGET_TYPES.includes(rule.type)) {
        return next(
          createError(
            400,
            `type must be one of: ${VALID_BUDGET_TYPES.join(", ")}`
          )
        );
      }

      // tags array is required when type is 'tag'
      if (rule.type === "tag") {
        if (!Array.isArray(rule.tags) || rule.tags.length === 0) {
          return next(
            createError(
              400,
              "tags (non-empty array) is required when type is 'tag'"
            )
          );
        }
        // Validate each tag is a string
        for (let i = 0; i < rule.tags.length; i++) {
          if (typeof rule.tags[i] !== "string") {
            return next(createError(400, `tags[${i}] must be a string`));
          }
        }
      }

      if (typeof rule.limit !== "number" || rule.limit < 0) {
        return next(createError(400, "limit must be a non-negative number"));
      }

      if (typeof rule.spent !== "number" || rule.spent < 0) {
        return next(createError(400, "spent must be a non-negative number"));
      }

      if (
        !rule.limitAction ||
        !VALID_LIMIT_ACTIONS.includes(rule.limitAction)
      ) {
        return next(
          createError(
            400,
            `limitAction must be one of: ${VALID_LIMIT_ACTIONS.join(", ")}`
          )
        );
      }

      // degradeToModel and degradeToProvider are required when limitAction is 'degrade'
      if (rule.limitAction === "degrade") {
        if (!rule.degradeToModel || typeof rule.degradeToModel !== "string") {
          return next(
            createError(
              400,
              "degradeToModel is required when limitAction is 'degrade'"
            )
          );
        }
        if (
          !rule.degradeToProvider ||
          typeof rule.degradeToProvider !== "string"
        ) {
          return next(
            createError(
              400,
              "degradeToProvider is required when limitAction is 'degrade'"
            )
          );
        }

        // Validate model belongs to the specified provider
        const targets = await pricingService.getDegradationTargets();
        const providerModels = targets.models[rule.degradeToProvider];

        if (!providerModels) {
          return next(
            createError(400, `Unknown provider: ${rule.degradeToProvider}`)
          );
        }

        const validModelNames = providerModels.map(
          (m: { model: string }) => m.model
        );
        if (!validModelNames.includes(rule.degradeToModel)) {
          return next(
            createError(
              400,
              `degradeToModel "${rule.degradeToModel}" does not belong to provider "${rule.degradeToProvider}"`
            )
          );
        }
      }

      if (!Array.isArray(rule.alerts)) {
        return next(createError(400, "alerts must be an array"));
      }
      for (let i = 0; i < rule.alerts.length; i++) {
        if (!isValidBudgetAlert(rule.alerts[i])) {
          return next(
            createError(
              400,
              `alerts[${i}] must have threshold (0-100) and enabled (boolean)`
            )
          );
        }
      }

      if (!isValidBudgetNotifications(rule.notifications)) {
        return next(
          createError(
            400,
            "notifications must have inApp, email, emailRecipients[], and webhook fields"
          )
        );
      }

      const policy = await controlService.addBudgetRule(
        userContext.team_id,
        policyId,
        rule,
        userContext
      );

      if (global._ADEN_CONTROL_EMITTER) {
        global._ADEN_CONTROL_EMITTER.emitPolicyUpdate(
          userContext.team_id,
          policyId,
          policy
        );
      }

      res.json(policy);
    } catch (error: unknown) {
      console.error("[Aden Control] Error adding budget rule:", getErrorMessage(error));
      next(createError(500, "Failed to add budget rule"));
    }
  }
);

/**
 * POST /v1/control/policies/:policyId/throttles
 * Add a throttle rule
 */
router.post(
  "/policies/:policyId/throttles",
  passport.authenticate("jwt", { session: false }),
  async (req: AuthenticatedRequest, res: Response, next: NextFunction) => {
    try {
      const policyId = resolvePolicyId(req.params.policyId);
      const rule = req.body;
      const userContext = getUserContext(req);

      if (!userContext?.team_id) {
        return next(createError(400, "Team context required"));
      }

      if (!rule.requests_per_minute && !rule.delay_ms) {
        return next(
          createError(400, "requests_per_minute or delay_ms required")
        );
      }

      const policy = await controlService.addThrottleRule(
        userContext.team_id,
        policyId,
        rule,
        userContext
      );

      if (global._ADEN_CONTROL_EMITTER) {
        global._ADEN_CONTROL_EMITTER.emitPolicyUpdate(
          userContext.team_id,
          policyId,
          policy
        );
      }

      res.json(policy);
    } catch (error: unknown) {
      console.error("[Aden Control] Error adding throttle rule:", getErrorMessage(error));
      next(createError(500, "Failed to add throttle rule"));
    }
  }
);

/**
 * POST /v1/control/policies/:policyId/blocks
 * Add a block rule
 */
router.post(
  "/policies/:policyId/blocks",
  passport.authenticate("jwt", { session: false }),
  async (req: AuthenticatedRequest, res: Response, next: NextFunction) => {
    try {
      const policyId = resolvePolicyId(req.params.policyId);
      const rule = req.body;
      const userContext = getUserContext(req);

      if (!userContext?.team_id) {
        return next(createError(400, "Team context required"));
      }

      if (!rule.reason) {
        return next(createError(400, "reason required"));
      }

      const policy = await controlService.addBlockRule(
        userContext.team_id,
        policyId,
        rule,
        userContext
      );

      if (global._ADEN_CONTROL_EMITTER) {
        global._ADEN_CONTROL_EMITTER.emitPolicyUpdate(
          userContext.team_id,
          policyId,
          policy
        );
      }

      res.json(policy);
    } catch (error: unknown) {
      console.error("[Aden Control] Error adding block rule:", getErrorMessage(error));
      next(createError(500, "Failed to add block rule"));
    }
  }
);

/**
 * POST /v1/control/policies/:policyId/degradations
 * Add a degradation rule (within same provider only - no cross-vendor degradation)
 *
 * Body:
 * {
 *   provider: string,     // e.g., "openai", "anthropic"
 *   from_model: string,   // Model to degrade from, e.g., "gpt-4o"
 *   to_model: string,     // Model to degrade to, e.g., "gpt-4o-mini"
 *   trigger: string       // When to trigger: "budget_exceeded", "rate_limit", etc.
 * }
 */
router.post(
  "/policies/:policyId/degradations",
  passport.authenticate("jwt", { session: false }),
  async (req: AuthenticatedRequest, res: Response, next: NextFunction) => {
    try {
      const policyId = resolvePolicyId(req.params.policyId);
      const rule = req.body;
      const userContext = getUserContext(req);

      if (!userContext?.team_id) {
        return next(createError(400, "Team context required"));
      }

      if (!rule.provider || typeof rule.provider !== "string") {
        return next(createError(400, "provider (string) is required"));
      }

      if (!rule.from_model || typeof rule.from_model !== "string") {
        return next(createError(400, "from_model (string) is required"));
      }

      if (!rule.to_model || typeof rule.to_model !== "string") {
        return next(createError(400, "to_model (string) is required"));
      }

      if (!rule.trigger || typeof rule.trigger !== "string") {
        return next(createError(400, "trigger (string) is required"));
      }

      // Validate models belong to the specified provider
      const targets = await pricingService.getDegradationTargets();
      const providerModels = targets.models[rule.provider];

      if (!providerModels) {
        return next(createError(400, `Unknown provider: ${rule.provider}`));
      }

      const validModelNames = providerModels.map(
        (m: { model: string }) => m.model
      );

      if (!validModelNames.includes(rule.from_model)) {
        return next(
          createError(
            400,
            `from_model "${rule.from_model}" does not belong to provider "${rule.provider}"`
          )
        );
      }

      if (!validModelNames.includes(rule.to_model)) {
        return next(
          createError(
            400,
            `to_model "${rule.to_model}" does not belong to provider "${rule.provider}"`
          )
        );
      }

      const policy = await controlService.addDegradeRule(
        userContext.team_id,
        policyId,
        rule,
        userContext
      );

      if (global._ADEN_CONTROL_EMITTER) {
        global._ADEN_CONTROL_EMITTER.emitPolicyUpdate(
          userContext.team_id,
          policyId,
          policy
        );
      }

      res.json(policy);
    } catch (error: unknown) {
      console.error("[Aden Control] Error adding degradation rule:", getErrorMessage(error));
      next(createError(500, "Failed to add degradation rule"));
    }
  }
);

/**
 * POST /v1/control/policies/:policyId/alerts
 * Add an alert rule
 */
router.post(
  "/policies/:policyId/alerts",
  passport.authenticate("jwt", { session: false }),
  async (req: AuthenticatedRequest, res: Response, next: NextFunction) => {
    try {
      const policyId = resolvePolicyId(req.params.policyId);
      const rule = req.body;
      const userContext = getUserContext(req);

      if (!userContext?.team_id) {
        return next(createError(400, "Team context required"));
      }

      if (!rule.trigger || !rule.level || !rule.message) {
        return next(createError(400, "trigger, level, and message required"));
      }

      // Validate level
      if (!["info", "warning", "critical"].includes(rule.level)) {
        return next(
          createError(400, "level must be one of: info, warning, critical")
        );
      }

      // Validate trigger
      if (
        !["budget_threshold", "model_usage", "always"].includes(rule.trigger)
      ) {
        return next(
          createError(
            400,
            "trigger must be one of: budget_threshold, model_usage, always"
          )
        );
      }

      const policy = await controlService.addAlertRule(
        userContext.team_id,
        policyId,
        rule,
        userContext
      );

      if (global._ADEN_CONTROL_EMITTER) {
        global._ADEN_CONTROL_EMITTER.emitPolicyUpdate(
          userContext.team_id,
          policyId,
          policy
        );
      }

      res.json(policy);
    } catch (error: unknown) {
      console.error("[Aden Control] Error adding alert rule:", getErrorMessage(error));
      next(createError(500, "Failed to add alert rule"));
    }
  }
);

// =============================================================================
// Budget Management Endpoints
// =============================================================================

/**
 * GET /v1/control/budget/:budgetId
 * Get budget status for a budget ID
 */
router.get(
  "/budget/:budgetId",
  passport.authenticate("jwt", { session: false }),
  async (req: Request, res: Response, next: NextFunction) => {
    try {
      const { budgetId } = req.params;
      const status = await controlService.getBudgetStatus(budgetId);
      res.json(status);
    } catch (error: unknown) {
      console.error("[Aden Control] Error getting budget status:", getErrorMessage(error));
      next(createError(500, "Failed to get budget status"));
    }
  }
);

/**
 * POST /v1/control/budget/:budgetId/reset
 * Reset budget for a budget ID
 */
router.post(
  "/budget/:budgetId/reset",
  passport.authenticate("jwt", { session: false }),
  async (req: Request, res: Response, next: NextFunction) => {
    try {
      const { budgetId } = req.params;
      await controlService.resetBudget(budgetId);
      res.json({ success: true, id: budgetId });
    } catch (error: unknown) {
      console.error("[Aden Control] Error resetting budget:", getErrorMessage(error));
      next(createError(500, "Failed to reset budget"));
    }
  }
);

// =============================================================================
// Team Policies & Metrics Endpoints
// =============================================================================

/**
 * GET /v1/control/policies
 * Get all policies for the current team (dashboard)
 */
router.get(
  "/policies",
  passport.authenticate("jwt", { session: false }),
  async (req: AuthenticatedRequest, res: Response, next: NextFunction) => {
    try {
      const userContext = getUserContext(req);
      if (!userContext?.team_id) {
        return next(createError(400, "Team context required"));
      }

      const { limit, offset } = req.query;
      const policies = await controlService.getPoliciesByTeam(
        userContext.team_id,
        {
          limit: parseInt(limit as string) || 100,
          offset: parseInt(offset as string) || 0,
        }
      );

      res.json({ policies, count: policies.length });
    } catch (error: unknown) {
      console.error("[Aden Control] Error getting team policies:", getErrorMessage(error));
      next(createError(500, "Failed to get team policies"));
    }
  }
);

/**
 * POST /v1/control/policies
 * Create a new policy for the team
 */
router.post(
  "/policies",
  passport.authenticate("jwt", { session: false }),
  async (req: AuthenticatedRequest, res: Response, next: NextFunction) => {
    try {
      const userContext = getUserContext(req);
      if (!userContext?.team_id) {
        return next(createError(400, "Team context required"));
      }

      const { name } = req.body;
      if (!name || typeof name !== "string") {
        return next(createError(400, "name (string) is required"));
      }

      // Create a new policy with the given name
      const policy = await controlService.updatePolicy(
        userContext.team_id,
        null, // Will generate a new policy ID
        { name },
        userContext
      );

      res.status(201).json(policy);
    } catch (error: unknown) {
      console.error("[Aden Control] Error creating policy:", getErrorMessage(error));
      next(createError(500, "Failed to create policy"));
    }
  }
);

/**
 * GET /v1/control/policies/:policyId
 * Get a specific policy by ID
 * Use "default" as policyId to get the team's default policy
 */
router.get(
  "/policies/:policyId",
  passport.authenticate("jwt", { session: false }),
  async (req: AuthenticatedRequest, res: Response, next: NextFunction) => {
    try {
      const policyId = resolvePolicyId(req.params.policyId);
      const userContext = getUserContext(req);

      if (!userContext?.team_id) {
        return next(createError(400, "Team context required"));
      }

      const policy = await controlService.getPolicy(
        userContext.team_id,
        policyId,
        userContext
      );

      if (!policy) {
        return next(createError(404, "Policy not found"));
      }

      res.json(policy);
    } catch (error: unknown) {
      console.error("[Aden Control] Error getting policy:", getErrorMessage(error));
      next(createError(500, "Failed to get policy"));
    }
  }
);

/**
 * DELETE /v1/control/policies/:policyId
 * Delete a policy
 * Note: "default" is NOT allowed here - must specify actual policy ID
 */
router.delete(
  "/policies/:policyId",
  passport.authenticate("jwt", { session: false }),
  async (req: AuthenticatedRequest, res: Response, next: NextFunction) => {
    try {
      const { policyId } = req.params;

      // Don't allow deleting "default" - must specify actual policy ID
      if (policyId === "default") {
        return next(
          createError(400, "Cannot delete 'default' - specify actual policy ID")
        );
      }

      const userContext = getUserContext(req);

      if (!userContext?.team_id) {
        return next(createError(400, "Team context required"));
      }

      await controlService.deletePolicy(
        userContext.team_id,
        policyId,
        userContext
      );

      res.json({ success: true, id: policyId });
    } catch (error: unknown) {
      console.error("[Aden Control] Error deleting policy:", getErrorMessage(error));
      next(createError(500, "Failed to delete policy"));
    }
  }
);

/**
 * GET /v1/control/metrics
 * Get metrics summary for the current team (dashboard analytics)
 */
router.get(
  "/metrics",
  passport.authenticate("jwt", { session: false }),
  async (req: AuthenticatedRequest, res: Response, next: NextFunction) => {
    try {
      const userContext = getUserContext(req);
      if (!userContext?.team_id) {
        return next(createError(400, "Team context required"));
      }

      const { start_date, end_date } = req.query;
      const summary = await controlService.getMetricsSummary(
        userContext.team_id,
        {
          start_date: start_date as string | undefined,
          end_date: end_date as string | undefined,
        }
      );

      res.json(summary);
    } catch (error: unknown) {
      console.error("[Aden Control] Error getting metrics summary:", getErrorMessage(error));
      next(createError(500, "Failed to get metrics summary"));
    }
  }
);

// =============================================================================
// Usage & Rate Analytics Endpoints
// =============================================================================

/**
 * GET /v1/control/metrics/usage
 * Get usage breakdown (daily, by model, by feature)
 */
router.get(
  "/metrics/usage",
  passport.authenticate("jwt", { session: false }),
  async (req: AuthenticatedRequest, res: Response, next: NextFunction) => {
    try {
      const userContext = getUserContext(req);
      if (!userContext?.team_id) {
        return next(createError(400, "Team context required"));
      }

      const { days, context_id } = req.query;
      const breakdown = await controlService.getUsageBreakdown(
        userContext.team_id,
        {
          days: days ? parseInt(days as string) : 7,
          context_id: context_id as string | undefined,
        }
      );

      res.json(breakdown);
    } catch (error: unknown) {
      console.error("[Aden Control] Error getting usage breakdown:", getErrorMessage(error));
      next(createError(500, "Failed to get usage breakdown"));
    }
  }
);

/**
 * GET /v1/control/metrics/rates
 * Get rate metrics (peak, p95, avg, min, burst)
 */
router.get(
  "/metrics/rates",
  passport.authenticate("jwt", { session: false }),
  async (req: AuthenticatedRequest, res: Response, next: NextFunction) => {
    try {
      const userContext = getUserContext(req);
      if (!userContext?.team_id) {
        return next(createError(400, "Team context required"));
      }

      const { days, context_id } = req.query;
      const rates = await controlService.getRateMetrics(userContext.team_id, {
        days: days ? parseInt(days as string) : 30,
        context_id: context_id as string | undefined,
      });

      res.json(rates);
    } catch (error: unknown) {
      console.error("[Aden Control] Error getting rate metrics:", getErrorMessage(error));
      next(createError(500, "Failed to get rate metrics"));
    }
  }
);

/**
 * GET /v1/control/policies/:policyId/budgets/:budgetId
 * Get detailed budget info including usage stats
 */
router.get(
  "/policies/:policyId/budgets/:budgetId",
  passport.authenticate("jwt", { session: false }),
  async (req: AuthenticatedRequest, res: Response, next: NextFunction) => {
    try {
      const policyId = resolvePolicyId(req.params.policyId);
      const { budgetId } = req.params;
      const userContext = getUserContext(req);

      if (!userContext?.team_id) {
        return next(createError(400, "Team context required"));
      }

      const budget = await controlService.getBudgetDetails(
        userContext.team_id,
        policyId,
        budgetId
      );

      if (!budget) {
        return next(createError(404, "Budget not found"));
      }

      res.json(budget);
    } catch (error: unknown) {
      console.error("[Aden Control] Error getting budget details:", getErrorMessage(error));
      next(createError(500, "Failed to get budget details"));
    }
  }
);

/**
 * GET /v1/control/policies/:policyId/budgets/:budgetId/usage
 * Get usage breakdown for a specific budget
 * Returns: { daily, by_model, by_feature }
 */
router.get(
  "/policies/:policyId/budgets/:budgetId/usage",
  passport.authenticate("jwt", { session: false }),
  async (req: AuthenticatedRequest, res: Response, next: NextFunction) => {
    try {
      const policyId = resolvePolicyId(req.params.policyId);
      const { budgetId } = req.params;
      const { days } = req.query;
      const userContext = getUserContext(req);

      if (!userContext?.team_id) {
        return next(createError(400, "Team context required"));
      }

      // Get budget details for filtering
      const budget = await controlService.getBudgetDetails(
        userContext.team_id,
        policyId,
        budgetId
      );

      if (!budget) {
        return next(createError(404, "Budget not found"));
      }

      // Pass the budget object for type-aware filtering
      const breakdown = await controlService.getUsageBreakdown(
        userContext.team_id,
        {
          days: days ? parseInt(days as string) : 7,
          budget,
        }
      );

      res.json(breakdown);
    } catch (error: unknown) {
      console.error("[Aden Control] Error getting budget usage:", getErrorMessage(error));
      next(createError(500, "Failed to get budget usage"));
    }
  }
);

/**
 * GET /v1/control/policies/:policyId/budgets/:budgetId/rates
 * Get rate metrics for a specific budget
 * Returns: { peak_rate, p95_rate, avg_rate, min_rate, max_burst }
 */
router.get(
  "/policies/:policyId/budgets/:budgetId/rates",
  passport.authenticate("jwt", { session: false }),
  async (req: AuthenticatedRequest, res: Response, next: NextFunction) => {
    try {
      const policyId = resolvePolicyId(req.params.policyId);
      const { budgetId } = req.params;
      const { days } = req.query;
      const userContext = getUserContext(req);

      if (!userContext?.team_id) {
        return next(createError(400, "Team context required"));
      }

      // Get budget details for filtering
      const budget = await controlService.getBudgetDetails(
        userContext.team_id,
        policyId,
        budgetId
      );

      if (!budget) {
        return next(createError(404, "Budget not found"));
      }

      // Pass the budget object for type-aware filtering
      const rates = await controlService.getRateMetrics(userContext.team_id, {
        days: days ? parseInt(days as string) : 30,
        budget,
      });

      res.json(rates);
    } catch (error: unknown) {
      console.error("[Aden Control] Error getting budget rates:", getErrorMessage(error));
      next(createError(500, "Failed to get budget rates"));
    }
  }
);

// =============================================================================
// Budget Validation Endpoint (for Hybrid Enforcement)
// =============================================================================

/**
 * POST /v1/control/budget/validate
 * Server-side budget validation for hybrid enforcement.
 *
 * Called by SDK when local budget usage approaches threshold (e.g., 80%).
 * Returns authoritative spend from TSDB and enforcement decision.
 */
router.post(
  "/budget/validate",
  passport.authenticate("jwt", { session: false }),
  async (req: AuthenticatedRequest, res: Response, next: NextFunction) => {
    try {
      const userContext = getUserContext(req);
      if (!userContext?.team_id) {
        return next(createError(400, "Team context required"));
      }

      const { budget_id, estimated_cost, context, local_spend } = req.body as {
        budget_id?: string;
        estimated_cost: number;
        context?: ValidationContext;
        local_spend?: number;
      };
      const policyId = getPolicyId(req);

      if (typeof estimated_cost !== "number" || estimated_cost < 0) {
        return next(
          createError(400, "estimated_cost must be a non-negative number")
        );
      }

      // Get the policy with authoritative budget data from TSDB
      const policy = await controlService.getPolicy(
        userContext.team_id,
        policyId,
        userContext
      );

      if (!policy) {
        return next(createError(404, "Policy not found"));
      }

      // MULTI-BUDGET MODE: Use context to find all matching budgets
      if (context && typeof context === "object") {
        const matchingBudgets = controlService.findMatchingBudgetsForContext(
          policy.budgets || [],
          context
        );

        if (matchingBudgets.length === 0) {
          // No budgets match this context - allow by default
          return res.json({
            allowed: true,
            action: "allow",
            reason: "No budgets match the provided context",
            authoritative_spend: 0,
            budget_limit: 0,
            usage_percent: 0,
            projected_percent: 0,
            policy_version: policy.version,
            budgets_checked: [],
          });
        }

        // Validate all matching budgets and get most restrictive result
        const result = controlService.validateMultipleBudgets(
          matchingBudgets,
          estimated_cost,
          local_spend
        );

        // Log the validation for audit
        console.log(
          `[Aden Control] Multi-budget validation: ` +
            `checked ${result.budgets_checked.length} budgets, ` +
            `action: ${result.action}` +
            (result.restricting_budget_name
              ? `, restricting: ${result.restricting_budget_name}`
              : "")
        );

        return res.json({
          ...result,
          policy_version: policy.version,
        });
      }

      // SINGLE-BUDGET MODE (backward compatible): Use budget_id
      if (!budget_id) {
        return next(createError(400, "budget_id or context is required"));
      }

      // Find the budget by ID
      const budget = policy.budgets?.find(
        (b: { id: string }) => b.id === budget_id
      );
      if (!budget) {
        // Budget not found - allow by default (budget may have been removed)
        return res.json({
          allowed: true,
          action: "allow",
          reason: "Budget not found in policy",
          authoritative_spend: 0,
          budget_limit: 0,
          usage_percent: 0,
          projected_percent: 0,
          policy_version: policy.version,
          budgets_checked: [],
        });
      }

      // Use the multi-budget validator for consistency (with single budget)
      const result = controlService.validateMultipleBudgets(
        [budget],
        estimated_cost,
        local_spend
      );

      // Log the validation for audit
      console.log(
        `[Aden Control] Budget validation: ${budget_id} - ` +
          `spend: $${result.authoritative_spend.toFixed(4)}, ` +
          `limit: $${budget.limit}, ` +
          `action: ${result.action}`
      );

      res.json({
        ...result,
        policy_version: policy.version,
        // Keep backward-compatible fields
        updated_spend: result.authoritative_spend,
      });
    } catch (error: unknown) {
      console.error("[Aden Control] Error validating budget:", getErrorMessage(error));
      next(createError(500, "Failed to validate budget"));
    }
  }
);

// =============================================================================
// Model Options for Degradation
// =============================================================================

/**
 * GET /v1/control/degradation-targets
 * Get available target models for budget degradation mode, grouped by provider
 * Models are sorted by cost (cheapest first)
 *
 * Query params:
 *   provider (optional) - Filter to specific provider (e.g., "openai", "anthropic")
 *
 * Response (no filter):
 *   { providers: [...], models: { openai: [...], anthropic: [...] } }
 *
 * Response (with provider filter):
 *   { provider: "openai", models: [...] }
 */
router.get(
  "/degradation-targets",
  passport.authenticate("jwt", { session: false }),
  async (req: Request, res: Response, next: NextFunction) => {
    try {
      const { provider } = req.query;
      const targets = await pricingService.getDegradationTargets();

      // If provider specified, filter to that provider only
      if (provider) {
        const providerModels = targets.models[provider as string];
        if (!providerModels) {
          return next(createError(400, `Unknown provider: ${provider}`));
        }
        return res.json({
          provider,
          models: providerModels,
        });
      }

      res.json(targets);
    } catch (error: unknown) {
      console.error("[Aden Control] Error getting degradation targets:", getErrorMessage(error));
      next(createError(500, "Failed to get degradation targets"));
    }
  }
);

// =============================================================================
// SSE - Real-time Agent Status Stream
// =============================================================================

interface ControlEmitter {
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
 * GET /v1/control/agent-status/stream
 * SSE endpoint for real-time agent connection status
 *
 * Streams updates every 2 seconds with:
 * - active: boolean indicating if any agents are connected
 * - count: number of connected agents
 * - instances: array of connected agent details
 */
router.get(
  "/agent-status/stream",
  passport.authenticate("jwt", { session: false }),
  (req: AuthenticatedRequest, res: Response) => {
    const teamId = req.user?.current_team_id;

    if (!teamId) {
      res.status(401).json({ error: "Team ID required" });
      return;
    }

    // Set SSE headers
    res.setHeader("Content-Type", "text/event-stream");
    res.setHeader("Cache-Control", "no-cache");
    res.setHeader("Connection", "keep-alive");
    res.setHeader("X-Accel-Buffering", "no"); // Disable nginx buffering
    res.flushHeaders();

    const controlEmitter = req.app.locals.controlEmitter as
      | ControlEmitter
      | undefined;

    // Send initial status immediately
    const sendStatus = () => {
      if (!controlEmitter) {
        const data = {
          active: false,
          count: 0,
          instances: [],
          timestamp: new Date().toISOString(),
          error: "WebSocket not initialized",
        };
        res.write(`data: ${JSON.stringify(data)}\n\n`);
        return;
      }

      const count = controlEmitter.getConnectedCount(teamId);
      const instances = controlEmitter.getConnectedInstances(teamId);

      const data = {
        active: count > 0,
        count,
        instances,
        timestamp: new Date().toISOString(),
      };

      res.write(`data: ${JSON.stringify(data)}\n\n`);
    };

    // Send immediately
    sendStatus();

    // Send updates every 2 seconds
    const intervalId = setInterval(sendStatus, 2000);

    // Cleanup on client disconnect
    req.on("close", () => {
      clearInterval(intervalId);
    });
  }
);

/**
 * GET /v1/control/agent-status
 * Get current agent connection status (non-streaming)
 */
router.get(
  "/agent-status",
  passport.authenticate("jwt", { session: false }),
  (req: AuthenticatedRequest, res: Response) => {
    const teamId = req.user?.current_team_id;

    if (!teamId) {
      res.status(401).json({ error: "Team ID required" });
      return;
    }

    const controlEmitter = req.app.locals.controlEmitter as
      | ControlEmitter
      | undefined;

    if (!controlEmitter) {
      res.json({
        active: false,
        count: 0,
        instances: [],
        timestamp: new Date().toISOString(),
        error: "WebSocket not initialized",
      });
      return;
    }

    const count = controlEmitter.getConnectedCount(teamId);
    const instances = controlEmitter.getConnectedInstances(teamId);

    res.json({
      active: count > 0,
      count,
      instances,
      timestamp: new Date().toISOString(),
    });
  }
);

// =============================================================================
// Agent Discovery - Historical agents with availability
// =============================================================================

/**
 * GET /v1/control/agents
 * Get all agents from past events with their current availability status
 *
 * Query params:
 * - since: ISO date string to filter events from (optional)
 * - limit: Max number of agents to return (default: 100)
 *
 * Returns agents sorted by last_seen descending with:
 * - agent: unique agent identifier
 * - agent_name: human-readable name (if available)
 * - status: "connected" | "disconnected"
 * - connection_type: "websocket" | "http" | null (null if disconnected)
 * - first_seen: when agent first appeared in events
 * - last_seen: when agent last appeared in events
 * - total_requests: total LLM requests made by this agent
 * - total_cost: total cost incurred by this agent
 */
router.get(
  "/agents",
  passport.authenticate("jwt", { session: false }),
  async (req: AuthenticatedRequest, res: Response, next: NextFunction) => {
    try {
      const teamId = req.user?.current_team_id;
      if (!teamId) {
        throw createError(401, "Team ID required");
      }

      // Parse query params
      const since = req.query.since ? new Date(req.query.since as string) : undefined;
      const limit = req.query.limit ? parseInt(req.query.limit as string, 10) : 100;

      // Get team-specific pool/schema
      const teamPool = await getTeamPool(teamId);
      const schemaName = buildSchemaName(teamId);
      const client = await teamPool.connect();

      let historicalAgents;
      try {
        await client.query(`SET search_path TO ${schemaName}`);
        await tsdbService.ensureSchema(client);

        // Get all distinct agents from TSDB
        historicalAgents = await tsdbService.getDistinctAgents(
          teamId,
          { since, limit },
          client
        );
      } finally {
        client.release();
      }

      // Get currently connected instances
      const controlEmitter = req.app.locals.controlEmitter as ControlEmitter | undefined;
      const connectedInstances = controlEmitter?.getConnectedInstances(teamId) || [];

      // Build a map of connected agents (by instance_id and agent_name)
      const connectedByInstanceId = new Map<string, typeof connectedInstances[0]>();
      const connectedByAgentName = new Map<string, typeof connectedInstances[0]>();

      for (const instance of connectedInstances) {
        connectedByInstanceId.set(instance.instance_id, instance);
        if (instance.agent_name) {
          connectedByAgentName.set(instance.agent_name, instance);
        }
      }

      // Merge historical agents with connection status
      const agents = historicalAgents.map((agent) => {
        // Try to match by agent ID (instance_id) or agent_name
        const connectedInstance =
          connectedByInstanceId.get(agent.agent) ||
          connectedByAgentName.get(agent.agent) ||
          (agent.agent_name ? connectedByAgentName.get(agent.agent_name) : null);

        return {
          agent: agent.agent,
          agent_name: agent.agent_name || connectedInstance?.agent_name || null,
          status: connectedInstance ? "connected" : "disconnected",
          connection_type: connectedInstance?.connection_type || null,
          instance_id: connectedInstance?.instance_id || null,
          first_seen: agent.first_seen.toISOString(),
          last_seen: agent.last_seen.toISOString(),
          total_requests: agent.total_requests,
          total_cost: agent.total_cost,
        };
      });

      // Also add any connected agents that don't have historical events yet
      const historicalAgentIds = new Set(historicalAgents.map((a) => a.agent));
      const historicalAgentNames = new Set(
        historicalAgents.map((a) => a.agent_name).filter(Boolean)
      );

      for (const instance of connectedInstances) {
        const isInHistory =
          historicalAgentIds.has(instance.instance_id) ||
          (instance.agent_name && historicalAgentNames.has(instance.agent_name));

        if (!isInHistory) {
          agents.push({
            agent: instance.instance_id,
            agent_name: instance.agent_name,
            status: "connected",
            connection_type: instance.connection_type,
            instance_id: instance.instance_id,
            first_seen: instance.connected_at,
            last_seen: instance.last_heartbeat,
            total_requests: 0,
            total_cost: 0,
          });
        }
      }

      res.json({
        agents,
        total: agents.length,
        connected_count: agents.filter((a) => a.status === "connected").length,
        timestamp: new Date().toISOString(),
      });
    } catch (error: unknown) {
      next(error);
    }
  }
);

// =============================================================================
// Health Check
// =============================================================================

/**
 * GET /v1/control/health
 * Health check endpoint
 */
router.get("/health", (_req: Request, res: Response) => {
  res.json({
    status: "healthy",
    timestamp: new Date().toISOString(),
    websocket: !!global._ADEN_CONTROL_EMITTER,
  });
});

export default router;
