import { useState, useEffect, useCallback } from "react";
import { KeyRound, Check, AlertCircle, X, Shield, Loader2, Trash2, ExternalLink } from "lucide-react";
import { credentialsApi, type CredentialInfo, type AgentCredentialRequirement } from "@/api/credentials";

export interface Credential {
  id: string;
  name: string;
  description: string;
  icon: string;
  connected: boolean;
  required: boolean;
}

export const credentialTemplates: Record<string, Omit<Credential, "connected">[]> = {
  "inbox-management": [
    { id: "gmail", name: "Gmail", description: "Read, send, and archive emails", icon: "\ud83d\udce7", required: true },
    { id: "gcal", name: "Google Calendar", description: "Accept invites and create events", icon: "\ud83d\udcc5", required: false },
    { id: "gsheets", name: "Google Sheets", description: "Log invoices and expenses", icon: "\ud83d\udcca", required: false },
  ],
  "job-hunter": [
    { id: "linkedin", name: "LinkedIn", description: "Scan jobs and auto-apply", icon: "\ud83d\udcbc", required: true },
    { id: "gmail", name: "Gmail", description: "Send cover letters and replies", icon: "\ud83d\udce7", required: true },
    { id: "gdrive", name: "Google Drive", description: "Access resume and documents", icon: "\ud83d\udcc1", required: false },
  ],
  "fitness-coach": [
    { id: "apple-health", name: "Apple Health", description: "Sleep, HRV, and recovery data", icon: "\u2764\ufe0f", required: true },
    { id: "gcal", name: "Google Calendar", description: "Schedule workouts and meals", icon: "\ud83d\udcc5", required: false },
  ],
  "vuln-assessment": [
    { id: "shodan", name: "Shodan", description: "Port scanning and host discovery", icon: "\ud83d\udd0d", required: true },
    { id: "ssl-labs", name: "SSL Labs", description: "SSL certificate analysis", icon: "\ud83d\udd12", required: false },
    { id: "gcal", name: "Google Calendar", description: "Set renewal reminders", icon: "\ud83d\udcc5", required: false },
  ],
};

/** Create fresh (disconnected) credentials for an agent type */
export function createFreshCredentials(agentType: string): Credential[] {
  const templates = credentialTemplates[agentType] || [];
  return templates.map(t => ({ ...t, connected: false }));
}

/** Clone credentials from an existing set (for new instances of the same agent) */
export function cloneCredentials(existing: Credential[]): Credential[] {
  return existing.map(c => ({ ...c }));
}

/** Check if all required credentials are connected */
export function allRequiredCredentialsMet(creds: Credential[]): boolean {
  return creds.filter(c => c.required).every(c => c.connected);
}

// Internal display type for the modal
interface CredentialRow {
  id: string;
  name: string;
  description: string;
  icon: string;
  connected: boolean;
  required: boolean;
  credentialKey: string; // key name within the credential (e.g., "api_key")
  adenSupported: boolean; // whether this credential uses OAuth via Aden
}

interface CredentialsModalProps {
  agentType: string;
  agentLabel: string;
  open: boolean;
  onClose: () => void;
  agentPath?: string;
  onCredentialChange?: () => void;
  // Legacy props — still accepted for backward compat but ignored when backend is available
  credentials?: Credential[];
  onToggleCredential?: (credId: string) => void;
}

