#!/usr/bin/env bun

/**
 * Bounty Tracker — calculates points from merged PRs and generates leaderboards.
 *
 * Modes:
 *   notify  — Post a Discord message for a single completed bounty (called by bounty-completed.yml)
 *   leaderboard — Generate and post the weekly leaderboard (called by weekly-leaderboard.yml)
 *
 * Environment:
 *   GITHUB_TOKEN               — GitHub API token
 *   GITHUB_REPOSITORY_OWNER    — e.g. "adenhq"
 *   GITHUB_REPOSITORY_NAME     — e.g. "hive"
 *   DISCORD_WEBHOOK_URL        — Discord webhook for #integrations-announcements
 *   LURKR_API_KEY              — Lurkr Read/Write API key (for XP push)
 *   LURKR_GUILD_ID             — Discord server ID where Lurkr is installed
 *   PR_NUMBER                  — (notify mode) The merged PR number
 */

import { readFileSync } from "fs";
import { join } from "path";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface Contributor {
  github: string;
  discord: string;
  name?: string;
}

interface GitHubLabel {
  name: string;
}

interface GitHubUser {
  login: string;
}

interface GitHubPR {
  number: number;
  title: string;
  merged_at: string | null;
  labels: GitHubLabel[];
  user: GitHubUser;
  html_url: string;
}

interface BountyResult {
  pr: GitHubPR;
  bountyType: string;
  points: number;
  difficulty: string;
  contributor: string;
  discordId: string | null;
}

