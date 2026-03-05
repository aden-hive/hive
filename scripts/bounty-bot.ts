#!/usr/bin/env bun

/**
 * Bounty Bot — Discord bot for the Integration Bounty Program.
 *
 * Commands:
 *   /link-github <username>  — Link your Discord to a GitHub account
 *   /bounty-rank             — Check your bounty stats
 *
 * Environment:
 *   DISCORD_BOT_TOKEN        — Discord bot token
 *   DISCORD_APP_ID           — Discord application ID
 *   MONGODB_URI              — MongoDB connection string
 *   GITHUB_PAT               — GitHub PAT (to verify usernames)
 *   LURKR_API_KEY            — (optional) Lurkr API key for level lookups
 *   LURKR_GUILD_ID           — (optional) Discord server ID
 *
 * Setup:
 *   1. Create a Discord app at https://discord.com/developers/applications
 *   2. Bot > create bot, copy token
 *   3. OAuth2 > URL Generator > scopes: bot, applications.commands
 *   4. Bot permissions: Send Messages, Use Slash Commands
 *   5. Set env vars, then: bun run scripts/bounty-bot.ts
 */

import {
  getDb,
  closeDb,
  addContributor,
  findByDiscord,
  ensureIndexes,
} from "./contributors-db";

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------

const DISCORD_BOT_TOKEN = process.env.DISCORD_BOT_TOKEN;
const DISCORD_APP_ID = process.env.DISCORD_APP_ID;
const GITHUB_PAT = process.env.GITHUB_PAT;
const LURKR_API_KEY = process.env.LURKR_API_KEY;
const LURKR_GUILD_ID = process.env.LURKR_GUILD_ID;

if (!DISCORD_BOT_TOKEN || !DISCORD_APP_ID) {
  console.error("Missing DISCORD_BOT_TOKEN or DISCORD_APP_ID");
  process.exit(1);
}

const DISCORD_API = "https://discord.com/api/v10";
const GITHUB_API = "https://api.github.com";

// ---------------------------------------------------------------------------
// GitHub: verify username
// ---------------------------------------------------------------------------

async function verifyGitHubUser(username: string): Promise<boolean> {
  if (!GITHUB_PAT) {
    console.warn("No GITHUB_PAT set, skipping GitHub username verification");
    return true;
  }
  const res = await fetch(`${GITHUB_API}/users/${username}`, {
    headers: { Authorization: `Bearer ${GITHUB_PAT}` },
  });
  return res.ok;
}

// ---------------------------------------------------------------------------
// Lurkr: get user level
// ---------------------------------------------------------------------------

async function getLurkrLevel(discordId: string): Promise<{ level: number; xp: number } | null> {
  if (!LURKR_API_KEY || !LURKR_GUILD_ID) return null;

  const res = await fetch(
    `https://api.lurkr.gg/v2/levels/${LURKR_GUILD_ID}/users/${discordId}`,
    { headers: { "X-API-Key": LURKR_API_KEY } }
  );
  if (!res.ok) return null;

  const data = await res.json() as { level: { level: number; xp: number } };
  return data.level;
}

// ---------------------------------------------------------------------------
// Discord: register slash commands
// ---------------------------------------------------------------------------

