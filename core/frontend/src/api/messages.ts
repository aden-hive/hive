import { api } from "./client";

export const messagesApi = {
  /** Classify a home-screen prompt to a queen_id (no session created). */
  classify: (message: string) =>
    api.post<{ queen_id: string }>("/messages/classify", { message }),
};
