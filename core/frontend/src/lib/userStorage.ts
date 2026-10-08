/**
 * Per-user namespaced wrapper around localStorage / sessionStorage.
 *
 * The renderer used to write under bare `hive:*` keys, which were global
 * to the Electron install. Switching accounts then required a wipe-on-
 * logout that raced with React's `useState` initializers (which read
 * storage during render, before any cleanup useEffect could run). The
 * fix here is structural: every entry is keyed by the active user's
 * stable id, so user A's preferences and user B's preferences coexist
 * in localStorage with no overlap and no need for a wipe.
 *
 * Usage:
 *   - `setActiveUser(userKey)` is called from `AuthGate` synchronously
 *     during render, *before* its descendants mount. Combined with the
 *     `key={userKey}` Fragment in AuthGate, child `useState(() => ...)`
 *     initializers see the correct namespace from the very first render.
 *   - `userStorage.get/set/remove` for localStorage,
 *     `userStorage.session.get/set/remove` for sessionStorage.
 */

let activeUserKey: string | null = null;
let migratedFor: string | null = null;

/**
 * Update the namespace that subsequent `userStorage.*` calls resolve
 * against. Call this synchronously from AuthGate during render — *not*
 * from a useEffect, which would fire after children's useState
 * initializers and miss the first read.
 */
export function setActiveUser(key: string | null): void {
  activeUserKey = key;
  if (key !== null && migratedFor !== key) {
    migrateLegacyKeys(key);
    migratedFor = key;
  } else if (key === null) {
    // Allow re-migration when a user signs back in after a logout.
    migratedFor = null;
  }
}

export function getActiveUser(): string | null {
  return activeUserKey;
}

function ns(rawKey: string): string {
  return `hive:u:${activeUserKey ?? "_"}:${rawKey}`;
}

function readJson<T>(storage: Storage, key: string, fallback: T): T {
  try {
    const raw = storage.getItem(key);
    if (raw === null) return fallback;
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

function writeJson<T>(storage: Storage, key: string, value: T): void {
  try {
    storage.setItem(key, JSON.stringify(value));
  } catch {
    /* storage disabled / quota exceeded — best-effort */
  }
}

export const userStorage = {
  get<T>(key: string, fallback: T): T {
    return readJson(localStorage, ns(key), fallback);
  },
  set<T>(key: string, value: T): void {
    writeJson(localStorage, ns(key), value);
  },
  remove(key: string): void {
    try {
      localStorage.removeItem(ns(key));
    } catch {
      /* storage disabled */
    }
  },
  session: {
    get<T>(key: string, fallback: T): T {
      return readJson(sessionStorage, ns(key), fallback);
    },
    set<T>(key: string, value: T): void {
      writeJson(sessionStorage, ns(key), value);
    },
    remove(key: string): void {
      try {
        sessionStorage.removeItem(ns(key));
      } catch {
        /* storage disabled */
      }
    },
  },
};

/**
 * One-time migration of pre-namespaced renderer state into the active
 * user's namespace. Runs once per user the first time `setActiveUser`
 * is called for them, and is a no-op afterwards.
 *
 * The legacy keys were never reliably user-scoped — but for an existing
 * install with one signed-in user, all of that state belongs to *them*,
 * so attributing it to the user we just learned about is the right
 * thing. After this migration, the global keys are removed, so a future
 * second user on the same install starts with a clean slate.
 *
 * `theme` is intentionally excluded — it remains a global preference.
 */
function migrateLegacyKeys(userKey: string): void {
  const userNs = `hive:u:${userKey}:`;
  try {
    const stale: string[] = [];
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (!k) continue;
      // Only migrate the old bare `hive:*` keys. Skip anything already
      // under the per-user namespace, and skip globally-scoped keys
      // (e.g. `theme`).
      if (!k.startsWith("hive:")) continue;
      if (k.startsWith("hive:u:")) continue;
      stale.push(k);
    }
    for (const oldKey of stale) {
      const value = localStorage.getItem(oldKey);
      if (value === null) continue;
      const suffix = oldKey.slice("hive:".length);
      const newKey = userNs + suffix;
      // Don't clobber if the new namespace already has a value.
      if (localStorage.getItem(newKey) === null) {
        localStorage.setItem(newKey, value);
      }
      localStorage.removeItem(oldKey);
    }
    if (stale.length > 0) {
      console.log(
        `[userStorage] migrated ${stale.length} legacy hive:* keys into ${userNs}*`,
      );
    }
  } catch {
    /* storage disabled */
  }
}
