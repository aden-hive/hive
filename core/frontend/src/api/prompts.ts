import { api } from "./client";

export interface CustomPrompt {
  id: string;
  title: string;
  category: string;
  content: string;
  /** Hand-picked skill names the prompt references (also embedded inline in
   *  content as <use_skill> markers). Lowercased/deduped server-side; absent
   *  on pre-skills prompts (treat as []). */
  skills?: string[];
  /** Free-form user tags, distinct from skills. Lowercased and deduped
   *  server-side; absent on pre-tag prompts (treat as []). */
  tags?: string[];
  custom: true;
}

export const promptsApi = {
  list: () => api.get<{ prompts: CustomPrompt[] }>("/prompts"),

  create: (title: string, category: string, content: string, skills: string[] = []) =>
    api.post<CustomPrompt>("/prompts", { title, category, content, skills }),

  /**
   * Update an existing custom prompt. The runtime currently rejects PUT on
   * this resource (405), so we patch via the REST-conventional fallback —
   * create a new row with the new content, then delete the old one. The
   * caller resolves with the freshly-created row.
   *
   * Order matters: create first, delete second. If create fails the
   * original survives; if delete fails the user has a duplicate they can
   * remove manually instead of losing the prompt entirely.
   */
  update: async (
    promptId: string,
    title: string,
    category: string,
    content: string,
    skills: string[] = [],
  ): Promise<CustomPrompt> => {
    const created = await api.post<CustomPrompt>("/prompts", {
      title,
      category,
      content,
      skills,
    });
    try {
      await api.delete<{ deleted: string }>(`/prompts/${promptId}`);
    } catch (err) {
      // Surface to the console but don't fail the edit — the new row is
      // already saved, the worst case is a stale duplicate.
      console.warn(
        `[prompts.update] created ${created.id} but failed to delete old ${promptId}:`,
        err,
      );
    }
    return created;
  },

  delete: (promptId: string) =>
    api.delete<{ deleted: string }>(`/prompts/${promptId}`),
};
