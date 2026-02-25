import { useState, useEffect, useCallback } from "react";
import { KeyRound, Check, AlertCircle, X, Shield, Loader2, Trash2, ExternalLink } from "lucide-react";
import { credentialsApi, type AgentCredentialRequirement } from "@/api/credentials";

export interface Credential {
  id: string;
  name: string;
  description: string;
  icon: string;
  connected: boolean;
  required: boolean;
}

/** Create fresh (disconnected) credentials for an agent type.
 *  Real credentials are fetched from the backend via agentPath — this returns
 *  an empty list as a safe default until the backend responds. */
export function createFreshCredentials(_agentType: string): Credential[] {
  return [];
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
  valid: boolean | null; // true = health check passed, false = failed, null = not checked
  validationMessage: string | null;
}

function requirementToRow(r: AgentCredentialRequirement): CredentialRow {
  return {
    id: r.credential_id,
    name: r.credential_name,
    description: r.description,
    icon: "\uD83D\uDD11",
    connected: r.available,
    required: true,
    credentialKey: r.credential_key || "api_key",
    adenSupported: r.aden_supported,
    valid: r.valid,
    validationMessage: r.validation_message,
  };
}

// Module-level cache: credential requirements are static per agent path.
// Cleared on save/delete so the next fetch picks up updated availability.
const credentialCache = new Map<string, AgentCredentialRequirement[]>();

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
  const [hasAdenKey, setHasAdenKey] = useState(true); // assume true until backend says otherwise
  const [adenKeyInput, setAdenKeyInput] = useState("");
  const [savingAdenKey, setSavingAdenKey] = useState(false);

  const fetchStatus = useCallback(async () => {
    setError(null);
    try {
      if (agentPath) {
        // Check cache first — credential requirements are static per agent
        const cached = credentialCache.get(agentPath);
        if (cached) {
          setRows(cached.map(requirementToRow));
          setLoading(false);
          return;
        }

        // Real agent — ask backend what credentials it actually needs
        setLoading(true);
        const { required, has_aden_key } = await credentialsApi.checkAgent(agentPath);
        setHasAdenKey(has_aden_key);
        credentialCache.set(agentPath, required);
        setRows(required.map(requirementToRow));
      } else {
        // No real path — no credentials to show
        setRows([]);
      }
    } catch {
      // Backend unavailable — fall back to legacy props or empty
      if (legacyCredentials) {
        setRows(legacyCredentials.map(c => ({
          ...c,
          credentialKey: "api_key",
          adenSupported: false,
          valid: null,
          validationMessage: null,
        })));
      } else {
        setRows([]);
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
      setAdenKeyInput("");
    }
  }, [open, fetchStatus]);

  const handleSaveAdenKey = async () => {
    if (!adenKeyInput.trim()) return;
    setSavingAdenKey(true);
    try {
      await credentialsApi.saveAdenKey(adenKeyInput.trim());
      setAdenKeyInput("");
      if (agentPath) credentialCache.delete(agentPath);
      onCredentialChange?.();
      await fetchStatus();
    } catch {
      setError("Failed to save Aden API Key");
    } finally {
      setSavingAdenKey(false);
    }
  };

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
        if (agentPath) credentialCache.delete(agentPath);
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
      if (agentPath) credentialCache.delete(agentPath);
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
  const invalidCount = rows.filter(c => c.valid === false).length;
  const missingCount = requiredCount - requiredConnected;
  const allRequiredMet = requiredConnected === requiredCount && invalidCount === 0;
  const needsAdenKeyInput = !hasAdenKey && rows.some(r => r.adenSupported);

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
                  {missingCount > 0 && `${missingCount} missing`}
                  {missingCount > 0 && invalidCount > 0 && ", "}
                  {invalidCount > 0 && `${invalidCount} invalid`}
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

          {/* Aden API Key section */}
          {!loading && needsAdenKeyInput && (
            <div className="mx-5 mt-4 px-3 py-3 rounded-lg border border-amber-500/30 bg-amber-500/5">
              <div className="flex items-center gap-2 mb-1">
                <KeyRound className="w-3.5 h-3.5 text-amber-600" />
                <span className="text-sm font-medium text-foreground">Aden API Key</span>
                <span className="text-[9px] font-semibold uppercase tracking-wider px-1.5 py-0.5 rounded text-destructive/70 bg-destructive/10">
                  Required
                </span>
              </div>
              <p className="text-[11px] text-muted-foreground mb-2">
                Required to connect OAuth integrations below.{" "}
                <a
                  href="https://hive.adenhq.com/"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-primary hover:underline inline-flex items-center gap-0.5"
                >
                  Get your key at hive.adenhq.com
                  <ExternalLink className="w-2.5 h-2.5" />
                </a>
              </p>
              <div className="flex gap-2">
                <input
                  type="password"
                  value={adenKeyInput}
                  onChange={(e) => setAdenKeyInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") handleSaveAdenKey();
                  }}
                  placeholder="Paste your ADEN_API_KEY..."
                  className="flex-1 px-3 py-1.5 rounded-md border border-border bg-background text-xs text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary/40"
                />
                <button
                  onClick={handleSaveAdenKey}
                  disabled={savingAdenKey || !adenKeyInput.trim()}
                  className="px-3 py-1.5 rounded-md text-xs font-medium bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                >
                  {savingAdenKey ? <Loader2 className="w-3 h-3 animate-spin" /> : "Save"}
                </button>
              </div>
            </div>
          )}

          {/* Credential list */}
          {!loading && (
            <div className="p-5 space-y-2">
              {rows.map((row) => (
                <div key={row.id}>
                  <div
                    className={`flex items-center gap-3 px-3 py-3 rounded-lg border transition-colors ${
                      row.connected && row.valid !== false
                        ? "border-primary/20 bg-primary/[0.03]"
                        : row.valid === false
                          ? "border-destructive/30 bg-destructive/[0.03]"
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
                      {row.valid === false && row.validationMessage && (
                        <p className="text-[11px] text-destructive mt-0.5">{row.validationMessage}</p>
                      )}
                    </div>
                    {row.connected ? (
                      <div className="flex items-center gap-1 flex-shrink-0">
                        {row.valid === false ? (
                          <span className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium bg-destructive/10 text-destructive" title={row.validationMessage || "Invalid"}>
                            <AlertCircle className="w-3 h-3" />
                            Invalid
                          </span>
                        ) : (
                          <span className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium bg-primary/10 text-primary">
                            <Check className="w-3 h-3" />
                            Connected
                          </span>
                        )}
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
                {allRequiredMet ? "Done" : missingCount > 0 ? "Connect required credentials to continue" : "Fix invalid credentials to continue"}
              </button>
            </div>
          )}
        </div>
      </div>
    </>
  );
}