async function registerCommands() {
  const commands = [
    {
      name: "link-github",
      description: "Link your Discord account to GitHub for bounty XP",
      options: [
        {
          name: "username",
          description: "Your GitHub username",
          type: 3, // STRING
          required: true,
        },
      ],
    },
    {
      name: "bounty-rank",
      description: "Check your bounty program level and stats",
    },
  ];

  const res = await fetch(`${DISCORD_API}/applications/${DISCORD_APP_ID}/commands`, {
    method: "PUT",
    headers: {
      Authorization: `Bot ${DISCORD_BOT_TOKEN}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(commands),
  });

  if (!res.ok) {
    const err = await res.text();
    throw new Error(`Failed to register commands: ${res.status} ${err}`);
  }

  console.log("Slash commands registered");
}

// ---------------------------------------------------------------------------
// Discord: Gateway (WebSocket)
// ---------------------------------------------------------------------------

async function connectGateway() {
  const gatewayRes = await fetch(`${DISCORD_API}/gateway/bot`, {
    headers: { Authorization: `Bot ${DISCORD_BOT_TOKEN}` },
  });
  if (!gatewayRes.ok) throw new Error(`Gateway fetch failed: ${gatewayRes.status}`);
  const { url } = (await gatewayRes.json()) as { url: string };

  const ws = new WebSocket(`${url}?v=10&encoding=json`);
  let heartbeatInterval: ReturnType<typeof setInterval> | null = null;
  let seq: number | null = null;

  ws.addEventListener("message", async (event) => {
    const data = JSON.parse(event.data as string);
    seq = data.s ?? seq;

    switch (data.op) {
      case 10: // Hello
        heartbeatInterval = setInterval(() => {
          ws.send(JSON.stringify({ op: 1, d: seq }));
        }, data.d.heartbeat_interval);

        // Identify
        ws.send(
          JSON.stringify({
            op: 2,
            d: {
              token: DISCORD_BOT_TOKEN,
              intents: 0,
              properties: { os: "linux", browser: "bounty-bot", device: "bounty-bot" },
            },
          })
        );
        break;

      case 11: // Heartbeat ACK
        break;

      case 0: // Dispatch
        if (data.t === "READY") {
          console.log(`Bot online as ${data.d.user.username}#${data.d.user.discriminator}`);
        } else if (data.t === "INTERACTION_CREATE") {
          await handleInteraction(data.d);
        }
        break;
    }
  });

  ws.addEventListener("close", (event) => {
    console.log(`WebSocket closed: ${event.code} ${event.reason}`);
    if (heartbeatInterval) clearInterval(heartbeatInterval);
    setTimeout(connectGateway, 5000);
  });

  ws.addEventListener("error", (event) => {
    console.error("WebSocket error:", event);
  });
}

// ---------------------------------------------------------------------------
// Interaction handler
// ---------------------------------------------------------------------------

async function handleInteraction(interaction: any) {
  const { type, data, member, user } = interaction;

  if (type !== 2) return;

  const discordUser = member?.user ?? user;
  const discordId = discordUser.id;

  if (data.name === "link-github") {
    const githubUsername = data.options?.[0]?.value;
    if (!githubUsername) {
      await respondToInteraction(interaction, "Please provide your GitHub username.");
      return;
    }

    await respondToInteraction(interaction, "Linking your account...", true);

    // Verify the GitHub username exists
    const exists = await verifyGitHubUser(githubUsername);
    if (!exists) {
      await editInteractionResponse(interaction, `\u274C GitHub user **${githubUsername}** not found.`);
      return;
    }

    const db = await getDb();
    const result = await addContributor(db, githubUsername, discordId);
    const emoji = result.success ? "\u2705" : "\u274C";
    await editInteractionResponse(interaction, `${emoji} ${result.message}`);
  } else if (data.name === "bounty-rank") {
    await respondToInteraction(interaction, "Checking your rank...", true);

    try {
      const db = await getDb();
      const entry = await findByDiscord(db, discordId);

      if (!entry) {
        await editInteractionResponse(
          interaction,
          "You haven't linked your GitHub yet. Use `/link-github <username>` first."
        );
        return;
      }

      let msg = `**${entry.githubDisplay}** (linked)`;

      const level = await getLurkrLevel(discordId);
      if (level) {
        msg += `\nLevel **${level.level}** | **${level.xp}** XP`;
      }

      await editInteractionResponse(interaction, msg);
    } catch (err) {
      console.error("Rank lookup failed:", err);
      await editInteractionResponse(interaction, "Failed to look up your rank. Try again later.");
    }
  }
}

async function respondToInteraction(interaction: any, content: string, ephemeral = false) {
  await fetch(`${DISCORD_API}/interactions/${interaction.id}/${interaction.token}/callback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      type: 4,
      data: { content, flags: ephemeral ? 64 : 0 },
    }),
  });
}

async function editInteractionResponse(interaction: any, content: string) {
  await fetch(
    `${DISCORD_API}/webhooks/${DISCORD_APP_ID}/${interaction.token}/messages/@original`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content }),
    }
  );
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

async function main() {
  console.log("Starting Bounty Bot...");

  const db = await getDb();
  await ensureIndexes(db);
  console.log("MongoDB connected");

  await registerCommands();
  await connectGateway();
}

main().catch(async (err) => {
  console.error(err);
  await closeDb();
  process.exit(1);
});

// Graceful shutdown
process.on("SIGINT", async () => {
  await closeDb();
  process.exit(0);
});
