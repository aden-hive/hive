import { api } from "./client";

export interface CredentialInfo {
  credential_id: string;
  credential_type: string;
  key_names: string[];
  created_at: string | null;
  updated_at: string | null;
}

export interface CredentialAccount {
  provider: string;
  alias: string;
  identity: Record<string, string>;
  source: "aden" | "local" | string;
  credential_id: string;
}

export interface CredentialSpec {
  credential_name: string;
  credential_id: string;
  env_var: string;
  description: string;
  help_url: string;
  api_key_instructions: string;
  tools: string[];
  aden_supported: boolean;
  direct_api_key_supported: boolean;
  credential_key: string;
  credential_group: string;
  available: boolean;
  accounts: CredentialAccount[];
}

export interface ResyncResponse {
  synced: boolean;
  accounts_by_provider: Record<string, CredentialAccount[]>;
}

export interface OAuthStatusResponse {
  accounts_by_provider: Record<string, CredentialAccount[]>;
  has_aden_key: boolean;
  fetched_at: number;
}

/** One field the agent's secure credential form asks the user to fill in. */
export interface AgentCredentialField {
  name: string;
  label: string;
  secret: boolean;
  required: boolean;
  placeholder: string;
}

/** Payload carried by the `client_credential_form_requested` SSE event. */
export interface AgentCredentialFormRequest {
  credential_id: string;
  account: string;
  title: string;
  instructions: string;
  fields: AgentCredentialField[];
  correlation_id: string;
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
  alternative_group: string | null;
}

export const credentialsApi = {
  listSpecs: () =>
    api.get<{
      specs: CredentialSpec[];
      has_aden_key: boolean;
      accounts_by_provider?: Record<string, CredentialAccount[]>;
    }>("/credentials/specs"),

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

  // Manually add a named local credential (Integrations page "Add credential"
  // flow): any provider id, optional account alias, one or more key fields.
  // Stored as a health-checked local account — parity with the agent's form.
  saveLocal: (
    credentialId: string,
    account: string,
    keys: Record<string, string>,
  ) =>
    api.post<{
      saved: string;
      status: string;
      identity: Record<string, string>;
      valid: boolean | null;
      message: string | null;
    }>("/credentials/local", {
      credential_id: credentialId,
      account,
      keys,
    }),

  // Remove a single named local account.
  deleteLocal: (credentialId: string, alias: string) =>
    api.delete<{ deleted: boolean }>(
      `/credentials/local/${encodeURIComponent(credentialId)}/${encodeURIComponent(alias)}`,
    ),

  checkAgent: (agentPath: string) =>
    api.post<{ required: AgentCredentialRequirement[]; has_aden_key: boolean }>(
      "/credentials/check-agent",
      { agent_path: agentPath },
    ),

  resync: () =>
    api.post<ResyncResponse>("/credentials/resync", {}),

  oauthStatus: () =>
    api.get<OAuthStatusResponse>("/credentials/oauth-status"),

  validateKey: (providerId: string, apiKey: string) =>
    api.post<{ valid: boolean | null; message: string }>(
      "/credentials/validate-key",
      { provider_id: providerId, api_key: apiKey },
    ),

  // Submit (or cancel) a secure credential form the agent popped via
  // credentials(action="collect"). On "saved" the secret values go straight
  // to the encrypted store and the parked queen loop is resumed; they never
  // travel back through the chat.
  submitAgentForm: (
    sessionId: string,
    payload: {
      correlation_id: string;
      status: "saved" | "cancelled";
      credential_id: string;
      account: string;
      keys?: Record<string, string>;
    },
  ) =>
    api.post<{ saved?: string; resumed?: boolean; status?: string }>(
      `/sessions/${sessionId}/credential-form`,
      payload,
    ),
};
