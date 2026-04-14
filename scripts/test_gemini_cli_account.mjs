#!/usr/bin/env node
/**
 * Account sanity test for the Gemini CLI Code Assist OAuth path.
 *
 * This replicates, byte-for-byte, the HTTP flow that
 * google-gemini/gemini-cli uses when talking to cloudcode-pa.googleapis.com
 * — loadCodeAssist → (onboardUser + LRO poll) → generateContent. It exists
 * so you can verify "does my Google account actually work with the Gemini
 * CLI subscription?" independently of the Python port in hive.
 *
 * It reads OAuth tokens from ~/.hive/google-gemini-cli-accounts.json (the
 * file quickstart.sh populates) and refreshes them against oauth2.googleapis.com,
 * the same way core/google_auth.py does. It then issues one non-streaming
 * :generateContent against gemini-3-flash-preview by default.
 *
 * Request shapes are taken from the local gemini-cli checkout at
 * /Users/aden/aden/gemini-cli:
 *   packages/core/src/code_assist/setup.ts      (loadCodeAssist / onboardUser)
 *   packages/core/src/code_assist/server.ts     (endpoint + URL shape)
 *   packages/core/src/code_assist/converter.ts  (outer + inner body shape)
 *   packages/core/src/code_assist/types.ts      (UserTierId)
 *
 * Usage:
 *   node scripts/test_gemini_cli_account.mjs
 *   node scripts/test_gemini_cli_account.mjs --model gemini-3.1-pro-preview
 *   node scripts/test_gemini_cli_account.mjs --prompt "Say hi in one word."
 */

import { readFileSync, writeFileSync, existsSync } from 'node:fs';
import { homedir } from 'node:os';
import { join } from 'node:path';
import { randomUUID } from 'node:crypto';

// ---------------------------------------------------------------------------
// Constants — mirror gemini-cli code_assist/{server,setup,types}.ts
// ---------------------------------------------------------------------------

const CODE_ASSIST_ENDPOINT = 'https://cloudcode-pa.googleapis.com';
const CODE_ASSIST_API_VERSION = 'v1internal';
const TOKEN_URL = 'https://oauth2.googleapis.com/token';

const CLIENT_METADATA = {
  ideType: 'IDE_UNSPECIFIED',
  platform: 'PLATFORM_UNSPECIFIED',
  pluginType: 'GEMINI',
};

const UserTierId = {
  FREE: 'free-tier',
  LEGACY: 'legacy-tier',
  STANDARD: 'standard-tier',
};

const ACCOUNTS_FILE = join(homedir(), '.hive', 'google-gemini-cli-accounts.json');

// OAuth credentials source — identical URL to core/google_auth.py so both
// tools agree on the client_id / client_secret they fetch.
const OAUTH_CREDENTIALS_URL =
  'https://raw.githubusercontent.com/google-gemini/gemini-cli/main/packages/core/src/code_assist/oauth2.ts';

// ---------------------------------------------------------------------------
// Tiny arg parser
// ---------------------------------------------------------------------------

function parseArgs(argv) {
  const args = { model: 'gemini-3-flash-preview', prompt: 'Say hi in one word.' };
  for (let i = 2; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--model') args.model = argv[++i];
    else if (a === '--prompt') args.prompt = argv[++i];
    else if (a === '-h' || a === '--help') {
      console.log(
        'Usage: node scripts/test_gemini_cli_account.mjs [--model ID] [--prompt TEXT]',
      );
      process.exit(0);
    }
  }
  return args;
}

// ---------------------------------------------------------------------------
// Credentials: load from hive accounts file + refresh
// ---------------------------------------------------------------------------

