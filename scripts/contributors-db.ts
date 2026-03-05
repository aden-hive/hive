/**
 * MongoDB-backed contributor identity store.
 *
 * Stores GitHub ↔ Discord mappings in a `contributors` collection.
 * Used by bounty-bot.ts (read/write) and bounty-tracker.ts (read).
 *
 * Environment:
 *   MONGODB_URI — MongoDB connection string (required)
 */

import { MongoClient, type Collection, type Db } from "mongodb";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ContributorDoc {
  github: string; // GitHub username (lowercased for lookups)
  githubDisplay: string; // Original-case GitHub username
  discord: string; // Discord user ID
  name?: string;
  linkedAt: Date;
}

// ---------------------------------------------------------------------------
// Connection
// ---------------------------------------------------------------------------

let _client: MongoClient | null = null;
let _db: Db | null = null;

export async function getDb(): Promise<Db> {
  if (_db) return _db;

  const uri = process.env.MONGODB_URI;
  if (!uri) {
    throw new Error("Missing MONGODB_URI environment variable");
  }

  _client = new MongoClient(uri);
  await _client.connect();
  _db = _client.db("hive");
  return _db;
}

export async function closeDb(): Promise<void> {
  if (_client) {
    await _client.close();
    _client = null;
    _db = null;
  }
}

function collection(db: Db): Collection<ContributorDoc> {
  return db.collection<ContributorDoc>("contributors");
}

// ---------------------------------------------------------------------------
// Read operations
// ---------------------------------------------------------------------------

export async function findByGithub(
  db: Db,
  githubUsername: string
): Promise<ContributorDoc | null> {
  return collection(db).findOne({ github: githubUsername.toLowerCase() });
}

export async function findByDiscord(
  db: Db,
  discordId: string
): Promise<ContributorDoc | null> {
  return collection(db).findOne({ discord: discordId });
}

export async function getAllContributors(
  db: Db
): Promise<ContributorDoc[]> {
  return collection(db).find().toArray();
}

/**
 * Build a Map<github_lowercase, { github, discord, name }> for compatibility
 * with bounty-tracker.ts's existing contributor resolution.
 */
export async function loadContributorMap(
  db: Db
): Promise<Map<string, { github: string; discord: string; name?: string }>> {
  const docs = await getAllContributors(db);
  const map = new Map<string, { github: string; discord: string; name?: string }>();
  for (const doc of docs) {
    map.set(doc.github, {
      github: doc.githubDisplay,
      discord: doc.discord,
      name: doc.name,
    });
  }
  return map;
}

// ---------------------------------------------------------------------------
// Write operations
// ---------------------------------------------------------------------------

export async function addContributor(
  db: Db,
  githubUsername: string,
  discordId: string,
  name?: string
): Promise<{ success: boolean; message: string }> {
  const existing = await findByGithub(db, githubUsername);
  if (existing) {
    return { success: false, message: `**${githubUsername}** is already linked.` };
  }

  const byDiscord = await findByDiscord(db, discordId);
  if (byDiscord) {
    return {
      success: false,
      message: `Your Discord is already linked to **${byDiscord.githubDisplay}**. To change it, ask a maintainer.`,
    };
  }

  await collection(db).insertOne({
    github: githubUsername.toLowerCase(),
    githubDisplay: githubUsername,
    discord: discordId,
    name,
    linkedAt: new Date(),
  });

  return {
    success: true,
    message: `Linked! **${githubUsername}** ↔ Discord. You'll now receive XP when your bounty PRs are merged.`,
  };
}

// ---------------------------------------------------------------------------
// Index setup (run once)
// ---------------------------------------------------------------------------

export async function ensureIndexes(db: Db): Promise<void> {
  const coll = collection(db);
  await coll.createIndex({ github: 1 }, { unique: true });
  await coll.createIndex({ discord: 1 }, { unique: true });
}
