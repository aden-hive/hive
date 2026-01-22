/**
 * Test Application Factory
 *
 * Creates isolated Express app instances for testing with mocked dependencies.
 */

import express, { Express, Request, Response, NextFunction } from 'express';
import cors from 'cors';
import passport from 'passport';
import { Strategy as JwtStrategy, ExtractJwt } from 'passport-jwt';
import { createMockPool, setupGlobalMongoMocks, MockPool } from './db-mocks';
import { createMockUser, createMockUserDbService, MockUser, MockUserDbService } from './auth-mocks';

const TEST_JWT_SECRET_FALLBACK = 'test-jwt-secret-for-testing-only';

function getTestJwtSecret(): string {
  return process.env.JWT_SECRET || TEST_JWT_SECRET_FALLBACK;
}

const TEST_JWT_STRATEGY_NAME = 'jwt';

/**
 * Cleanup Passport strategies registered by test apps.
 * Call this in afterEach to prevent strategy accumulation across tests.
 */
export function cleanupPassportStrategies(): void {
  try {
    passport.unuse(TEST_JWT_STRATEGY_NAME);
  } catch {
    // Strategy not found - that's fine
  }
}

export interface TestAppOptions {
  user?: MockUser;
  mockPool?: MockPool;
  dbType?: 'postgres' | 'mysql';
}

export interface TestAppResult {
  app: Express;
  mockPool: MockPool;
  mockUserDbService: MockUserDbService;
  mockUser: MockUser;
}

/**
 * Create a test application with routes mounted
 *
 * This creates a fresh Express app with mocked database connections,
 * authentication, and real routes for integration testing.
 */
export async function createFullTestApp(options: TestAppOptions = {}): Promise<TestAppResult> {
  const {
    user = createMockUser(),
    mockPool = createMockPool(),
    dbType = 'postgres',
  } = options;

  const app = express();

  // Middleware (match production order)
  app.use(cors());
  app.use(express.json({ limit: '10mb' }));
  app.use(express.urlencoded({ extended: true }));
  app.disable('x-powered-by');

  // Setup mock user database service
  const mockUserDbService = createMockUserDbService(user, { dbType });
  app.locals.userDbService = mockUserDbService;
  app.locals.pgPool = mockPool;

  // Setup Passport JWT authentication
  passport.use(new JwtStrategy({
    jwtFromRequest: ExtractJwt.fromAuthHeaderAsBearerToken(),
    secretOrKey: getTestJwtSecret(),
  }, (payload, done) => {
    done(null, payload);
  }));
  app.use(passport.initialize());

  // Setup global MongoDB mocks
  setupGlobalMongoMocks();

  // Health check endpoint
  app.get('/health', (req: Request, res: Response) => {
    res.json({
      status: 'ok',
      service: 'aden-hive',
      timestamp: new Date().toISOString(),
      userDbType: dbType,
    });
  });

  // 404 handler
  app.use((req: Request, res: Response) => {
    res.status(404).json({
      error: 'not_found',
      message: `Route ${req.method} ${req.path} not found`,
    });
  });

  // Error handler
  app.use((err: Error & { status?: number }, req: Request, res: Response, _next: NextFunction) => {
    const status = err.status || 500;
    res.status(status).json({
      error: err.name || 'Error',
      message: err.message || 'An unexpected error occurred',
    });
  });

  return {
    app,
    mockPool,
    mockUserDbService,
    mockUser: user,
  };
}