let _oauthCreds = null;
async function fetchOAuthCreds() {
  if (_oauthCreds) return _oauthCreds;
  const envId = process.env.GOOGLE_GEMINI_CLI_CLIENT_ID;
  const envSecret = process.env.GOOGLE_GEMINI_CLI_CLIENT_SECRET;
  if (envId && envSecret) {
    _oauthCreds = { clientId: envId, clientSecret: envSecret };
    return _oauthCreds;
  }
  const res = await fetch(OAUTH_CREDENTIALS_URL, {
    headers: { 'User-Agent': 'Hive-Gemini-Test/1.0' },
  });
  const text = await res.text();
  const idMatch = text.match(
    /OAUTH_CLIENT_ID\s*=\s*\n?\s*'([a-z0-9\-\.]+\.apps\.googleusercontent\.com)'/,
  );
  const secretMatch = text.match(/OAUTH_CLIENT_SECRET\s*=\s*'([^']+)'/);
  if (!idMatch || !secretMatch) {
    throw new Error('Failed to parse OAUTH_CLIENT_ID/SECRET from gemini-cli source');
  }
  _oauthCreds = { clientId: idMatch[1], clientSecret: secretMatch[1] };
  return _oauthCreds;
}

function loadAccounts() {
  if (!existsSync(ACCOUNTS_FILE)) {
    throw new Error(
      `No credentials at ${ACCOUNTS_FILE}. Run: uv run python core/google_auth.py auth account add`,
    );
  }
  const data = JSON.parse(readFileSync(ACCOUNTS_FILE, 'utf-8'));
  const accounts = data.accounts || [];
  if (!accounts.length) throw new Error(`No accounts in ${ACCOUNTS_FILE}`);
  const account = accounts.find((a) => a.enabled !== false) || accounts[0];
  return { data, account };
}

function saveAccounts(data) {
  writeFileSync(ACCOUNTS_FILE, JSON.stringify(data, null, 2));
}

async function refreshIfNeeded(data, account) {
  const expiresAt = (account.expires || 0) / 1000;
  const now = Date.now() / 1000;
  if (account.access && expiresAt && now < expiresAt - 60) {
    return account.access;
  }
  const refreshRaw = account.refresh || '';
  const refreshToken = refreshRaw.split('|')[0];
  if (!refreshToken) {
    throw new Error('Account has no refresh_token; re-run the quickstart OAuth flow.');
  }
  const { clientId, clientSecret } = await fetchOAuthCreds();
  const body = new URLSearchParams({
    grant_type: 'refresh_token',
    refresh_token: refreshToken,
    client_id: clientId,
  });
  if (clientSecret) body.set('client_secret', clientSecret);

  const res = await fetch(TOKEN_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body,
  });
  if (!res.ok) {
    throw new Error(`Token refresh failed: HTTP ${res.status} ${await res.text()}`);
  }
  const tok = await res.json();
  account.access = tok.access_token;
  account.expires = Math.floor((Date.now() / 1000 + (tok.expires_in || 3600)) * 1000);
  saveAccounts(data);
  return account.access;
}

// ---------------------------------------------------------------------------
// Code Assist API wrappers — request shapes from setup.ts / server.ts
// ---------------------------------------------------------------------------

async function caPost(method, token, body) {
  const url = `${CODE_ASSIST_ENDPOINT}/${CODE_ASSIST_API_VERSION}:${method}`;
  const res = await fetch(url, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(body),
  });
  const text = await res.text();
  if (!res.ok) {
    throw new Error(`Code Assist ${method} HTTP ${res.status}: ${text}`);
  }
  return text ? JSON.parse(text) : {};
}

async function caGetOperation(name, token) {
  const url = `${CODE_ASSIST_ENDPOINT}/${CODE_ASSIST_API_VERSION}/${name}`;
  const res = await fetch(url, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) {
    throw new Error(`Code Assist getOperation HTTP ${res.status}: ${await res.text()}`);
  }
  return await res.json();
}

function pickOnboardTier(loadRes) {
  // setup.ts::getOnboardTier — pick the isDefault tier, fall back to LEGACY.
  for (const tier of loadRes.allowedTiers || []) {
    if (tier.isDefault) return tier.id || UserTierId.LEGACY;
  }
  return UserTierId.LEGACY;
}

