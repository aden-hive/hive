/**
 * Health Endpoint Tests
 *
 * Example test file demonstrating how to test API endpoints with supertest.
 * Use this as a template for writing additional endpoint tests.
 */

import request from 'supertest';
import { createFullTestApp, TestAppResult } from '../utils/test-app';

describe('GET /health', () => {
  let testApp: TestAppResult;

  beforeEach(async () => {
    testApp = await createFullTestApp();
  });

  it('should return 200 OK with correct response schema', async () => {
    const response = await request(testApp.app)
      .get('/health')
      .expect(200)
      .expect('Content-Type', /application\/json/);

    expect(response.body).toMatchObject({
      status: 'ok',
      service: 'aden-hive',
      timestamp: expect.any(String),
      userDbType: 'postgres',
    });
  });

  it('should not require authentication', async () => {
    const response = await request(testApp.app)
      .get('/health')
      .expect(200);

    expect(response.body.status).toBe('ok');
  });

  it('should reflect database type configuration', async () => {
    const mysqlApp = await createFullTestApp({ dbType: 'mysql' });

    const response = await request(mysqlApp.app)
      .get('/health')
      .expect(200);

    expect(response.body.userDbType).toBe('mysql');
  });
});
