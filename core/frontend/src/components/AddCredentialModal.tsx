import { useState } from "react";
import { KeyRound, X, Loader2, Plus, Trash2, Shield, Eye, EyeOff, Check, AlertCircle } from "lucide-react";
import { credentialsApi } from "@/api/credentials";
import type { BYOKCredentialField } from "@/data/byokCatalog";

interface Props {
  open: boolean;
  onClose: () => void;
  /** Called after a successful save so the page can refresh. */
  onSaved: () => void;
  /**
   * When set, the provider is fixed (modal opened from a specific card's
   * "Add account"). When null, the user types any provider id (incl. custom).
   */
  lockedProvider?: {
    credentialId: string;
    name: string;
    defaultKeyName?: string;
    /** Pre-seeded multi-field shape for known auth types (e.g. Postgres). */
    defaultFields?: BYOKCredentialField[];
  } | null;
}

interface FieldRow {
  id: number;
  name: string;
  value: string;
  secret: boolean;
  placeholder: string;
}

let _fieldSeq = 0;
const newField = (name = "api_key", secret = true, placeholder = ""): FieldRow => ({
  id: ++_fieldSeq,
  name,
  value: "",
  secret,
  placeholder,
});

// Seed the modal's key rows: a known field shape (Postgres, Twilio, …) when the
// provider has one, otherwise a single "api_key" row.
const seedFields = (lp: Props["lockedProvider"]): FieldRow[] =>
  lp?.defaultFields?.length
    ? lp.defaultFields.map((f) => newField(f.name, f.secret ?? true, f.placeholder ?? ""))
    : [newField(lp?.defaultKeyName || "api_key")];

/**
 * Manual "Add credential" form for the Integrations page — parity with the
 * agent's secure form. Supports any provider id (known or custom), an account
 * alias for multi-account, and one or more key fields. Saves via
 * `POST /api/credentials/local` (aliased, health-checked local account).
 */
