/**
 * User Controller
 *
 * Handles user authentication endpoints including login-v2.
 */

import { Router, Request, Response, NextFunction } from "express";
import config from "../config";

const router = Router();

/**
 * Extract token from Authorization header
 * Supports: "jwt <token>", "Bearer <token>", or raw "<token>"
 */
function extractToken(authHeader: string): string {
  if (authHeader.startsWith("jwt ")) {
    return authHeader.slice(4);
  }
  if (authHeader.startsWith("Bearer ")) {
    return authHeader.slice(7);
  }
  return authHeader;
}

// Email validation regex
const EMAIL_REGEX =
  /[\w!#$%&'*+/=?^_`{|}~-]+(?:\.[\w!#$%&'*+/=?^_`{|}~-]+)*@(?:[\w](?:[\w-]*[\w])?\.)+[\w](?:[\w-]*[\w])?/;

/**
 * POST /user/login-v2
 *
 * Authenticate a user with email and password.
 * Returns a JWT token on success.
 */
router.post(
  "/login-v2",
  async (req: Request, res: Response, next: NextFunction) => {
    try {
      let { email, password } = req.body;

      // Validate required fields
      if (
        !email ||
        typeof email !== "string" ||
        !password ||
        typeof password !== "string"
      ) {
        return res.status(400).json({
          success: false,
          msg: "Email and password are required",
        });
      }

      // Validate email format
      if (!EMAIL_REGEX.test(email)) {
        return res.status(400).json({
          success: false,
          msg: "Please enter a valid email",
        });
      }

      // Trim email
      email = email.trim().toLowerCase();

      // Validate password length
      if (password.length < 6) {
        return res.status(400).json({
          success: false,
          msg: "Password must be at least 6 characters",
        });
      }

      // Get userDbService from app.locals
      const userDbService = req.app.locals.userDbService;
      if (!userDbService) {
        console.error("[UserController] userDbService not found in app.locals");
        return res.status(500).json({
          success: false,
          msg: "Internal server error",
        });
      }

      // Attempt login
      const result = await userDbService.login(email, password, {
        jwtSecret: config.jwt.secret,
        expiresIn: config.jwt.expiresIn,
      });

      console.log(
        `[UserController] login-v2: User ${email} logged in successfully`
      );

      // Return success response
      res.json({
        success: true,
        token: result.token,
        email: result.email,
        firstname: result.firstname,
        lastname: result.lastname,
        name: result.name,
        current_team_id: result.current_team_id,
        create_time: result.created_at,
      });
    } catch (err: any) {
      console.error("[UserController] login-v2 error:", err.message);

      // Handle specific error codes
      if (err.code === "USER_NOT_FOUND") {
        return res.status(401).json({
          success: false,
          msg: "User not found. Please sign up for an account.",
        });
      }

      if (err.code === "INVALID_CREDENTIALS") {
        return res.status(401).json({
          success: false,
          msg: "Invalid email or password",
        });
      }

      if (err.code === "OAUTH_REQUIRED") {
        return res.status(400).json({
          success: false,
          msg: err.message,
        });
      }

      if (err.code === "ACCOUNT_DISABLED") {
        return res.status(403).json({
          success: false,
          msg: "Your account has been disabled",
        });
      }

      // Generic error
      return res.status(500).json({
        success: false,
        msg: "Login failed. Please try again.",
      });
    }
  }
);

/**
 * POST /user/register
 *
 * Register a new user account.
 * Returns a JWT token on success.
 */
router.post("/register", async (req: Request, res: Response) => {
  try {
    let { email, password, name, firstname, lastname } = req.body;

    // Validate required fields
    if (
      !email ||
      typeof email !== "string" ||
      !password ||
      typeof password !== "string"
    ) {
      return res.status(400).json({
        success: false,
        msg: "Email and password are required",
      });
    }

    // Validate email format
    if (!EMAIL_REGEX.test(email)) {
      return res.status(400).json({
        success: false,
        msg: "Please enter a valid email",
      });
    }

    // Trim and lowercase email
    email = email.trim().toLowerCase();

    // Validate password length
    if (password.length < 8) {
      return res.status(400).json({
        success: false,
        msg: "Password must be at least 8 characters",
      });
    }

    // Get userDbService from app.locals
    const userDbService = req.app.locals.userDbService;
    if (!userDbService) {
      console.error("[UserController] userDbService not found in app.locals");
      return res.status(500).json({
        success: false,
        msg: "Internal server error",
      });
    }

    // Attempt registration
    const result = await userDbService.register(
      { email, password, name, firstname, lastname },
      {
        jwtSecret: config.jwt.secret,
        expiresIn: config.jwt.expiresIn,
        defaultTeamId: 1, // Default to team 1 for local dev
      }
    );

    console.log(
      `[UserController] register: User ${email} registered successfully`
    );

    // Return success response
    res.status(201).json({
      success: true,
      token: result.token,
      email: result.email,
      name: result.name,
      firstname: result.firstname,
      lastname: result.lastname,
      current_team_id: result.current_team_id,
      create_time: result.created_at,
    });
  } catch (err: any) {
    console.error("[UserController] register error:", err.message);

    // Handle specific error codes
    if (err.code === "EMAIL_EXISTS") {
      return res.status(409).json({
        success: false,
        msg: "Email already registered",
      });
    }

    // Generic error
    return res.status(500).json({
      success: false,
      msg: "Registration failed. Please try again.",
    });
  }
});

/**
 * GET /user/profile
 *
 * Get current user profile.
 * Requires authentication.
 */
router.get("/profile", async (req: Request, res: Response) => {
  try {
    const authHeader = req.headers.authorization;
    if (!authHeader) {
      return res.status(401).json({
        success: false,
        msg: "No token provided",
      });
    }

    const userDbService = req.app.locals.userDbService;
    const user = await userDbService.findByToken(extractToken(authHeader));

    if (!user) {
      return res.status(401).json({
        success: false,
        msg: "Invalid token",
      });
    }

    // Return in format expected by frontend
    res.json({
      data: {
        firstname: user.firstname || "",
        lastname: user.lastname || "",
        email: user.email,
        company_name: user.company_name || null,
        profile_img_url: user.avatar_url || null,
        roleId: user.role_id || 1,
        user_id: String(user.id),
        team_id: String(user.current_team_id || 1),
        roles: user.roles || ["user"],
      },
    });
  } catch (err: any) {
    console.error("[UserController] /profile error:", err.message);
    res.status(500).json({
      success: false,
      msg: "Failed to get user profile",
    });
  }
});

/**
 * PUT /user/profile
 *
 * Update current user profile.
 * Requires authentication.
 */
router.put("/profile", async (req: Request, res: Response) => {
  try {
    const authHeader = req.headers.authorization;
    if (!authHeader) {
      return res.status(401).json({
        success: false,
        msg: "No token provided",
      });
    }

    const userDbService = req.app.locals.userDbService;
    const user = await userDbService.findByToken(extractToken(authHeader));

    if (!user) {
      return res.status(401).json({
        success: false,
        msg: "Invalid token",
      });
    }

    const { firstname, lastname } = req.body;

    // Update user profile (basic implementation)
    if (userDbService.updateProfile) {
      await userDbService.updateProfile(user.id, { firstname, lastname });
    }

    res.json({ message: "Profile updated successfully" });
  } catch (err: any) {
    console.error("[UserController] PUT /profile error:", err.message);
    res.status(500).json({
      success: false,
      msg: "Failed to update profile",
    });
  }
});

/**
 * GET /user/me
 *
 * Get current user info from token.
 * Requires authentication.
 */
router.get("/me", async (req: Request, res: Response) => {
  try {
    const authHeader = req.headers.authorization;
    if (!authHeader) {
      return res.status(401).json({
        success: false,
        msg: "No token provided",
      });
    }

    const userDbService = req.app.locals.userDbService;
    const user = await userDbService.findByToken(extractToken(authHeader));

    if (!user) {
      return res.status(401).json({
        success: false,
        msg: "Invalid token",
      });
    }

    res.json({
      success: true,
      user: {
        id: user.id,
        email: user.email,
        name: user.name,
        firstname: user.firstname,
        lastname: user.lastname,
        current_team_id: user.current_team_id,
        avatar_url: user.avatar_url,
      },
    });
  } catch (err: any) {
    console.error("[UserController] /me error:", err.message);
    res.status(500).json({
      success: false,
      msg: "Failed to get user info",
    });
  }
});

/**
 * GET /user/get-dev-tokens
 *
 * Get all developer API tokens for the current user.
 * Requires authentication.
 */
router.get("/get-dev-tokens", async (req: Request, res: Response) => {
  try {
    const authHeader = req.headers.authorization;
    if (!authHeader) {
      return res.status(401).json({
        success: false,
        msg: "No token provided",
      });
    }

    const userDbService = req.app.locals.userDbService;
    const user = await userDbService.findByToken(extractToken(authHeader));

    if (!user) {
      return res.status(401).json({
        success: false,
        msg: "Invalid token",
      });
    }

    const tokens = await userDbService.getDevTokens(user);

    res.json({
      success: true,
      data: tokens,
    });
  } catch (err: any) {
    console.error("[UserController] /get-dev-tokens error:", err.message);
    res.status(500).json({
      success: false,
      msg: "Failed to get API tokens",
    });
  }
});

/**
 * POST /user/generate-dev-token
 *
 * Generate a new developer API token.
 * Requires authentication.
 */
router.post("/generate-dev-token", async (req: Request, res: Response) => {
  try {
    const authHeader = req.headers.authorization;
    if (!authHeader) {
      return res.status(401).json({
        success: false,
        msg: "No token provided",
      });
    }

    const userDbService = req.app.locals.userDbService;
    const user = await userDbService.findByToken(extractToken(authHeader));

    if (!user) {
      return res.status(401).json({
        success: false,
        msg: "Invalid token",
      });
    }

    const { label, ttl } = req.body;

    const tokenResult = await userDbService.generateDevToken(user, {
      label,
      ttl,
      jwtSecret: config.jwt.secret,
    });

    console.log(
      `[UserController] generate-dev-token: Created token for user ${user.id}`
    );

    res.status(201).json({
      success: true,
      data: tokenResult,
    });
  } catch (err: any) {
    console.error("[UserController] /generate-dev-token error:", err.message);
    res.status(500).json({
      success: false,
      msg: "Failed to generate API token",
    });
  }
});

// =============================================================================
// UI Settings Endpoints
// =============================================================================

/**
 * Default UI settings for new users
 */
const DEFAULT_UI_SETTINGS = {
  sidebarCollapsed: false,
  performanceDashboardTimeRange: 'today',
};

/**
 * GET /user/settings
 *
 * Get user UI settings from preferences column.
 * Returns defaults if no settings exist.
 */
router.get("/settings", async (req: Request, res: Response) => {
  try {
    const authHeader = req.headers.authorization;
    if (!authHeader) {
      return res.status(401).json({
        success: false,
        msg: "No token provided",
      });
    }

    const userDbService = req.app.locals.userDbService;
    const user = await userDbService.findByToken(extractToken(authHeader));

    if (!user) {
      return res.status(401).json({
        success: false,
        msg: "Invalid token",
      });
    }

    // Extract UI settings from preferences, merge with defaults
    const preferences = user.preferences || {};
    const uiSettings = {
      sidebarCollapsed: preferences.sidebarCollapsed ?? DEFAULT_UI_SETTINGS.sidebarCollapsed,
      performanceDashboardTimeRange: preferences.performanceDashboardTimeRange ?? DEFAULT_UI_SETTINGS.performanceDashboardTimeRange,
    };

    res.json({
      success: true,
      data: uiSettings,
    });
  } catch (err: any) {
    console.error("[UserController] GET /settings error:", err.message);
    res.status(500).json({
      success: false,
      msg: "Failed to get settings",
    });
  }
});

/**
 * PUT /user/settings
 *
 * Update user UI settings in preferences column.
 * Supports partial updates - merges with existing preferences.
 */
router.put("/settings", async (req: Request, res: Response) => {
  try {
    const authHeader = req.headers.authorization;
    if (!authHeader) {
      return res.status(401).json({
        success: false,
        msg: "No token provided",
      });
    }

    const userDbService = req.app.locals.userDbService;
    const user = await userDbService.findByToken(extractToken(authHeader));

    if (!user) {
      return res.status(401).json({
        success: false,
        msg: "Invalid token",
      });
    }

    const { sidebarCollapsed, performanceDashboardTimeRange } = req.body;

    // Build update object with only provided fields
    const updates: Record<string, any> = {};
    if (typeof sidebarCollapsed === 'boolean') {
      updates.sidebarCollapsed = sidebarCollapsed;
    }
    if (performanceDashboardTimeRange !== undefined) {
      updates.performanceDashboardTimeRange = performanceDashboardTimeRange;
    }

    // Merge with existing preferences
    const currentPreferences = user.preferences || {};
    const newPreferences = { ...currentPreferences, ...updates };

    // Update in database - use pgPool for Postgres, mysqlPool for MySQL
    const pgPool = req.app.locals.pgPool;
    const mysqlPool = req.app.locals.mysqlPool;

    if (pgPool) {
      // PostgreSQL - use JSONB
      await pgPool.query(
        'UPDATE users SET preferences = $1, updated_at = NOW() WHERE id = $2',
        [JSON.stringify(newPreferences), user.id]
      );
    } else if (mysqlPool) {
      // MySQL - use JSON column
      await mysqlPool.query(
        'UPDATE user SET preferences = ?, updated_at = NOW() WHERE id = ?',
        [JSON.stringify(newPreferences), user.id]
      );
    } else {
      console.warn("[UserController] PUT /settings: No database pool available, settings not persisted");
    }

    // Return updated settings
    const uiSettings = {
      sidebarCollapsed: newPreferences.sidebarCollapsed ?? DEFAULT_UI_SETTINGS.sidebarCollapsed,
      performanceDashboardTimeRange: newPreferences.performanceDashboardTimeRange ?? DEFAULT_UI_SETTINGS.performanceDashboardTimeRange,
    };

    res.json({
      success: true,
      data: uiSettings,
    });
  } catch (err: any) {
    console.error("[UserController] PUT /settings error:", err.message);
    res.status(500).json({
      success: false,
      msg: "Failed to update settings",
    });
  }
});

export default router;
