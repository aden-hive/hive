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
 *   DELETE /memories/file?path=…   → delete one memory
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
  /** File mtime in epoch seconds — runtime-provided when available. */
  mtime?: number;
  /** Full markdown body. Absent on list responses; populated by ``read()`` / ``update()``. */
  content?: string;
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

  /** Delete a memory file by path. */
  delete: (path: string) =>
    api.delete<{ deleted: string }>(`/memories/file?${pathQuery(path)}`),
};

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
