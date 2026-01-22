/**
 * Quickstart Documentation API Controller
 * Generates SDK quickstart documentation based on agent framework
 */
import express, { Request, Response, NextFunction } from "express";
import passport from "passport";
import { getErrorMessage } from "../utils/error";
// Passport is initialized in app.js

import * as quickstartService from "../services/quickstart/quickstart_service";

const router = express.Router();

interface AuthenticatedUser {
  id: number;
  current_team_id: number;
  [key: string]: unknown;
}

interface AuthenticatedRequest extends Request {
  user?: AuthenticatedUser;
}

/**
 * @swagger
 * /quickstart/options:
 *   get:
 *     summary: Get available options for quickstart generation
 *     tags:
 *       - Quickstart
 *     responses:
 *       200:
 *         description: Available options for quickstart document generation
 */
router.get("/options", async (req: Request, res: Response, next: NextFunction) => {
  try {
    const options = quickstartService.getQuickstartOptions();
    res.send(options);
  } catch (error: unknown) {
    next(error);
  }
});

/**
 * @swagger
 * /quickstart/generate:
 *   post:
 *     summary: Generate quickstart documentation with user's system token
 *     tags:
 *       - Quickstart
 *     security:
 *       - jwtAuth: []
 *     requestBody:
 *       required: true
 *       content:
 *         application/json:
 *           schema:
 *             type: object
 *             required:
 *               - agentFramework
 *             properties:
 *               agentFramework:
 *                 type: string
 *                 enum: [generic, langgraph, livekit]
 *                 description: The agent framework to use
 *     responses:
 *       200:
 *         description: Generated quickstart documentation
 *       400:
 *         description: Invalid parameters
 *       401:
 *         description: Unauthorized - JWT token required
 */
router.post(
  "/generate",
  passport.authenticate("jwt", { session: false }),
  async (req: AuthenticatedRequest, res: Response, next: NextFunction) => {
    try {
      const { user, body } = req;
      const { agentFramework, llmVendor, sdkLanguage } = body;

      // Get the user's latest non-system API key
      const userDbService = req.app.locals.userDbService;
      const tokenObj = user ? await userDbService.getLatestUserDevToken(user) : null;

      let apiKey: string;
      let tokenName: string;
      if (tokenObj) {
        apiKey = tokenObj.token;
        tokenName = tokenObj.label;
      } else {
        // No user API key - use placeholder
        apiKey = "eyJ-xxx";
        tokenName = "No Key";
      }

      // Generate the quickstart document
      const markdown = quickstartService.generateQuickstart({
        agentFramework,
        llmVendor,
        sdkLanguage,
        apiKey,
      });

      res.send({
        markdown,
        metadata: {
          agentFramework,
          llmVendor,
          sdkLanguage,
          tokenName,
          generatedAt: new Date().toISOString(),
        },
      });
    } catch (error: unknown) {
      if (getErrorMessage(error).includes("Invalid")) {
        return res.status(400).send({ error: getErrorMessage(error) });
      }
      next(error);
    }
  }
);

/**
 * @swagger
 * /quickstart/generate-with-key:
 *   post:
 *     summary: Generate quickstart documentation with a provided API key
 *     description: Generate documentation without requiring authentication - API key is provided directly
 *     tags:
 *       - Quickstart
 *     requestBody:
 *       required: true
 *       content:
 *         application/json:
 *           schema:
 *             type: object
 *             required:
 *               - agentFramework
 *               - apiKey
 *             properties:
 *               agentFramework:
 *                 type: string
 *                 enum: [generic, livekit]
 *               apiKey:
 *                 type: string
 *                 description: The Aden API key to embed in the documentation
 *     responses:
 *       200:
 *         description: Generated quickstart documentation
 *       400:
 *         description: Invalid parameters
 */
router.post("/generate-with-key", async (req: Request, res: Response, next: NextFunction) => {
  try {
    const { agentFramework, llmVendor, sdkLanguage, apiKey } = req.body;

    if (!apiKey) {
      return res.status(400).send({
        error: "API key is required",
        message: "Please provide an apiKey in the request body",
      });
    }

    // Generate the quickstart document
    const markdown = quickstartService.generateQuickstart({
      agentFramework,
      llmVendor,
      sdkLanguage,
      apiKey,
    });

    res.send({
      markdown,
      metadata: {
        agentFramework,
        llmVendor,
        sdkLanguage,
        generatedAt: new Date().toISOString(),
      },
    });
  } catch (error: unknown) {
    if (
      getErrorMessage(error).includes("Invalid") ||
      getErrorMessage(error).includes("required")
    ) {
      return res.status(400).send({ error: getErrorMessage(error) });
    }
    next(error);
  }
});

export default router;
