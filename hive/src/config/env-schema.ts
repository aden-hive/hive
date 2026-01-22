export type EnvValidationSeverity = 'error' | 'warning';

export type EnvValidationIssue = {
  severity: EnvValidationSeverity;
  key: string;
  message: string;
  example?: string;
  howToFix?: string;
};

export type EnvValidationReport = {
  ok: boolean;
  timestamp: string;
  nodeEnv: string;
  normalizedEnv: Record<string, string>;
  errors: EnvValidationIssue[];
  warnings: EnvValidationIssue[];
};

type ValidateEnvOptions = {
  nodeEnv?: string;
};

function isNonEmpty(value: unknown): value is string {
  return typeof value === 'string' && value.trim().length > 0;
}

function isValidPort(value: string): boolean {
  const n = Number(value);
  return Number.isInteger(n) && n >= 1 && n <= 65535;
}

function isValidUrl(value: string): boolean {
  try {
    // eslint-disable-next-line no-new
    new URL(value);
    return true;
  } catch {
    return false;
  }
}

function validateMongoUrl(value: string): boolean {
  // URL() does not understand the mongodb scheme unless it is explicitly supported.
  // We still do basic format checks to catch obvious misconfigurations.
  return (
    value.startsWith('mongodb://') ||
    value.startsWith('mongodb+srv://')
  );
}

function parseRedisUrl(value: string): { host: string; port: string } | null {
  try {
    const u = new URL(value);
    if (!u.hostname) return null;
    const port = u.port || '6379';
    return { host: u.hostname, port };
  } catch {
    return null;
  }
}

function redactEnvForReport(normalizedEnv: Record<string, string>): Record<string, string> {
  const redacted: Record<string, string> = {};
  const secretKeys = new Set([
    'JWT_SECRET',
    'PASSPHRASE',
    'MYSQL_PASSWORD',
    'POSTGRES_PASSWORD',
  ]);

  for (const [k, v] of Object.entries(normalizedEnv)) {
    if (secretKeys.has(k)) {
      redacted[k] = v ? `**redacted** (len=${v.length})` : '';
    } else {
      redacted[k] = v;
    }
  }
  return redacted;
}

function pushIssue(
  list: EnvValidationIssue[],
  issue: Omit<EnvValidationIssue, 'severity'> & { severity?: EnvValidationSeverity },
) {
  list.push({ severity: issue.severity ?? 'error', ...issue });
}

export function normalizeEnv(inputEnv: NodeJS.ProcessEnv): Record<string, string> {
  const normalizedEnv: Record<string, string> = {};

  for (const [k, v] of Object.entries(inputEnv)) {
    if (typeof v === 'string') normalizedEnv[k] = v;
  }

  // Mongo
  if (!isNonEmpty(normalizedEnv.MONGODB_URL) && isNonEmpty(normalizedEnv.MONGODB_URI)) {
    normalizedEnv.MONGODB_URL = normalizedEnv.MONGODB_URI;
  }
  if (!isNonEmpty(normalizedEnv.MONGODB_URI) && isNonEmpty(normalizedEnv.MONGODB_URL)) {
    normalizedEnv.MONGODB_URI = normalizedEnv.MONGODB_URL;
  }

  // Redis
  if (!isNonEmpty(normalizedEnv.REDIS_URL)) {
    const host = normalizedEnv.REDIS_HOST;
    const port = normalizedEnv.REDIS_PORT;
    if (isNonEmpty(host) && isNonEmpty(port)) {
      normalizedEnv.REDIS_URL = `redis://${host}:${port}`;
    }
  }

  if (isNonEmpty(normalizedEnv.REDIS_URL) && (!isNonEmpty(normalizedEnv.REDIS_HOST) || !isNonEmpty(normalizedEnv.REDIS_PORT))) {
    const parsed = parseRedisUrl(normalizedEnv.REDIS_URL);
    if (parsed) {
      if (!isNonEmpty(normalizedEnv.REDIS_HOST)) normalizedEnv.REDIS_HOST = parsed.host;
      if (!isNonEmpty(normalizedEnv.REDIS_PORT)) normalizedEnv.REDIS_PORT = parsed.port;
    }
  }

  if (!isNonEmpty(normalizedEnv.TSDB_PG_URL)) {
    const host = normalizedEnv.POSTGRES_HOST;
    const port = normalizedEnv.POSTGRES_PORT;
    const user = normalizedEnv.POSTGRES_USER;
    const password = normalizedEnv.POSTGRES_PASSWORD;
    const db = normalizedEnv.POSTGRES_DB;
    if (isNonEmpty(host) && isNonEmpty(port) && isNonEmpty(user) && isNonEmpty(password) && isNonEmpty(db)) {
      normalizedEnv.TSDB_PG_URL = `postgresql://${encodeURIComponent(user)}:${encodeURIComponent(password)}@${host}:${port}/${db}`;
    }
  }

  return normalizedEnv;
}