async function setupUser(token) {
  const seedProject =
    process.env.GOOGLE_CLOUD_PROJECT || process.env.GOOGLE_CLOUD_PROJECT_ID || undefined;

  // setup.ts: loadCodeAssist body
  const loadBody = { metadata: { ...CLIENT_METADATA } };
  if (seedProject) {
    loadBody.cloudaicompanionProject = seedProject;
    loadBody.metadata.duetProject = seedProject;
  }
  console.log('  → :loadCodeAssist');
  const loadRes = await caPost('loadCodeAssist', token, loadBody);
  console.log(
    '  ← currentTier=',
    loadRes.currentTier?.id,
    ' project=',
    loadRes.cloudaicompanionProject?.id,
  );

  if (loadRes.currentTier && loadRes.cloudaicompanionProject?.id) {
    return loadRes.cloudaicompanionProject.id;
  }
  if (loadRes.currentTier && seedProject) {
    return seedProject;
  }

  const tierId = pickOnboardTier(loadRes);
  console.log('  → :onboardUser tier=', tierId);
  const onboardBody = { tierId, metadata: { ...CLIENT_METADATA } };
  if (tierId !== UserTierId.FREE && seedProject) {
    onboardBody.cloudaicompanionProject = seedProject;
    onboardBody.metadata.duetProject = seedProject;
  }

  let lro = await caPost('onboardUser', token, onboardBody);
  while (!lro.done) {
    if (!lro.name) break;
    console.log('  · polling LRO', lro.name);
    await new Promise((f) => setTimeout(f, 5000));
    lro = await caGetOperation(lro.name, token);
  }
  const projectId = lro.response?.cloudaicompanionProject?.id || seedProject;
  console.log('  ← onboarded, project=', projectId);
  return projectId;
}

// ---------------------------------------------------------------------------
// generateContent (non-streaming) — shape from converter.ts::toGenerateContentRequest
// ---------------------------------------------------------------------------

async function generateContent(token, model, projectId, prompt) {
  const body = {
    model, // bare model id, NOT "models/<id>" — matches req.model in converter.ts
    project: projectId,
    user_prompt_id: randomUUID(),
    request: {
      contents: [{ role: 'user', parts: [{ text: prompt }] }],
      generationConfig: { maxOutputTokens: 32, temperature: 1.0 },
      session_id: randomUUID(),
    },
  };
  console.log('  → :generateContent model=', model);
  return await caPost('generateContent', token, body);
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

async function main() {
  const args = parseArgs(process.argv);
  console.log('=== Gemini CLI account sanity test ===');
  console.log('  accounts file:', ACCOUNTS_FILE);

  const { data, account } = loadAccounts();
  console.log('  account:', account.email || '(unknown)');

  const token = await refreshIfNeeded(data, account);
  console.log('  access token OK (len', token.length + ')');

  const projectId = account.project || (await setupUser(token));
  if (projectId && account.project !== projectId) {
    account.project = projectId;
    saveAccounts(data);
    console.log('  cached project ->', projectId);
  }

  if (!projectId) {
    console.error('  FAIL: no project id resolved');
    process.exit(1);
  }

  try {
    const res = await generateContent(token, args.model, projectId, args.prompt);
    const payload = res.response || res;
    const text = (payload.candidates?.[0]?.content?.parts || [])
      .filter((p) => p.text && !p.thought)
      .map((p) => p.text)
      .join('');
    console.log('  ← response text:', JSON.stringify(text));
    console.log('  ← finishReason:', payload.candidates?.[0]?.finishReason);
    console.log('  ← usage:', JSON.stringify(payload.usageMetadata));
    console.log('\nRESULT: PASS');
  } catch (err) {
    console.error('\nRESULT: FAIL');
    console.error(err.message);
    process.exit(1);
  }
}

main().catch((err) => {
  console.error('Unexpected error:', err);
  process.exit(1);
});
