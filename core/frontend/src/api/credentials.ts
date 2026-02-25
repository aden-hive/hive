import { api } from "./client";

export interface CredentialInfo {
  credential_id: string;
  credential_type: string;
  key_names: string[];
  created_at: string | null;
  updated_at: string | null;
}

export interface AgentCredentialRequirement {
  credential_name: string;
  credential_id: string;
  env_var: string;
  description: string;
  help_url: string;
  tools: string[];
  node_types: string[];
  available: boolean;
  valid: boolean | null;
  validation_message: string | null;
  direct_api_key_supported: boolean;
  aden_supported: boolean;
  credential_key: string;
}

export interface CheckAgentResponse {
  required: AgentCredentialRequirement[];
  all_valid: boolean;
  error?: string;
}

export const credentialsApi = {
  list: () =>
    api.get<{ credentials: CredentialInfo[] }>("/credentials"),

  get: (credentialId: string) =>
    api.get<CredentialInfo>(`/credentials/${credentialId}`),

  save: (credentialId: string, keys: Record<string, string>) =>
    api.post<{ saved: string }>("/credentials", {
      credential_id: credentialId,
      keys,
    }),

  delete: (credentialId: string) =>
    api.delete<{ deleted: boolean }>(`/credentials/${credentialId}`),

  checkAgent: async (agentPath: string): Promise<CheckAgentResponse> => {
    const url = `/api/credentials/check-agent`;
    const response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ agent_path: agentPath }),
    });
    const body = await response.json();
    // 424 = validation failures, but body still has the required array
    if (response.ok || response.status === 424) {
      return body as CheckAgentResponse;
    }
    throw new Error(body.error || response.statusText);
  },
};