/**
 * Validate runtime env vars and normalize common aliases.
 *
 * This function is intentionally dependency-free (no zod) so it can be reused
 * from both runtime code and root-level scripts.
 */
export function validateEnv(
  inputEnv: NodeJS.ProcessEnv,
  options: ValidateEnvOptions = {},
): EnvValidationReport {
  const nodeEnv = (options.nodeEnv ?? inputEnv.NODE_ENV ?? 'development').toString();
  const normalizedEnv = normalizeEnv(inputEnv);

  const errors: EnvValidationIssue[] = [];
  const warnings: EnvValidationIssue[] = [];

  // Required runtime env vars (strict, fail-fast)
  if (!isNonEmpty(normalizedEnv.TSDB_PG_URL)) {
    const pgPieces: Array<[string, string | undefined, string]> = [
      ['POSTGRES_HOST', normalizedEnv.POSTGRES_HOST, 'localhost'],
      ['POSTGRES_PORT', normalizedEnv.POSTGRES_PORT, '5432'],
      ['POSTGRES_USER', normalizedEnv.POSTGRES_USER, 'postgres'],
      ['POSTGRES_PASSWORD', normalizedEnv.POSTGRES_PASSWORD, 'postgres'],
      ['POSTGRES_DB', normalizedEnv.POSTGRES_DB, 'aden_tsdb'],
    ];
    const missingPieces = pgPieces.filter(([, v]) => !isNonEmpty(v)).map(([k]) => k);

    pushIssue(errors, {
      key: 'TSDB_PG_URL',
      message: missingPieces.length > 0
        ? `Missing TimescaleDB connection string (or missing Postgres vars: ${missingPieces.join(', ')}).`
        : 'Missing TimescaleDB connection string.',
      example: 'postgresql://postgres:postgres@localhost:5432/aden_tsdb',
      howToFix: 'Set TSDB_PG_URL (preferred) or set POSTGRES_HOST/PORT/USER/PASSWORD/DB, or update config.yaml and run: npm run generate:env',
    });
  } else {
    // postgresql:// is not a WHATWG URL scheme, but URL() still accepts it.
    if (!isValidUrl(normalizedEnv.TSDB_PG_URL)) {
      pushIssue(errors, {
        key: 'TSDB_PG_URL',
        message: 'Invalid TSDB_PG_URL. Must be a valid URL string.',
        example: 'postgresql://postgres:postgres@localhost:5432/aden_tsdb',
        howToFix: 'Fix the value in your .env or config.yaml then regenerate env files.',
      });
    }
  }

  if (!isNonEmpty(normalizedEnv.MONGODB_URL) && !isNonEmpty(normalizedEnv.MONGODB_URI)) {
    pushIssue(errors, {
      key: 'MONGODB_URI',
      message: 'Missing MongoDB connection string.',
      example: 'mongodb://localhost:27017',
      howToFix: 'Set MONGODB_URI (or MONGODB_URL) or update config.yaml and run: npm run generate:env',
    });
  } else {
    const mongoUri = normalizedEnv.MONGODB_URL || normalizedEnv.MONGODB_URI;
    if (mongoUri && !validateMongoUrl(mongoUri)) {
    pushIssue(errors, {
      key: 'MONGODB_URI',
      message: 'Invalid MongoDB URI. Must start with mongodb:// or mongodb+srv://',
      example: 'mongodb://localhost:27017',
      howToFix: 'Fix the MongoDB URI in your .env or config.yaml then regenerate env files.',
    });
    }
  }

  if (!isNonEmpty(normalizedEnv.REDIS_URL) && !(isNonEmpty(normalizedEnv.REDIS_HOST) && isNonEmpty(normalizedEnv.REDIS_PORT))) {
    pushIssue(errors, {
      key: 'REDIS_HOST',
      message: 'Missing Redis connection string.',
      example: 'redis://localhost:6379',
      howToFix: 'Set REDIS_HOST and REDIS_PORT (or set REDIS_URL) or update config.yaml and run: npm run generate:env',
    });
  } else {
    const redisUrl = normalizedEnv.REDIS_URL;
    if (redisUrl && !isValidUrl(redisUrl)) {
      pushIssue(errors, {
        key: 'REDIS_URL',
        message: 'Invalid REDIS_URL. Must be a valid URL string.',
        example: 'redis://localhost:6379',
        howToFix: 'Fix REDIS_URL in your .env or config.yaml then regenerate env files.',
      });
    }
  }

  if (isNonEmpty(normalizedEnv.REDIS_PORT) && !isValidPort(normalizedEnv.REDIS_PORT)) {
    pushIssue(errors, {
      key: 'REDIS_PORT',
      message: 'Invalid REDIS_PORT. Must be an integer between 1 and 65535.',
      example: '6379',
      howToFix: 'Set REDIS_PORT to a valid value or remove it and use REDIS_URL instead.',
    });
  }

  if (!isNonEmpty(normalizedEnv.JWT_SECRET)) {
    pushIssue(errors, {
      key: 'JWT_SECRET',
      message: 'Missing JWT secret.',
      example: 'openssl rand -base64 32',
      howToFix: 'Set JWT_SECRET (or update auth.jwt_secret in config.yaml and run: npm run generate:env).',
    });
  } else if (nodeEnv === 'production' && normalizedEnv.JWT_SECRET.length < 32) {
    pushIssue(errors, {
      key: 'JWT_SECRET',
      message: 'JWT_SECRET is too short for production. Minimum 32 characters recommended.',
      example: 'openssl rand -base64 32',
      howToFix: 'Generate a strong secret and set JWT_SECRET, then redeploy.',
    });
  }

  if (!isNonEmpty(normalizedEnv.PASSPHRASE)) {
    pushIssue(warnings, {
      severity: 'warning',
      key: 'PASSPHRASE',
      message: 'Missing PASSPHRASE. Some encryption features may be degraded.',
      example: 'openssl rand -base64 32',
      howToFix: 'Set PASSPHRASE (or update auth.passphrase in config.yaml and run: npm run generate:env).',
    });
  }

  // Database selection requirements match hive/src/config/index.ts
  const explicitDbType = normalizedEnv.USER_DB_TYPE?.toLowerCase();
  const userDbType = (explicitDbType === 'mysql' || explicitDbType === 'postgres')
    ? explicitDbType
    : (isNonEmpty(normalizedEnv.MYSQL_HOST) ? 'mysql' : 'postgres');

  if (userDbType === 'mysql') {
    const mysqlRequired: Array<[string, string | undefined, string]> = [
      ['MYSQL_HOST', normalizedEnv.MYSQL_HOST, 'localhost'],
      ['MYSQL_USER', normalizedEnv.MYSQL_USER, 'root'],
      ['MYSQL_DATABASE', normalizedEnv.MYSQL_DATABASE, 'hive'],
    ];
    for (const [key, value, example] of mysqlRequired) {
      if (!isNonEmpty(value)) {
        pushIssue(errors, {
          key,
          message: `Missing ${key} required for USER_DB_TYPE=mysql.`,
          example,
          howToFix: 'Set the MySQL env vars or switch USER_DB_TYPE to postgres for local development.',
        });
      }
    }
  } else {
    if (!isNonEmpty(normalizedEnv.USER_DB_PG_URL) && !isNonEmpty(normalizedEnv.TSDB_PG_URL)) {
      pushIssue(errors, {
        key: 'USER_DB_PG_URL',
        message: 'Missing Postgres connection string for user database.',
        example: 'postgresql://postgres:postgres@localhost:5432/aden_tsdb',
        howToFix: 'Set USER_DB_PG_URL or rely on TSDB_PG_URL (same database) for local development.',
      });
    }
  }

  const report: EnvValidationReport = {
    ok: errors.length === 0,
    timestamp: new Date().toISOString(),
    nodeEnv,
    normalizedEnv: redactEnvForReport(normalizedEnv),
    errors,
    warnings,
  };

  return report;
}

export function formatEnvReportHuman(report: EnvValidationReport): string {
  const lines: string[] = [];
  lines.push(`[Env] Validation ${report.ok ? 'passed' : 'failed'} (${report.nodeEnv})`);
  lines.push(`[Env] Timestamp: ${report.timestamp}`);

  if (report.errors.length > 0) {
    lines.push('');
    lines.push(`[Env] Errors (${report.errors.length}):`);
    for (const e of report.errors) {
      lines.push(`- ${e.key}: ${e.message}`);
      if (e.example) lines.push(`  example: ${e.example}`);
      if (e.howToFix) lines.push(`  fix: ${e.howToFix}`);
    }
  }

  if (report.warnings.length > 0) {
    lines.push('');
    lines.push(`[Env] Warnings (${report.warnings.length}):`);
    for (const w of report.warnings) {
      lines.push(`- ${w.key}: ${w.message}`);
      if (w.example) lines.push(`  example: ${w.example}`);
      if (w.howToFix) lines.push(`  fix: ${w.howToFix}`);
    }
  }

  return lines.join('\n');
}