interface LeaderboardEntry {
  github: string;
  discordId: string | null;
  points: number;
  bounties: number;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const POINTS: Record<string, number> = {
  "bounty:test": 20,
  "bounty:docs": 20,
  "bounty:code": 30,
  "bounty:new-tool": 75,
};

// ---------------------------------------------------------------------------
// GitHub API
// ---------------------------------------------------------------------------

async function githubRequest<T>(
  endpoint: string,
  token: string,
  method: string = "GET",
  body?: unknown
): Promise<T> {
  const headers: Record<string, string> = {
    Authorization: `Bearer ${token}`,
    Accept: "application/vnd.github.v3+json",
    "User-Agent": "bounty-tracker",
  };

  if (body) {
    headers["Content-Type"] = "application/json";
  }

  const options: RequestInit = { method, headers };
  if (body) {
    options.body = JSON.stringify(body);
  }

  const response = await fetch(`https://api.github.com${endpoint}`, options);

  if (!response.ok) {
    throw new Error(
      `GitHub API request failed: ${response.status} ${response.statusText}`
    );
  }

  return response.json();
}

async function getPR(
  owner: string,
  repo: string,
  prNumber: number,
  token: string
): Promise<GitHubPR> {
  return githubRequest<GitHubPR>(
    `/repos/${owner}/${repo}/pulls/${prNumber}`,
    token
  );
}

async function getMergedBountyPRs(
  owner: string,
  repo: string,
  token: string,
  since?: string
): Promise<GitHubPR[]> {
  // GitHub search API requires each label with special chars to be quoted individually.
  // Multiple label: qualifiers are OR'd together.
  const bountyLabels = Object.keys(POINTS)
    .map((l) => `label:"${l}"`)
    .join(" ");

  const query = `repo:${owner}/${repo} is:pr is:merged ${bountyLabels}${since ? ` merged:>=${since}` : ""}`;

  const result = await githubRequest<{ items: GitHubPR[] }>(
    `/search/issues?q=${encodeURIComponent(query)}&per_page=100&sort=updated&order=desc`,
    token
  );

  return result.items;
}

// ---------------------------------------------------------------------------
// Identity resolution
// ---------------------------------------------------------------------------

// Parse contributors.yml without a YAML dependency.
// The format is simple enough to parse with regex:
//   contributors:
//     - github: jane-doe
//       discord: "123456789012345678"
//       name: Jane Doe
function parseContributorsYaml(raw: string): Contributor[] {
  const contributors: Contributor[] = [];
  let current: Partial<Contributor> | null = null;

  for (const line of raw.split("\n")) {
    const trimmed = line.trim();

    if (trimmed.startsWith("- github:")) {
      if (current?.github && current?.discord) {
        contributors.push(current as Contributor);
      }
      current = { github: trimmed.replace("- github:", "").trim() };
    } else if (trimmed.startsWith("discord:") && current) {
      current.discord = trimmed.replace("discord:", "").trim().replace(/^["']|["']$/g, "");
    } else if (trimmed.startsWith("name:") && current) {
      current.name = trimmed.replace("name:", "").trim();
    }
  }

  // Don't forget the last entry
  if (current?.github && current?.discord) {
    contributors.push(current as Contributor);
  }

  return contributors;
}

function loadContributors(): Map<string, Contributor> {
  const map = new Map<string, Contributor>();

  try {
    // Resolve path relative to the script location (scripts/ dir → repo root)
    const scriptDir = new URL(".", import.meta.url).pathname;
    const raw = readFileSync(
      join(scriptDir, "..", "contributors.yml"),
      "utf-8"
    );
    const entries = parseContributorsYaml(raw);

    for (const c of entries) {
      map.set(c.github.toLowerCase(), c);
    }
  } catch {
    console.warn("Warning: could not load contributors.yml");
  }

  return map;
}

function resolveDiscord(
  githubUsername: string,
  contributors: Map<string, Contributor>
): string | null {
  const entry = contributors.get(githubUsername.toLowerCase());
  return entry?.discord ?? null;
}

// ---------------------------------------------------------------------------
// Bounty extraction
// ---------------------------------------------------------------------------

function extractBounty(
  pr: GitHubPR,
  contributors: Map<string, Contributor>
): BountyResult | null {
  const labels = pr.labels.map((l) => l.name);

  const bountyLabel = labels.find((l) => l.startsWith("bounty:"));
  if (!bountyLabel) return null;

  const points = POINTS[bountyLabel];
  if (points === undefined) return null;

  const difficulty =
    labels.find((l) => l.startsWith("difficulty:"))?.replace("difficulty:", "") ??
    "unknown";

  return {
    pr,
    bountyType: bountyLabel.replace("bounty:", ""),
    points,
    difficulty,
    contributor: pr.user.login,
    discordId: resolveDiscord(pr.user.login, contributors),
  };
}

// ---------------------------------------------------------------------------
// Discord notifications
// ---------------------------------------------------------------------------

async function postToDiscord(
  webhookUrl: string,
  content: string,
  embeds?: unknown[]
): Promise<void> {
  const body: Record<string, unknown> = { content };
  if (embeds) body.embeds = embeds;

  const response = await fetch(webhookUrl, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    throw new Error(
      `Discord webhook failed: ${response.status} ${response.statusText}`
    );
  }
}

function formatBountyNotification(bounty: BountyResult): string {
  const userMention = bounty.discordId
    ? `<@${bounty.discordId}>`
    : `**${bounty.contributor}**`;

  const typeEmoji: Record<string, string> = {
    test: "\u{1F9EA}",
    docs: "\u{1F4DD}",
    code: "\u{1F527}",
    "new-tool": "\u{2B50}",
  };

  const emoji = typeEmoji[bounty.bountyType] ?? "\u{1F3AF}";

  let msg = `${emoji} **Bounty Completed!**\n\n`;
  msg += `${userMention} completed a **${bounty.bountyType}** bounty (+${bounty.points} pts)\n`;
  msg += `PR: ${bounty.pr.html_url}\n`;

  if (!bounty.discordId) {
    msg += `\n_\u{1F517} @${bounty.contributor}: link your Discord in \`contributors.yml\` to get pinged!_`;
  }

  return msg;
}

function formatLeaderboard(entries: LeaderboardEntry[]): string {
  if (entries.length === 0) {
    return "No bounty completions this period.";
  }

  const sorted = [...entries].sort((a, b) => b.points - a.points);
  const top10 = sorted.slice(0, 10);

  const medals = ["\u{1F947}", "\u{1F948}", "\u{1F949}"];

  let msg = "**\u{1F3C6} Integration Bounty Leaderboard**\n\n";

  for (let i = 0; i < top10.length; i++) {
    const entry = top10[i];
    const rank = medals[i] ?? `**${i + 1}.**`;
    const name = entry.discordId
      ? `<@${entry.discordId}>`
      : `**${entry.github}**`;
    msg += `${rank} ${name} — ${entry.points} pts (${entry.bounties} bounties)\n`;
  }

  msg += `\n_${sorted.length} contributors total_`;

  return msg;
}

// ---------------------------------------------------------------------------
// Lurkr API — push XP to Discord leveling system
// ---------------------------------------------------------------------------

const LURKR_BASE_URL = "https://api.lurkr.gg/v2";

interface LurkrLevelResponse {
  level: {
    level: number;
    xp: number;
    messageCount: number;
  };
}

async function lurkrAddXP(
  guildId: string,
  userId: string,
  xp: number,
  apiKey: string
): Promise<LurkrLevelResponse> {
  const response = await fetch(
    `${LURKR_BASE_URL}/levels/${guildId}/users/${userId}`,
    {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
        "X-API-Key": apiKey,
      },
      body: JSON.stringify({ xp: { increment: xp } }),
    }
  );

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`Lurkr API failed: ${response.status} ${text}`);
  }

  return response.json();
}

async function lurkrGetUser(
  guildId: string,
  userId: string,
  apiKey: string
): Promise<LurkrLevelResponse | null> {
  const response = await fetch(
    `${LURKR_BASE_URL}/levels/${guildId}/users/${userId}`,
    {
      method: "GET",
      headers: { "X-API-Key": apiKey },
    }
  );

  if (response.status === 404) return null;

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`Lurkr API failed: ${response.status} ${text}`);
  }

  return response.json();
}

