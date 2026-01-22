/**
 * Environment Validation CLI
 *
 * Validates runtime environment variables and prints a human-readable report.
 * If --json is provided, also writes a JSON artifact (useful for CI/monitoring).
 *
 * Usage:
 *   npx tsx scripts/validate-config.ts
 *   npx tsx scripts/validate-config.ts --json
 *   npx tsx scripts/validate-config.ts --json=./artifacts/env-report.json
 */

import { mkdirSync, writeFileSync } from 'fs';
import { dirname, resolve } from 'path';

import { formatEnvReportHuman, validateEnv } from '../hive/src/config/env-schema';

function getJsonPathFromArgs(argv: string[]): string | null {
  const arg = argv.find((a) => a === '--json' || a.startsWith('--json='));
  if (!arg) return null;
  if (arg === '--json') return resolve(process.cwd(), 'logs', 'env-validation.json');
  const [, value] = arg.split('=', 2);
  return resolve(process.cwd(), value);
}

function main() {
  const jsonPath = getJsonPathFromArgs(process.argv.slice(2));
  const report = validateEnv(process.env);

  const human = formatEnvReportHuman(report);
  if (report.ok) console.log(human);
  else console.error(human);

  if (jsonPath) {
    mkdirSync(dirname(jsonPath), { recursive: true });
    writeFileSync(jsonPath, `${JSON.stringify(report, null, 2)}\n`, 'utf-8');
    console.log(`[Env] Wrote JSON report: ${jsonPath}`);
  }

  process.exit(report.ok ? 0 : 1);
}

main();
