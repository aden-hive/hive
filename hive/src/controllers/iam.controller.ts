/**
 * IAM Controller
 *
 * Handles Identity and Access Management endpoints.
 */

import { Router, Request, Response } from 'express';

const router = Router();

/**
 * Extract token from Authorization header
 * Supports: "jwt <token>", "Bearer <token>", or raw "<token>"
 */
function extractToken(authHeader: string): string {
  if (authHeader.startsWith('jwt ')) {
    return authHeader.slice(4);
  }
  if (authHeader.startsWith('Bearer ')) {
    return authHeader.slice(7);
  }
  return authHeader;
}

/**
 * GET /iam/get-current-team
 *
 * Get the current team/organization for the authenticated user.
 */
router.get('/get-current-team', async (req: Request, res: Response) => {
  try {
    const authHeader = req.headers.authorization;
    if (!authHeader) {
      return res.status(401).json({
        success: false,
        msg: 'No token provided',
      });
    }

    const userDbService = req.app.locals.userDbService;
    const user = await userDbService.findByToken(extractToken(authHeader));

    if (!user) {
      return res.status(401).json({
        success: false,
        msg: 'Invalid token',
      });
    }

    const pgPool = req.app.locals.pgPool;
    if (!pgPool) {
      // Return default team if no database
      return res.json({
        orgId: user.current_team_id || 1,
        orgName: 'Default Organization',
        teamId: user.current_team_id || 1,
        teamName: 'Default Team',
      });
    }

    // Get team info from database
    const result = await pgPool.query(
      `SELECT id, name, slug FROM teams WHERE id = $1`,
      [user.current_team_id || 1]
    );

    const team = result.rows[0];

    if (!team) {
      // Return default if team not found
      return res.json({
        orgId: user.current_team_id || 1,
        orgName: 'Default Organization',
        teamId: user.current_team_id || 1,
        teamName: 'Default Team',
      });
    }

    res.json({
      orgId: team.id,
      orgName: team.name,
      teamId: team.id,
      teamName: team.name,
    });
  } catch (err) {
    console.error('[IAMController] /get-current-team error:', err instanceof Error ? err.message : err);
    res.status(500).json({
      success: false,
      msg: 'Failed to get current team',
    });
  }
});

/**
 * GET /iam/team/get-team-role-by-id/:teamId
 *
 * Get the user's role in a specific team.
 */
router.get('/team/get-team-role-by-id/:teamId', async (req: Request, res: Response) => {
  try {
    const authHeader = req.headers.authorization;
    if (!authHeader) {
      return res.status(401).json({
        success: false,
        msg: 'No token provided',
      });
    }

    const userDbService = req.app.locals.userDbService;
    const user = await userDbService.findByToken(extractToken(authHeader));

    if (!user) {
      return res.status(401).json({
        success: false,
        msg: 'Invalid token',
      });
    }

    const teamId = parseInt(req.params.teamId, 10);

    const pgPool = req.app.locals.pgPool;
    if (!pgPool) {
      // Return default role if no database
      return res.json({ roleId: 1 });
    }

    // Get user's role in this team
    const result = await pgPool.query(
      `SELECT role FROM team_members WHERE user_id = $1 AND team_id = $2`,
      [user.id, teamId]
    );

    const membership = result.rows[0];

    // Map role name to roleId (admin=1, member=2, viewer=3)
    const roleMap: Record<string, number> = {
      admin: 1,
      member: 2,
      viewer: 3,
    };

    const roleId = membership ? (roleMap[membership.role] || 2) : 2;

    res.json({ roleId });
  } catch (err) {
    console.error('[IAMController] /team/get-team-role-by-id error:', err instanceof Error ? err.message : err);
    res.status(500).json({
      success: false,
      msg: 'Failed to get team role',
    });
  }
});

export default router;
