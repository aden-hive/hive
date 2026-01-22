/**
 * Authentication Mock Utilities
 *
 * Provides utilities for mocking JWT authentication and user context in tests.
 */

import jwt from 'jsonwebtoken';

const TEST_JWT_SECRET_FALLBACK = 'test-jwt-secret-for-testing-only';

function getTestJwtSecret(): string {
  return process.env.JWT_SECRET || TEST_JWT_SECRET_FALLBACK;
}

// =============================================================================
// User Factory
// =============================================================================

export interface MockUser {
  id: number;
  email: string;
  current_team_id: number;
  firstname?: string;
  lastname?: string;
  name?: string;
  roles?: string[];
}

/**
 * Create a mock user with sensible defaults
 */
export function createMockUser(overrides: Partial<MockUser> = {}): MockUser {
  return {
    id: 1,
    email: 'test@example.com',
    current_team_id: 1,
    firstname: 'Test',
    lastname: 'User',
    name: 'Test User',
    roles: ['user'],
    ...overrides,
  };
}

// =============================================================================
// JWT Token Generation
// =============================================================================

export interface TokenPayload {
  id: number;
  email: string;
  current_team_id: number;
  [key: string]: unknown;
}

/**
 * Generate a valid JWT token for testing
 */
export function generateTestToken(
  payload: Partial<TokenPayload> = {},
  options: { expiresIn?: number; secret?: string } = {}
): string {
  const { expiresIn = 3600, secret = getTestJwtSecret() } = options;

  const defaultPayload: TokenPayload = {
    id: 1,
    email: 'test@example.com',
    current_team_id: 1,
    ...payload,
  };

  return jwt.sign(defaultPayload, secret, { expiresIn } as jwt.SignOptions);
}

// =============================================================================
// Mock User Database Service
// =============================================================================

/**
 * Minimal MockUserDbService interface for testing
 */
export interface MockUserDbService {
  findByToken: jest.Mock;
  login: jest.Mock;
  dbType: 'postgres' | 'mysql';
}

/**
 * Create a mock userDbService for testing
 */
export function createMockUserDbService(
  user: MockUser = createMockUser(),
  options: { dbType?: 'postgres' | 'mysql' } = {}
): MockUserDbService {
  const { dbType = 'postgres' } = options;

  return {
    findByToken: jest.fn().mockResolvedValue(user),
    login: jest.fn().mockResolvedValue({
      token: generateTestToken({ id: user.id, email: user.email, current_team_id: user.current_team_id }),
      email: user.email,
      firstname: user.firstname,
      lastname: user.lastname,
      name: user.name,
      current_team_id: user.current_team_id,
      created_at: new Date(),
    }),
    dbType,
  };
}

// =============================================================================
// Request Headers Helper
// =============================================================================

/**
 * Create authorization header object for supertest
 */
export function authHeader(token?: string): Record<string, string> {
  const finalToken = token || generateTestToken();
  return {
    Authorization: `Bearer ${finalToken}`,
  };
}
