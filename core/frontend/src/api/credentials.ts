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

  checkAgent: (agentPath: string) =>
    api.post<{ required: AgentCredentialRequirement[]; has_aden_key: boolean }>(
      "/credentials/check-agent",
      { agent_path: agentPath },
    ),
};
