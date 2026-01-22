/**
 * Database Mock Utilities
 *
 * Provides mock factories for PostgreSQL and MongoDB connections.
 * Use these to create isolated test environments without real database connections.
 */

import { QueryResult } from 'pg';

// =============================================================================
// PostgreSQL Mocks
// =============================================================================

export interface MockQueryResult<T = Record<string, unknown>> extends Partial<QueryResult<T>> {
  rows: T[];
  rowCount?: number;
}

export interface MockPoolClient {
  query: jest.Mock;
  release: jest.Mock;
}

export interface MockPool {
  connect: jest.Mock<Promise<MockPoolClient>>;
  query: jest.Mock;
  end: jest.Mock;
}

/**
 * Create a mock PostgreSQL pool client
 */
export function createMockPoolClient(defaultRows: unknown[] = []): MockPoolClient {
  return {
    query: jest.fn().mockResolvedValue({ rows: defaultRows, rowCount: defaultRows.length }),
    release: jest.fn(),
  };
}

/**
 * Create a mock PostgreSQL pool
 */
export function createMockPool(defaultRows: unknown[] = []): MockPool {
  return {
    connect: jest.fn().mockImplementation(() => {
      return Promise.resolve(createMockPoolClient(defaultRows));
    }),
    query: jest.fn().mockResolvedValue({ rows: defaultRows, rowCount: defaultRows.length }),
    end: jest.fn().mockResolvedValue(undefined),
  };
}

// =============================================================================
// MongoDB Mocks
// =============================================================================

export interface MockCollection {
  find: jest.Mock;
  findOne: jest.Mock;
  insertOne: jest.Mock;
  updateOne: jest.Mock;
  deleteOne: jest.Mock;
}

export interface MockDb {
  collection: jest.Mock<MockCollection>;
}

export interface MockMongoClient {
  connect: jest.Mock;
  db: jest.Mock<MockDb>;
  close: jest.Mock;
}

/**
 * Create a mock MongoDB collection
 */
export function createMockCollection(defaultDocs: unknown[] = []): MockCollection {
  const cursor = {
    toArray: jest.fn().mockResolvedValue(defaultDocs),
  };

  return {
    find: jest.fn().mockReturnValue(cursor),
    findOne: jest.fn().mockResolvedValue(defaultDocs[0] || null),
    insertOne: jest.fn().mockResolvedValue({ insertedId: 'mock-id' }),
    updateOne: jest.fn().mockResolvedValue({ matchedCount: 1, modifiedCount: 1 }),
    deleteOne: jest.fn().mockResolvedValue({ deletedCount: 1 }),
  };
}

/**
 * Create a mock MongoDB database
 */
export function createMockDb(collections: Record<string, MockCollection> = {}): MockDb {
  return {
    collection: jest.fn().mockImplementation((name: string) => {
      return collections[name] || createMockCollection();
    }),
  };
}

/**
 * Create a mock MongoDB client
 */
export function createMockMongoClient(dbs: Record<string, MockDb> = {}): MockMongoClient {
  return {
    connect: jest.fn().mockResolvedValue(undefined),
    db: jest.fn().mockImplementation((name: string) => {
      return dbs[name] || createMockDb();
    }),
    close: jest.fn().mockResolvedValue(undefined),
  };
}

/**
 * Setup global MongoDB mocks (for services that use global._ACHO_MG_DB)
 */
export function setupGlobalMongoMocks(collections: Record<string, MockCollection> = {}): void {
  const mockDb = createMockDb(collections);
  const mockClient = createMockMongoClient({ erp: mockDb, aden: mockDb });

  (global as Record<string, unknown>)._ACHO_MG_DB = mockClient;
  (global as Record<string, unknown>)._ACHO_MDB_CONFIG = {
    ERP_DBNAME: 'erp',
    DBNAME: 'aden',
  };
  (global as Record<string, unknown>)._ACHO_MDB_COLLECTIONS = {
    ADEN_CONTROL_POLICIES: 'aden_control_policies',
    ADEN_CONTROL_CONTENT: 'aden_control_content',
    LLM_PRICING: 'llm_pricing',
  };
}

/**
 * Clear global MongoDB mocks
 */
export function clearGlobalMongoMocks(): void {
  delete (global as Record<string, unknown>)._ACHO_MG_DB;
  delete (global as Record<string, unknown>)._ACHO_MDB_CONFIG;
  delete (global as Record<string, unknown>)._ACHO_MDB_COLLECTIONS;
}