async function awardLurkrXP(bounty: BountyResult): Promise<string | null> {
  const apiKey = process.env.LURKR_API_KEY;
  const guildId = process.env.LURKR_GUILD_ID;

  if (!apiKey || !guildId) {
    console.log("Lurkr not configured (missing LURKR_API_KEY or LURKR_GUILD_ID), skipping XP push");
    return null;
  }

  if (!bounty.discordId) {
    console.log(`No Discord ID for @${bounty.contributor}, cannot push Lurkr XP`);
    return null;
  }

  try {
    const result = await lurkrAddXP(guildId, bounty.discordId, bounty.points, apiKey);
    const msg = `Lurkr: +${bounty.points} XP \u2192 <@${bounty.discordId}> (now level ${result.level.level}, ${result.level.xp} XP)`;
    console.log(msg);
    return msg;
  } catch (err) {
    // Lurkr failure should not prevent the Discord notification from being sent
    console.error(`Lurkr XP push failed (non-fatal): ${err}`);
    return null;
  }
}

// ---------------------------------------------------------------------------
// Leaderboard calculation
// ---------------------------------------------------------------------------

function buildLeaderboard(
  bounties: BountyResult[]
): LeaderboardEntry[] {
  const map = new Map<string, LeaderboardEntry>();

  for (const b of bounties) {
    const key = b.contributor.toLowerCase();
    const existing = map.get(key);

    if (existing) {
      existing.points += b.points;
      existing.bounties += 1;
    } else {
      map.set(key, {
        github: b.contributor,
        discordId: b.discordId,
        points: b.points,
        bounties: 1,
      });
    }
  }

  return Array.from(map.values());
}

// ---------------------------------------------------------------------------
// CLI
// ---------------------------------------------------------------------------

async function main() {
  const mode = process.argv[2];

  const token = process.env.GITHUB_TOKEN;
  const owner = process.env.GITHUB_REPOSITORY_OWNER;
  const repo = process.env.GITHUB_REPOSITORY_NAME;
  const webhookUrl = process.env.DISCORD_WEBHOOK_URL;

  if (!token || !owner || !repo) {
    console.error(
      "Missing required env: GITHUB_TOKEN, GITHUB_REPOSITORY_OWNER, GITHUB_REPOSITORY_NAME"
    );
    process.exit(1);
  }

  const contributors = loadContributors();

  if (mode === "notify") {
    // Single bounty notification
    const prNumber = parseInt(process.env.PR_NUMBER ?? "", 10);
    if (!prNumber) {
      console.error("Missing PR_NUMBER env var");
      process.exit(1);
    }

    const pr = await getPR(owner, repo, prNumber, token);
    if (!pr.merged_at) {
      console.log("PR not merged, skipping");
      return;
    }

    const bounty = extractBounty(pr, contributors);
    if (!bounty) {
      console.log("No bounty label found, skipping");
      return;
    }

    console.log(
      `Bounty: ${bounty.bountyType} | ${bounty.points} pts | @${bounty.contributor}`
    );

    // Push XP to Lurkr (before Discord notification so we can include level info)
    const lurkrMsg = await awardLurkrXP(bounty);

    if (webhookUrl) {
      let msg = formatBountyNotification(bounty);
      if (lurkrMsg) {
        msg += `\n${lurkrMsg}`;
      }
      await postToDiscord(webhookUrl, msg);
      console.log("Discord notification sent");
    } else {
      console.log("No DISCORD_WEBHOOK_URL set, skipping Discord notification");
      console.log(formatBountyNotification(bounty));
    }
  } else if (mode === "leaderboard") {
    // Weekly leaderboard
    const since = process.env.SINCE_DATE;
    const prs = await getMergedBountyPRs(owner, repo, token, since);

    console.log(`Found ${prs.length} merged bounty PRs`);

    const bounties = prs
      .map((pr) => extractBounty(pr, contributors))
      .filter((b): b is BountyResult => b !== null);

    const entries = buildLeaderboard(bounties);
    const msg = formatLeaderboard(entries);

    console.log(msg);

    if (webhookUrl) {
      await postToDiscord(webhookUrl, msg);
      console.log("Leaderboard posted to Discord");
    }
  } else {
    console.error("Usage: bounty-tracker.ts <notify|leaderboard>");
    console.error("  notify      — Post Discord notification for a merged bounty PR");
    console.error("  leaderboard — Generate and post the leaderboard");
    process.exit(1);
  }
}

// Run if invoked directly
main().catch((err) => {
  console.error(err);
  process.exit(1);
});

// Export for testing
export {
  extractBounty,
  buildLeaderboard,
  formatBountyNotification,
  formatLeaderboard,
  loadContributors,
  resolveDiscord,
  awardLurkrXP,
  lurkrAddXP,
  lurkrGetUser,
  POINTS,
};
export type {
  BountyResult,
  LeaderboardEntry,
  Contributor,
  GitHubPR,
  LurkrLevelResponse,
};
