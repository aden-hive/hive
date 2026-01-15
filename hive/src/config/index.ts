/**
 * Configuration Module
 *
 * Centralizes all configuration loading and validation.
 * Supports both MySQL (production) and PostgreSQL (local development) for user database.
 */

import fs from 'fs';

/**
 * Helper function to safely read SSL certificates
 * @param {string} envKey - Environment variable containing cert path
 * @param {string} fallbackPath - Fallback path if env var not set
 * @returns {Buffer|null} Certificate content or null
 */
function readCertificate(envKey: string, fallbackPath: string): Buffer | null {
  const certPath = process.env[envKey];
  if (certPath && fs.existsSync(certPath)) {
    return fs.readFileSync(certPath);
  }
  if (fallbackPath && fs.existsSync(fallbackPath)) {
    return fs.readFileSync(fallbackPath);
  }
  return null;
}

/**
 * Load MySQL SSL certificates from environment or default paths
 * @returns {Object|null} SSL config object or null if certs not found
 */
function loadMySQLSSL(): { ca: Buffer; key: Buffer; cert: Buffer } | null {
  const ca = readCertificate('MYSQL_SSL_CA', '/mnt/certs/mysql/server-ca.pem');
  const key = readCertificate('MYSQL_SSL_KEY', '/mnt/certs/mysql/client-key.pem');
  const cert = readCertificate('MYSQL_SSL_CERT', '/mnt/certs/mysql/client-cert.pem');

  return ca && key && cert ? { ca, key, cert } : null;
}

/**
 * Determine which database type to use for user authentication
 * Priority: USER_DB_TYPE env var > MySQL if configured > PostgreSQL fallback
 */
function getUserDbType(): 'mysql' | 'postgres' {
  const explicit = process.env.USER_DB_TYPE?.toLowerCase();
  if (explicit === 'mysql' || explicit === 'postgres') {
    return explicit;
  }
  // Default to MySQL if MySQL host is configured, otherwise use PostgreSQL
  return process.env.MYSQL_HOST ? 'mysql' : 'postgres';
}

const config = {
  // Server
  port: parseInt(process.env.PORT as string, 10) || 4000,
  nodeEnv: process.env.NODE_ENV || 'development',

  // TSDB PostgreSQL (metrics storage)
  tsdb: {
    url: process.env.TSDB_PG_URL,
  },

  // User Database Type ('mysql' or 'postgres')
  userDbType: getUserDbType(),

  // User Database (MySQL) - for production
  mysql: {
    host: process.env.MYSQL_HOST,
    port: parseInt(process.env.MYSQL_PORT as string, 10) || 3306,
    user: process.env.MYSQL_USER,
    password: process.env.MYSQL_PASSWORD,
    database: process.env.MYSQL_DATABASE,
    ssl: loadMySQLSSL(),
  },

  // User Database (PostgreSQL) - for local development
  // Defaults to same DB as TSDB if not specified
  userDb: {
    url: process.env.USER_DB_PG_URL || process.env.TSDB_PG_URL,
  },

  // MongoDB
  mongodb: {
    url: process.env.MONGODB_URL,
    dbName: process.env.MONGODB_DBNAME || 'aden',
    erpDbName: process.env.MONGODB_ERP_DBNAME || 'erp',
  },

  // Redis
  redis: {
    url: process.env.REDIS_URL,
  },

  // JWT
  jwt: {
    secret: process.env.JWT_SECRET || 'dev-secret-change-in-production',
    expiresIn: process.env.JWT_EXPIRES_IN || '7d',
    passphrase: process.env.PASSPHRASE,
  },
};

/**
 * Validates required configuration
 * @throws {Error} If required config is missing
 */
function validateConfig(): void {
  const required: [string, string | undefined][] = [
    ['TSDB_PG_URL', config.tsdb.url],
  ];

  // Add database-specific requirements
  if (config.userDbType === 'mysql') {
    required.push(
      ['MYSQL_HOST', config.mysql.host],
      ['MYSQL_USER', config.mysql.user],
      ['MYSQL_DATABASE', config.mysql.database],
    );
  } else {
    required.push(['USER_DB_PG_URL or TSDB_PG_URL', config.userDb.url]);
  }

  const missing = required.filter(([, value]) => !value);

  if (missing.length > 0) {
    const names = missing.map(([name]) => name).join(', ');
    console.warn(`[Config] Warning: Missing environment variables: ${names}`);
  }

  console.log(`[Config] User database type: ${config.userDbType}`);
}

// Validate on load
validateConfig();

export default config;