export default function AddCredentialModal({
  open,
  onClose,
  onSaved,
  lockedProvider,
}: Props) {
  const [providerId, setProviderId] = useState(lockedProvider?.credentialId ?? "");
  const [account, setAccount] = useState("default");
  const [fields, setFields] = useState<FieldRow[]>(() => seedFields(lockedProvider));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{ valid: boolean | null; message: string | null } | null>(null);

  if (!open) return null;

  const setFieldName = (id: number, name: string) =>
    setFields((f) => f.map((x) => (x.id === id ? { ...x, name } : x)));
  const setFieldValue = (id: number, value: string) =>
    setFields((f) => f.map((x) => (x.id === id ? { ...x, value } : x)));
  const toggleSecret = (id: number) =>
    setFields((f) => f.map((x) => (x.id === id ? { ...x, secret: !x.secret } : x)));
  const removeField = (id: number) =>
    setFields((f) => (f.length > 1 ? f.filter((x) => x.id !== id) : f));

  const effectiveProvider = (lockedProvider?.credentialId ?? providerId).trim();
  const validFields = fields.filter((f) => f.name.trim() && f.value.trim());
  const canSave =
    !!effectiveProvider &&
    !/[\s/\\]/.test(effectiveProvider) &&
    !!account.trim() &&
    !/[\s/\\]/.test(account.trim()) &&
    validFields.length > 0 &&
    !saving;

  const save = async () => {
    if (!canSave) return;
    setSaving(true);
    setError(null);
    setResult(null);
    try {
      const keys: Record<string, string> = {};
      for (const f of validFields) keys[f.name.trim()] = f.value;
      const resp = await credentialsApi.saveLocal(
        effectiveProvider,
        account.trim() || "default",
        keys,
      );
      // Surface the health-check verdict (when the provider has a checker)
      // before closing, so a bad key is caught here instead of at run time.
      if (resp.valid === false) {
        setResult({ valid: false, message: resp.message || "Key failed validation" });
        setSaving(false);
        return;
      }
      onSaved();
      onClose();
    } catch (e) {
      const body =
        e && typeof e === "object" && "body" in e
          ? (e as { body?: { error?: string } }).body
          : null;
      setError(body?.error || (e instanceof Error ? e.message : "Failed to save credential"));
      setSaving(false);
    }
  };

  return (
    <>
      <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm" onClick={saving ? undefined : onClose} />
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4 pointer-events-none">
        <div className="bg-card border border-border rounded-xl shadow-2xl w-full max-w-md pointer-events-auto max-h-[90vh] overflow-y-auto">
          {/* Header */}
          <div className="flex items-start justify-between px-5 pt-5 pb-3 border-b border-border/60">
            <div className="flex items-center gap-3">
              <div className="w-8 h-8 rounded-lg bg-primary/10 border border-primary/20 flex items-center justify-center">
                <KeyRound className="w-4 h-4 text-primary" />
              </div>
              <div>
                <h2 className="text-sm font-semibold text-foreground">
                  {lockedProvider ? `Add ${lockedProvider.name} account` : "Add credential"}
                </h2>
                <p className="text-[11px] text-muted-foreground">
                  Stored encrypted; usable by your agents.
                </p>
              </div>
            </div>
            <button
              onClick={onClose}
              className="p-1.5 rounded-md hover:bg-muted/60 text-muted-foreground hover:text-foreground transition-colors"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          {/* Body */}
          <div className="px-5 py-4 space-y-3">
            {/* Provider */}
            <div>
              <label className="block text-[11px] font-medium text-muted-foreground mb-1">
                Provider <span className="text-destructive">*</span>
              </label>
              {lockedProvider ? (
                <div className="px-3 py-2 rounded-md border border-border bg-muted/30 text-xs text-foreground">
                  {lockedProvider.name}{" "}
                  <span className="text-muted-foreground/60">({lockedProvider.credentialId})</span>
                </div>
              ) : (
                <input
                  value={providerId}
                  onChange={(e) =>
                    setProviderId(
                      e.target.value
                        .toLowerCase()
                        .replace(/[^a-z0-9_-]+/g, "_")
                        .replace(/^[^a-z0-9]+/, ""),
                    )
                  }
                  placeholder="e.g. google, github, stripe"
                  autoFocus
                  className="w-full px-3 py-2 rounded-md border border-border bg-background text-xs text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary/40"
                />
              )}
            </div>

            {/* Account alias */}
            <div>
              <label className="block text-[11px] font-medium text-muted-foreground mb-1">
                Account name
              </label>
              <input
                value={account}
                onChange={(e) =>
                  setAccount(
                    e.target.value
                      .toLowerCase()
                      .replace(/[^a-z0-9_-]+/g, "_")
                      .replace(/^[^a-z0-9]+/, ""),
                  )
                }
                placeholder="default"
                className="w-full px-3 py-2 rounded-md border border-border bg-background text-xs text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary/40"
              />
              <p className="text-[10px] text-muted-foreground/70 mt-1">
                Use distinct names (e.g. "work", "personal") to keep multiple accounts for one provider.
              </p>
            </div>

            {/* Key fields */}
            <div className="space-y-2">
              <label className="block text-[11px] font-medium text-muted-foreground">
                Keys <span className="text-destructive">*</span>
              </label>
              {fields.map((f) => (
                <div key={f.id} className="flex items-center gap-1.5">
                  <input
                    value={f.name}
                    onChange={(e) => setFieldName(f.id, e.target.value)}
                    placeholder="field"
                    className="w-28 px-2 py-1.5 rounded-md border border-border bg-background text-[11px] text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary/40"
                  />
                  <div className="relative flex-1 group">
                    <input
                      type={f.secret ? "password" : "text"}
                      value={f.value}
                      onChange={(e) => setFieldValue(f.id, e.target.value)}
                      placeholder={f.placeholder || "value"}
                      autoComplete={f.secret ? "new-password" : "off"}
                      className="w-full pl-2 pr-8 py-1.5 rounded-md border border-border bg-background text-[11px] text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary/40"
                    />
                    <button
                      type="button"
                      onClick={() => toggleSecret(f.id)}
                      title={f.secret ? "Show value" : "Hide value"}
                      className="absolute inset-y-0 right-0 flex items-center pr-2 text-muted-foreground hover:text-foreground transition-opacity opacity-0 group-hover:opacity-100 group-focus-within:opacity-100 focus:opacity-100"
                    >
                      {f.secret ? <Eye className="w-3.5 h-3.5" /> : <EyeOff className="w-3.5 h-3.5" />}
                    </button>
                  </div>
                  <button
                    onClick={() => removeField(f.id)}
                    disabled={fields.length <= 1}
                    title="Remove field"
                    className="p-1.5 rounded-md text-muted-foreground hover:text-destructive transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              ))}
              <button
                onClick={() => setFields((f) => [...f, newField("", false)])}
                className="flex items-center gap-1 text-[11px] font-medium text-primary hover:text-primary/80 transition-colors"
              >
                <Plus className="w-3 h-3" />
                Add field
              </button>
            </div>


            {result && result.valid === false && (
              <div className="flex items-start gap-2 px-3 py-2 rounded-lg border border-amber-500/30 bg-amber-500/5 text-xs text-amber-700 dark:text-amber-400">
                <AlertCircle className="w-3.5 h-3.5 flex-shrink-0 mt-0.5" />
                <span>{result.message} — saved anyway; you can update it below.</span>
              </div>
            )}

            {error && (
              <div className="px-3 py-2 rounded-lg border border-destructive/20 bg-destructive/5 text-xs text-destructive">
                {error}
              </div>
            )}
          </div>

          {/* Footer */}
          <div className="flex items-center justify-end gap-2 px-5 pb-5">
            <button
              onClick={onClose}
              disabled={saving}
              className="px-3 py-2 rounded-lg text-sm font-medium text-muted-foreground hover:bg-muted/60 transition-colors disabled:opacity-50"
            >
              {result?.valid === false ? "Done" : "Cancel"}
            </button>
            <button
              onClick={save}
              disabled={!canSave}
              className="flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Check className="w-3.5 h-3.5" />}
              Save
            </button>
          </div>
        </div>
      </div>
    </>
  );
}