export default function CredentialsModal({
  agentType,
  agentLabel,
  open,
  onClose,
  agentPath,
  onCredentialChange,
  credentials: legacyCredentials,
  onToggleCredential,
}: CredentialsModalProps) {
  const [rows, setRows] = useState<CredentialRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [inputValue, setInputValue] = useState("");
  const [saving, setSaving] = useState(false);

  const fetchStatus = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      if (agentPath) {
        // Real agent — ask backend what credentials it actually needs
        const { required } = await credentialsApi.checkAgent(agentPath);
        const newRows: CredentialRow[] = required.map((r: AgentCredentialRequirement) => ({
          id: r.credential_id,
          name: r.credential_name,
          description: r.description,
          icon: "\uD83D\uDD11",
          connected: r.available,
          required: true,
          credentialKey: r.credential_key || "api_key",
          adenSupported: r.aden_supported,
        }));
        setRows(newRows);
      } else {
        // No real path — fall back to templates + list
        const { credentials: stored } = await credentialsApi.list();
        const storedIds = new Set(stored.map((c: CredentialInfo) => c.credential_id));
        const templates = credentialTemplates[agentType] || [];
        const newRows: CredentialRow[] = templates.map(t => ({
          ...t,
          connected: storedIds.has(t.id),
          credentialKey: "api_key",
          adenSupported: false,
        }));
        setRows(newRows);
      }
    } catch {
      // Backend unavailable — fall back to legacy props or templates
      if (legacyCredentials) {
        setRows(legacyCredentials.map(c => ({
          ...c,
          credentialKey: "api_key",
          adenSupported: false,
        })));
      } else {
        const templates = credentialTemplates[agentType] || [];
        setRows(templates.map(t => ({
          ...t,
          connected: false,
          credentialKey: "api_key",
          adenSupported: false,
        })));
      }
    } finally {
      setLoading(false);
    }
  }, [agentPath, agentType, legacyCredentials]);

  // Fetch on open
  useEffect(() => {
    if (open) {
      fetchStatus();
      setEditingId(null);
      setInputValue("");
    }
  }, [open, fetchStatus]);

  const handleConnect = async (row: CredentialRow) => {
    if (row.adenSupported) {
      // OAuth credential — redirect to Aden platform
      window.open("https://hive.adenhq.com/", "_blank", "noopener");
      return;
    }

    if (editingId === row.id) {
      // Already editing — save
      if (!inputValue.trim()) return;
      setSaving(true);
      try {
        await credentialsApi.save(row.id, { [row.credentialKey]: inputValue.trim() });
        setEditingId(null);
        setInputValue("");
        onCredentialChange?.();
        await fetchStatus();
      } catch {
        setError(`Failed to save ${row.name}`);
      } finally {
        setSaving(false);
      }
    } else {
      // Start editing — show inline API key input
      setEditingId(row.id);
      setInputValue("");
    }
  };

  const handleDisconnect = async (row: CredentialRow) => {
    setSaving(true);
    try {
      await credentialsApi.delete(row.id);
      onCredentialChange?.();
      await fetchStatus();
    } catch {
      // Backend unavailable — fall back to legacy toggle
      onToggleCredential?.(row.id);
    } finally {
      setSaving(false);
    }
  };

  if (!open) return null;

  const connectedCount = rows.filter(c => c.connected).length;
  const requiredCount = rows.filter(c => c.required).length;
  const requiredConnected = rows.filter(c => c.required && c.connected).length;
  const allRequiredMet = requiredConnected === requiredCount;

  return (
    <>
      {/* Backdrop */}
      <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm" onClick={onClose} />

      {/* Modal */}
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4 pointer-events-none">
        <div className="bg-card border border-border rounded-xl shadow-2xl w-full max-w-md pointer-events-auto">
          {/* Header */}
          <div className="flex items-center justify-between px-5 py-4 border-b border-border/60">
            <div className="flex items-center gap-3">
              <div className="w-8 h-8 rounded-lg bg-primary/10 border border-primary/20 flex items-center justify-center">
                <KeyRound className="w-4 h-4 text-primary" />
              </div>
              <div>
                <h2 className="text-sm font-semibold text-foreground">Credentials</h2>
                <p className="text-[11px] text-muted-foreground">{agentLabel}</p>
              </div>
            </div>
            <button onClick={onClose} className="p-1.5 rounded-md hover:bg-muted/60 text-muted-foreground hover:text-foreground transition-colors">
              <X className="w-4 h-4" />
            </button>
          </div>

          {/* Status banner */}
          {!loading && (
            <div className={`mx-5 mt-4 px-3 py-2.5 rounded-lg border text-xs font-medium flex items-center gap-2 ${
              allRequiredMet
                ? "bg-emerald-500/10 border-emerald-500/20 text-emerald-600"
                : "bg-destructive/5 border-destructive/20 text-destructive"
            }`}>
              {allRequiredMet ? (
                <>
                  <Shield className="w-3.5 h-3.5" />
                  All required credentials connected ({connectedCount}/{rows.length} total)
                </>
              ) : (
                <>
                  <AlertCircle className="w-3.5 h-3.5" />
                  {requiredCount - requiredConnected} required credential{requiredCount - requiredConnected !== 1 ? "s" : ""} missing
                </>
              )}
            </div>
          )}

          {/* Error banner */}
          {error && (
            <div className="mx-5 mt-2 px-3 py-2 rounded-lg border border-destructive/20 bg-destructive/5 text-xs text-destructive">
              {error}
            </div>
          )}

          {/* Loading state */}
          {loading && (
            <div className="p-8 flex items-center justify-center">
              <Loader2 className="w-5 h-5 animate-spin text-muted-foreground" />
            </div>
          )}

          {/* Credential list */}
          {!loading && (
            <div className="p-5 space-y-2">
              {rows.map((row) => (
                <div key={row.id}>
                  <div
                    className={`flex items-center gap-3 px-3 py-3 rounded-lg border transition-colors ${
                      row.connected
                        ? "border-primary/20 bg-primary/[0.03]"
                        : "border-border/60 bg-muted/20"
                    }`}
                  >
                    <span className="text-lg flex-shrink-0">{row.icon}</span>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-medium text-foreground">{row.name}</span>
                        {row.required && (
                          <span className={`text-[9px] font-semibold uppercase tracking-wider px-1.5 py-0.5 rounded ${
                            row.connected
                              ? "text-emerald-600/70 bg-emerald-500/10"
                              : "text-destructive/70 bg-destructive/10"
                          }`}>
                            Required
                          </span>
                        )}
                      </div>
                      <p className="text-[11px] text-muted-foreground mt-0.5">{row.description}</p>
                    </div>
                    {row.connected ? (
                      <div className="flex items-center gap-1 flex-shrink-0">
                        <span className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium bg-primary/10 text-primary">
                          <Check className="w-3 h-3" />
                          Connected
                        </span>
                        <button
                          onClick={() => handleDisconnect(row)}
                          disabled={saving}
                          className="p-1.5 rounded-md text-muted-foreground hover:text-destructive hover:bg-destructive/10 transition-colors"
                          title="Disconnect"
                        >
                          <Trash2 className="w-3 h-3" />
                        </button>
                      </div>
                    ) : (
                      <button
                        onClick={() => handleConnect(row)}
                        disabled={saving}
                        className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium bg-muted/60 text-foreground hover:bg-muted transition-colors flex-shrink-0"
                      >
                        {row.adenSupported ? (
                          <>
                            <ExternalLink className="w-3 h-3" />
                            Authorize
                          </>
                        ) : (
                          <>
                            <KeyRound className="w-3 h-3" />
                            Connect
                          </>
                        )}
                      </button>
                    )}
                  </div>

                  {/* Inline API key input */}
                  {editingId === row.id && !row.connected && (
                    <div className="mt-1.5 flex gap-2 px-3">
                      <input
                        type="password"
                        value={inputValue}
                        onChange={(e) => setInputValue(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") handleConnect(row);
                          if (e.key === "Escape") { setEditingId(null); setInputValue(""); }
                        }}
                        placeholder={`Paste your ${row.name} API key...`}
                        autoFocus
                        className="flex-1 px-3 py-1.5 rounded-md border border-border bg-background text-xs text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary/40"
                      />
                      <button
                        onClick={() => handleConnect(row)}
                        disabled={saving || !inputValue.trim()}
                        className="px-3 py-1.5 rounded-md text-xs font-medium bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                      >
                        {saving ? <Loader2 className="w-3 h-3 animate-spin" /> : "Save"}
                      </button>
                      <button
                        onClick={() => { setEditingId(null); setInputValue(""); }}
                        className="px-2 py-1.5 rounded-md text-xs text-muted-foreground hover:bg-muted transition-colors"
                      >
                        Cancel
                      </button>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}

          {/* Footer */}
          {!loading && (
            <div className="px-5 pb-4">
              <button
                onClick={onClose}
                disabled={!allRequiredMet}
                className={`w-full py-2.5 rounded-lg text-sm font-medium transition-colors ${
                  allRequiredMet
                    ? "bg-primary text-primary-foreground hover:bg-primary/90"
                    : "bg-muted text-muted-foreground cursor-not-allowed"
                }`}
              >
                {allRequiredMet ? "Done" : "Connect required credentials to continue"}
              </button>
            </div>
          )}
        </div>
      </div>
    </>
  );
}
