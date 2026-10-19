import { useState } from "react";
import { Shield, X, Loader2, KeyRound } from "lucide-react";
import { credentialsApi, type AgentCredentialFormRequest } from "@/api/credentials";

interface Props {
  /** Session whose queen is parked waiting for this form. */
  sessionId: string;
  /** The form spec carried by the `client_credential_form_requested` event. */
  request: AgentCredentialFormRequest;
  /** Called once the submit/cancel request resolves (modal should unmount). */
  onClose: () => void;
}

/**
 * Secure credential form the agent pops via `credentials(action="collect")`.
 *
 * Secret values entered here are POSTed straight to the encrypted store
 * (`/sessions/{id}/credential-form`) and never travel back through the chat —
 * the agent only receives a non-secret confirmation. Submitting or cancelling
 * resumes the parked queen loop.
 */
export default function AgentCredentialForm({ sessionId, request, onClose }: Props) {
  const [values, setValues] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const setField = (name: string, v: string) =>
    setValues((prev) => ({ ...prev, [name]: v }));

  const missingRequired = request.fields.some(
    (f) => f.required && !(values[f.name] || "").trim(),
  );

  const submit = async () => {
    if (submitting || missingRequired) return;
    setSubmitting(true);
    setError(null);
    try {
      const keys: Record<string, string> = {};
      for (const f of request.fields) {
        const v = (values[f.name] || "").trim();
        if (v) keys[f.name] = v;
      }
      await credentialsApi.submitAgentForm(sessionId, {
        correlation_id: request.correlation_id,
        status: "saved",
        credential_id: request.credential_id,
        account: request.account,
        keys,
      });
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save credential");
      setSubmitting(false);
    }
  };

  const cancel = async () => {
    if (submitting) return;
    setSubmitting(true);
    try {
      await credentialsApi.submitAgentForm(sessionId, {
        correlation_id: request.correlation_id,
        status: "cancelled",
        credential_id: request.credential_id,
        account: request.account,
      });
    } catch {
      // Best effort — close regardless so the user isn't stuck.
    }
    onClose();
  };

  return (
    <>
      <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm" onClick={cancel} />
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4 pointer-events-none">
        <div className="bg-card border border-border rounded-xl shadow-2xl w-full max-w-md pointer-events-auto">
          {/* Header */}
          <div className="flex items-start justify-between px-5 pt-5 pb-3 border-b border-border/60">
            <div className="flex items-center gap-3">
              <div className="w-8 h-8 rounded-lg bg-primary/10 border border-primary/20 flex items-center justify-center">
                <KeyRound className="w-4 h-4 text-primary" />
              </div>
              <div>
                <h2 className="text-sm font-semibold text-foreground">{request.title}</h2>
                <p className="text-[11px] text-muted-foreground">
                  {request.credential_id}
                  {request.account && request.account !== "default"
                    ? ` · ${request.account}`
                    : ""}
                </p>
              </div>
            </div>
            <button
              onClick={cancel}
              className="p-1.5 rounded-md hover:bg-muted/60 text-muted-foreground hover:text-foreground transition-colors"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          {/* Body */}
          <div className="px-5 py-4 space-y-3">
            {request.instructions && (
              <p className="text-xs text-muted-foreground whitespace-pre-line">
                {request.instructions}
              </p>
            )}

            {request.fields.map((f) => (
              <div key={f.name}>
                <label className="block text-[11px] font-medium text-muted-foreground mb-1">
                  {f.label}
                  {f.required ? <span className="text-destructive"> *</span> : null}
                </label>
                <input
                  type={f.secret ? "password" : "text"}
                  value={values[f.name] || ""}
                  onChange={(e) => setField(f.name, e.target.value)}
                  placeholder={f.placeholder || undefined}
                  autoComplete={f.secret ? "new-password" : "off"}
                  className="w-full px-3 py-2 rounded-md border border-border bg-background text-xs text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary/40"
                />
              </div>
            ))}

            <div className="flex items-center gap-2 px-3 py-2 rounded-lg border border-border/60 bg-muted/30 text-[11px] text-muted-foreground">
              <Shield className="w-3.5 h-3.5 flex-shrink-0 text-primary" />
              <span>Stored encrypted. The agent never sees these values.</span>
            </div>

            {error && (
              <div className="px-3 py-2 rounded-lg border border-destructive/20 bg-destructive/5 text-xs text-destructive">
                {error}
              </div>
            )}
          </div>

          {/* Footer */}
          <div className="flex items-center justify-end gap-2 px-5 pb-5">
            <button
              onClick={cancel}
              disabled={submitting}
              className="px-3 py-2 rounded-lg text-sm font-medium text-muted-foreground hover:bg-muted/60 transition-colors disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              onClick={submit}
              disabled={submitting || missingRequired}
              className="flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {submitting && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
              Save securely
            </button>
          </div>
        </div>
      </div>
    </>
  );
}
