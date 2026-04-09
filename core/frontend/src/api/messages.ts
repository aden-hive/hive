import { api } from "./client";

export interface NewMessageResult {
  queen_id: string;
  session_id: string;
}

export const messagesApi = {
  newMessage: (message: string) =>
    api.post<NewMessageResult>("/messages/new", { message }),
};
