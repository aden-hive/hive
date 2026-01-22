import { formatEnvReportHuman, normalizeEnv, validateEnv, type EnvValidationReport } from '../config/env-schema';

export type ValidateEnvMiddlewareOptions = {
  env?: NodeJS.ProcessEnv;
  nodeEnv?: string;
};

export function validateEnvOrThrow(options: ValidateEnvMiddlewareOptions = {}): EnvValidationReport {
  const env = options.env ?? process.env;
  const report = validateEnv(env, { nodeEnv: options.nodeEnv });

  // Apply alias normalization back onto the live environment (only when validating process.env).
  if (env === process.env) {
    const normalized = normalizeEnv(env);
    for (const key of ['MONGODB_URL', 'MONGODB_URI', 'REDIS_URL', 'REDIS_HOST', 'REDIS_PORT', 'TSDB_PG_URL']) {
      if (!process.env[key] && normalized[key]) {
        process.env[key] = normalized[key];
      }
    }
  }

  // Always print the human-readable report to stdout/stderr.
  const formatted = formatEnvReportHuman(report);
  if (report.ok) {
    console.log(formatted);
  } else {
    console.error(formatted);
    throw new Error('Environment validation failed. Fix the errors above and restart.');
  }

  return report;
}
