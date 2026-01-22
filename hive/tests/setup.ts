/**
 * Jest Global Setup
 *
 * Configures environment variables and global mocks before all tests.
 */

import { clearGlobalMongoMocks } from './utils/db-mocks';
import { cleanupPassportStrategies } from './utils/test-app';

// Set test environment variables before any imports
process.env.NODE_ENV = 'test';
process.env.PORT = '4001';
process.env.JWT_SECRET = 'test-jwt-secret-for-testing-only';
process.env.JWT_EXPIRES_IN = '1h';

// Cleanup after each test to prevent state leakage
afterEach(() => {
  jest.clearAllMocks();
  clearGlobalMongoMocks();
  cleanupPassportStrategies();
});

// Final cleanup after all tests complete
afterAll(() => {
  clearGlobalMongoMocks();
  cleanupPassportStrategies();
});

export {};
