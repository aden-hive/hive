import { api } from "./client";

export interface CustomPrompt {
  id: string;
  title: string;
  category: string;
  content: string;
  custom: true;
}

export const promptsApi = {
  list: () => api.get<{ prompts: CustomPrompt[] }>("/prompts"),

  create: (title: string, category: string, content: string) =>
    api.post<CustomPrompt>("/prompts", { title, category, content }),

  delete: (promptId: string) =>
    api.delete<{ deleted: string }>(`/prompts/${promptId}`),
};
