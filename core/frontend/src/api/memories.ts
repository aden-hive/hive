import { api } from "./client";

/**
 * Memory store. The runtime persists markdown files under ``MEMORIES_DIR``
 * (typically ``~/.hive/memories/``) with a fixed taxonomy:
 *
 *     global/<name>.md
 *     agents/queens/<queenId>/<name>.md
 *     colonies/<colonyId>/<name>.md
 *     agents/<workerId>/<name>.md
 *
 * Each file is markdown with YAML frontmatter (``name``, ``type``,
 * ``description``). The runtime exposes four endpoints; the list endpoint
 * returns metadata only — content is fetched lazily per file.
 *
 *   GET    /memories               → list every memory across scopes
 *   GET    /memories/file?path=…   → read one memory's content
 *   PUT    /memories/file?path=…   → overwrite one memory's content
 *   DELETE /memories/file?path=…   → retire one memory (kept in its history)
 *   GET    /memories/history?path=… → every change to one memory
 *   POST   /memories/restore?path=… → put a memory back as one change left it
 *   GET    /memories/retired       → memories retired and not restored
 *
 * Edits and removals made here are the owner's: a memory the owner wrote
 * or edited can't be overwritten or retired by a queen.
 *
 * (Main rewrites these to ``/api/memories…`` before they hit the runtime.)
 */

export type MemoryScope = "global" | "queen" | "colony" | "agent" | "root";

export interface Memory {
  /** Path relative to the memories root, e.g. ``agents/queens/queen_x/foo.md``. Stable id for read/update/delete. */
  path: string;
  /** Just the basename including the .md suffix. */
  filename: string;
  /** Frontmatter ``name`` — may be missing on legacy files. */
  name?: string;
  /** Frontmatter ``type`` — e.g. ``user``, ``feedback``, ``project``, ``reference``. */
  type?: string;
  /** Frontmatter ``description`` — used as the collapsed preview. */
  description?: string;
  /** UI scope derived from the on-disk layout. */
  scope: MemoryScope;
  /** Queen / colony / agent id when scope is queen/colony/agent; empty for global. */
  scope_name: string;
  /** Who last wrote it; absent on files from before authors were recorded. */
  author?: MemoryAuthor | null;
  /** The day it was first written (YYYY-MM-DD). */
  learned?: string | null;
  /** The last day a conversation supported it (YYYY-MM-DD). */
  confirmed?: string | null;
  /** File mtime in epoch seconds — runtime-provided when available. */
  mtime?: number;
  /** Full markdown body. Absent on list responses; populated by ``read()`` / ``update()``. */
  content?: string;
}

export type MemoryAuthor = "owner" | "queen" | "reflection";

/** One change to a memory file, from its history. */
export interface MemoryChange {
  /** Its number in the scope's log; what ``restore`` takes. */
  n: number;
  at: string;
  op: "write" | "retire" | "restore";
  file: string;
  author: MemoryAuthor;
  reason: string;
  sources: { quote: string; where: string }[];
  /** The file's text before and after the change; null where there was none. */
  before: string | null;
  after: string | null;
}

/** A memory retired and not restored. */
export interface RetiredMemory {
  path: string;
  filename: string;
  /** The retirement's change number. */
  n: number;
  at: string;
  author: MemoryAuthor;
  reason: string;
  scope: MemoryScope;
  scope_name: string;
}

interface ListResponse {
  memories: Memory[];
}

function pathQuery(path: string): string {
  return `path=${encodeURIComponent(path)}`;
}

export const memoriesApi = {
  /** List every memory file (metadata only). Filter client-side by scope. */
  list: () => api.get<ListResponse>("/memories"),

  /** Read a single memory including its content. */
  read: (path: string) =>
    api.get<Memory & { content: string }>(`/memories/file?${pathQuery(path)}`),

  /** Overwrite an existing memory's content. */
  update: (path: string, content: string) =>
    api.put<Memory & { content: string }>(
      `/memories/file?${pathQuery(path)}`,
      { content },
    ),

  /** Retire a memory file by path; it stays in its history. */
  delete: (path: string) =>
    api.delete<{ deleted: string }>(`/memories/file?${pathQuery(path)}`),

  /** Every change to one memory, oldest first. */
  history: (path: string) =>
    api.get<{ path: string; changes: MemoryChange[] }>(
      `/memories/history?${pathQuery(path)}`,
    ),

  /** Put a memory back as change ``n`` left it (as it was before, for a retirement). */
  restore: (path: string, n: number) =>
    api.post<Memory & { content: string }>(
      `/memories/restore?${pathQuery(path)}`,
      { n },
    ),

  /** Memories retired and not restored, newest first. */
  retired: () => api.get<{ retired: RetiredMemory[] }>("/memories/retired"),
};

/** Who wrote a memory, as the page says it. */
export function memoryAuthorLabel(author: MemoryAuthor | null | undefined): string | null {
  if (author === "owner") return "You";
  if (author === "queen") return "Queen";
  if (author === "reflection") return "Reflection";
  return null;
}

/** Display title for a memory — frontmatter ``name`` wins, else derive from filename. */
export function memoryDisplayTitle(memory: Memory): string {
  return memory.name?.trim() || memoryTitleFromFilename(memory.filename);
}

/** Convert "draft-before-sending-preference.md" → "Draft before sending preference". */
export function memoryTitleFromFilename(filename: string): string {
  return filename
    .replace(/\.md$/i, "")
    .replace(/[-_]/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

/** Convert "Draft before sending" → "draft-before-sending.md". */
export function memoryFilenameFromTitle(title: string): string {
  const slug = title
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  if (!slug) return "untitled.md";
  return slug.endsWith(".md") ? slug : `${slug}.md`;
}
