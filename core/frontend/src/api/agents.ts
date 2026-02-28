import { api } from "./client";
import type { DiscoverResult } from "./types";

export const agentsApi = {
  discover: () => api.get<DiscoverResult>("/discover"),
};
