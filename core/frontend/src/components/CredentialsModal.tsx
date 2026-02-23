import { KeyRound, Check, AlertCircle, ExternalLink, X, Shield } from "lucide-react";

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

interface CredentialsModalProps {
  agentType: string;
  agentLabel: string;
  open: boolean;
  onClose: () => void;
  credentials: Credential[];
  onToggleCredential: (credId: string) => void;
}

export default function CredentialsModal({ agentLabel, open, onClose, credentials, onToggleCredential }: CredentialsModalProps) {
  // Suppress unused prop
  void 0;

  if (!open) return null;

  const creds = credentials;
  const connectedCount = creds.filter(c => c.connected).length;
  const requiredCount = creds.filter(c => c.required).length;
  const requiredConnected = creds.filter(c => c.required && c.connected).length;
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
          <div className={`mx-5 mt-4 px-3 py-2.5 rounded-lg border text-xs font-medium flex items-center gap-2 ${
            allRequiredMet
              ? "bg-primary/5 border-primary/20 text-primary"
              : "bg-destructive/5 border-destructive/20 text-destructive"
          }`}>
            {allRequiredMet ? (
              <>
                <Shield className="w-3.5 h-3.5" />
                All required credentials connected ({connectedCount}/{creds.length} total)
              </>
            ) : (
              <>
                <AlertCircle className="w-3.5 h-3.5" />
                {requiredCount - requiredConnected} required credential{requiredCount - requiredConnected !== 1 ? "s" : ""} missing
              </>
            )}
          </div>

          {/* Credential list */}
          <div className="p-5 space-y-2">
            {creds.map((cred) => (
              <div
                key={cred.id}
                className={`flex items-center gap-3 px-3 py-3 rounded-lg border transition-colors ${
                  cred.connected
                    ? "border-primary/20 bg-primary/[0.03]"
                    : "border-border/60 bg-muted/20"
                }`}
              >
                <span className="text-lg flex-shrink-0">{cred.icon}</span>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-foreground">{cred.name}</span>
                    {cred.required && (
                      <span className="text-[9px] font-semibold uppercase tracking-wider text-destructive/70 bg-destructive/10 px-1.5 py-0.5 rounded">
                        Required
                      </span>
                    )}
                  </div>
                  <p className="text-[11px] text-muted-foreground mt-0.5">{cred.description}</p>
                </div>
                <button
                  onClick={() => onToggleCredential(cred.id)}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors flex-shrink-0 ${
                    cred.connected
                      ? "bg-primary/10 text-primary hover:bg-primary/20"
                      : "bg-muted/60 text-foreground hover:bg-muted"
                  }`}
                >
                  {cred.connected ? (
                    <>
                      <Check className="w-3 h-3" />
                      Connected
                    </>
                  ) : (
                    <>
                      <ExternalLink className="w-3 h-3" />
                      Connect
                    </>
                  )}
                </button>
              </div>
            ))}
          </div>

          {/* Footer */}
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
        </div>
      </div>
    </>
  );
}
