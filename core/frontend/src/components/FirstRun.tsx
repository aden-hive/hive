import { useCallback, useEffect, useMemo, useState } from "react";
import { configApi, type ModelsCatalogue } from "@/api/config";
import { credentialsApi, type CredentialSpec } from "@/api/credentials";
import { ApiError } from "@/api/client";

// Ordering for the provider grid — the ones most BYOK users are likely to
// hit first appear at the top; everything else follows in catalogue order.
// Unlisted providers (any new one the runtime adds) simply sort to the end
// alphabetically.
const PREFERRED_ORDER = [
  "anthropic",
  "openai",
  "gemini",
  "openrouter",
  "deepseek",
  "mistral",
  "groq",
  "together",
  "cerebras",
  "minimax",
  "kimi",
  "hive",
];

type Stage =
  | { kind: "pick" }
  | { kind: "enter-key"; providerId: string; spec: CredentialSpec | null }
  | { kind: "saving"; providerId: string }
  | { kind: "done" };

interface FirstRunProps {
  /** Called after a key has been saved and set as the active LLM. */
  onComplete: () => void;
  /** Called when the user skips provider setup. */
  onSkip?: () => void;
}

export default function FirstRun({ onComplete, onSkip }: FirstRunProps) {
  const [specs, setSpecs] = useState<CredentialSpec[] | null>(null);
  const [models, setModels] = useState<ModelsCatalogue | null>(null);
  const [stage, setStage] = useState<Stage>({ kind: "pick" });
  const [loadError, setLoadError] = useState<string | null>(null);
  // Surfaced to EnterKey when activation (post-save `setLLMConfig` or the
  // no-models check) fails. Cleared whenever we leave the enter-key stage.
  const [activationError, setActivationError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [specsResp, modelsResp] = await Promise.all([
          credentialsApi.listSpecs(),
          configApi.getModels(),
        ]);
        if (cancelled) return;
        setSpecs(specsResp.specs);
        setModels(modelsResp);
      } catch (err) {
        if (cancelled) return;
        setLoadError(err instanceof Error ? err.message : String(err));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const specsByProvider = useMemo(() => {
    const map = new Map<string, CredentialSpec>();
    for (const s of specs ?? []) map.set(s.credential_id, s);
    return map;
  }, [specs]);

  /**
   * Build the actual provider list shown in the grid. Source-of-truth is
   * the runtime's `/api/config/models` response — every key there is an
   * LLM provider the runtime can route to. We then enrich each entry
   * with the matching credential spec so the card can show the real
   * display name, description and help_url.
   *
   * We drop OAuth-only providers (the rare ones where `direct_api_key_supported`
   * is false) because this wizard is strictly for BYOK key entry. OAuth-backed
   * providers live in the full Credentials settings page.
   */
  const providerList = useMemo(() => {
    if (!models) return [];
    const ids = Object.keys(models.models);
    const entries = ids.map((id) => {
      const spec = specsByProvider.get(id) ?? null;
      return {
        id,
        spec,
        label: spec?.credential_name ?? prettyFallback(id),
        description: spec?.description ?? "",
        available: spec?.available ?? false,
        byokSupported: spec?.direct_api_key_supported ?? true,
      };
    });

    const keep = entries.filter((e) => e.byokSupported);
    const rank = (id: string) => {
      const idx = PREFERRED_ORDER.indexOf(id);
      return idx === -1 ? PREFERRED_ORDER.length : idx;
    };
    keep.sort((a, b) => {
      const ra = rank(a.id);
      const rb = rank(b.id);
      if (ra !== rb) return ra - rb;
      return a.label.localeCompare(b.label);
    });
    return keep;
  }, [models, specsByProvider]);

  const handlePick = useCallback(
    (providerId: string) => {
      const spec = specsByProvider.get(providerId) ?? null;
      setActivationError(null);
      setStage({ kind: "enter-key", providerId, spec });
    },
    [specsByProvider],
  );

  const handleBack = useCallback(() => {
    setActivationError(null);
    setStage({ kind: "pick" });
  }, []);

  const handleSaved = useCallback(
    async (providerId: string) => {
      setActivationError(null);
      setStage({ kind: "saving", providerId });
      const providerModels = models?.models[providerId] ?? [];
      const chosen =
        providerModels.find((m) => m.recommended)?.id ??
        providerModels[0]?.id ??
        null;

      const bounceBack = (message: string) => {
        setActivationError(message);
        setStage({
          kind: "enter-key",
          providerId,
          spec: specsByProvider.get(providerId) ?? null,
        });
      };

      if (!chosen) {
        bounceBack(
          "This provider has no models registered with the runtime. Pick a different provider, or add models from Settings → Credentials.",
        );
        return;
      }

      try {
        await configApi.setLLMConfig(providerId, chosen);
        setStage({ kind: "done" });
        onComplete();
      } catch (err) {
        const message =
          err instanceof ApiError
            ? `${err.status}: ${err.message}`
            : err instanceof Error
              ? err.message
              : String(err);
        bounceBack(`Could not activate provider: ${message}`);
      }
    },
    [models, onComplete, specsByProvider],
  );

  if (loadError) {
    return (
      <Shell>
        <div className="text-center space-y-3">
          <p className="text-sm font-medium">Could not load providers</p>
          <p className="text-xs text-muted-foreground">{loadError}</p>
        </div>
      </Shell>
    );
  }

  if (!specs || !models || stage.kind === "saving") {
    return (
      <Shell>
        <div className="flex flex-col items-center gap-3 text-sm text-muted-foreground">
          <div className="w-8 h-8 border-2 border-primary/30 border-t-primary rounded-full animate-spin" />
          {stage.kind === "saving"
            ? `Activating ${specsByProvider.get(stage.providerId)?.credential_name ?? stage.providerId}…`
            : "Loading providers…"}
        </div>
      </Shell>
    );
  }

  if (stage.kind === "done") return null;

  if (stage.kind === "pick") {
    return (
      <Shell wide>
        <div className="space-y-6">
          <div className="text-center space-y-2">
            <h1 className="text-2xl font-semibold text-foreground">
              Welcome to Hive
            </h1>
            <p className="text-sm text-muted-foreground">
              Pick an LLM provider to get started. You can add more later from
              the Credentials settings page.
            </p>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 max-h-[60vh] overflow-y-auto pr-1">
            {providerList.map((p) => (
              <button
                key={p.id}
                type="button"
                onClick={() => handlePick(p.id)}
                className="text-left p-4 rounded-lg border border-border/60 bg-card hover:border-primary/50 hover:bg-muted/30 transition-colors"
              >
                <div className="flex items-center justify-between gap-2">
                  <div className="font-medium text-sm text-foreground truncate">
                    {p.label}
                  </div>
                  {p.available && (
                    <span className="text-[10px] uppercase tracking-wide text-emerald-600 flex-shrink-0">
                      Connected
                    </span>
                  )}
                </div>
                {p.description && (
                  <div className="text-xs text-muted-foreground mt-1 line-clamp-2">
                    {p.description}
                  </div>
                )}
              </button>
            ))}
          </div>
          {providerList.length === 0 && (
            <p className="text-xs text-muted-foreground text-center">
              No BYOK providers available. Check the runtime's model
              catalogue at <code>/api/config/models</code>.
            </p>
          )}
          <div className="text-center pt-2">
            <button
              type="button"
              onClick={onSkip ?? onComplete}
              className="text-sm text-muted-foreground hover:text-foreground transition-colors"
            >
              Skip for now
            </button>
          </div>
        </div>
      </Shell>
    );
  }

  return (
    <EnterKey
      providerId={stage.providerId}
      spec={stage.spec}
      fallbackLabel={prettyFallback(stage.providerId)}
      externalError={activationError}
      onBack={handleBack}
      onSaved={() => handleSaved(stage.providerId)}
    />
  );
}

// ---------------------------------------------------------------------------
// Step 2: paste + validate + save
// ---------------------------------------------------------------------------

function EnterKey({
  providerId,
  spec,
  fallbackLabel,
  externalError,
  onBack,
  onSaved,
}: {
  providerId: string;
  spec: CredentialSpec | null;
  fallbackLabel: string;
  /** Surfaced from the parent — e.g. a `setLLMConfig` failure after we already saved the key. */
  externalError: string | null;
  onBack: () => void;
  onSaved: () => void;
}) {
  const [apiKey, setApiKey] = useState("");
  const [validation, setValidation] = useState<
    | { kind: "idle" }
    | { kind: "validating" }
    | { kind: "valid"; message: string }
    | { kind: "invalid"; message: string }
  >({ kind: "idle" });
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const label = spec?.credential_name ?? fallbackLabel;
  const credentialKey = spec?.credential_key ?? "api_key";

  const handleTest = useCallback(async () => {
    if (!apiKey.trim()) return;
    setValidation({ kind: "validating" });
    try {
      const res = await credentialsApi.validateKey(providerId, apiKey.trim());
      if (res.valid === true) {
        setValidation({ kind: "valid", message: res.message || "Key works." });
      } else if (res.valid === false) {
        setValidation({
          kind: "invalid",
          message: res.message || "Key rejected by provider.",
        });
      } else {
        setValidation({
          kind: "valid",
          message:
            res.message ||
            "Could not reach the provider to test the key — saving anyway.",
        });
      }
    } catch (err) {
      setValidation({
        kind: "invalid",
        message: err instanceof Error ? err.message : String(err),
      });
    }
  }, [apiKey, providerId]);

  const handleSave = useCallback(async () => {
    setSaving(true);
    setSaveError(null);
    try {
      await credentialsApi.save(providerId, {
        [credentialKey]: apiKey.trim(),
      });
      onSaved();
    } catch (err) {
      setSaving(false);
      const message =
        err instanceof ApiError
          ? `${err.status}: ${err.message}`
          : err instanceof Error
            ? err.message
            : String(err);
      setSaveError(`Could not save key: ${message}`);
    }
  }, [apiKey, credentialKey, onSaved, providerId]);

  const canSave = validation.kind === "valid" && !saving;

  let helpHost: string | null = null;
  if (spec?.help_url) {
    try {
      helpHost = new URL(spec.help_url).host;
    } catch {
      helpHost = null;
    }
  }

  return (
    <Shell>
      <div className="space-y-5">
        <div className="space-y-1">
          <button
            type="button"
            onClick={onBack}
            className="text-xs text-muted-foreground hover:text-foreground"
          >
            ← Back
          </button>
          <h1 className="text-xl font-semibold text-foreground">
            {label} API key
          </h1>
          {spec?.description && (
            <p className="text-xs text-muted-foreground">{spec.description}</p>
          )}
        </div>

        {spec?.help_url && helpHost && (
          <p className="text-xs text-muted-foreground">
            Get a key at{" "}
            <a
              href={spec.help_url}
              target="_blank"
              rel="noreferrer"
              className="underline hover:text-primary"
            >
              {helpHost}
            </a>
            .
          </p>
        )}

        <div className="space-y-2">
          <label className="text-xs font-medium text-muted-foreground">
            API key
          </label>
          <input
            type="password"
            autoFocus
            value={apiKey}
            onChange={(e) => {
              setApiKey(e.target.value);
              if (validation.kind !== "idle") setValidation({ kind: "idle" });
              if (saveError) setSaveError(null);
            }}
            placeholder={`${label} API key`}
            className="w-full px-3 py-2 text-sm rounded-lg border border-border/60 bg-muted/30 text-foreground placeholder:text-muted-foreground/60 focus:outline-none focus:ring-1 focus:ring-primary/40"
          />
          {spec?.api_key_instructions && (
            <p className="text-[11px] text-muted-foreground whitespace-pre-line">
              {spec.api_key_instructions}
            </p>
          )}
        </div>

        {validation.kind === "validating" && (
          <p className="text-xs text-muted-foreground">Testing key…</p>
        )}
        {validation.kind === "valid" && (
          <p className="text-xs text-emerald-600">✓ {validation.message}</p>
        )}
        {validation.kind === "invalid" && (
          <p className="text-xs text-destructive">✗ {validation.message}</p>
        )}
        {saveError && <p className="text-xs text-destructive">{saveError}</p>}
        {externalError && (
          <p className="text-xs text-destructive">{externalError}</p>
        )}

        <div className="flex gap-2 pt-2">
          <button
            type="button"
            onClick={handleTest}
            disabled={!apiKey.trim() || validation.kind === "validating"}
            className="px-3 py-1.5 text-sm rounded-lg border border-border/60 text-muted-foreground hover:text-foreground hover:bg-muted/40 disabled:opacity-50 transition-colors"
          >
            Test key
          </button>
          <button
            type="button"
            onClick={handleSave}
            disabled={!canSave}
            className="px-3 py-1.5 text-sm font-medium rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50 transition-colors"
          >
            {saving ? "Saving…" : "Continue"}
          </button>
        </div>
      </div>
    </Shell>
  );
}

// ---------------------------------------------------------------------------
// Shell + helpers
// ---------------------------------------------------------------------------

function Shell({
  children,
  wide,
}: {
  children: React.ReactNode;
  wide?: boolean;
}) {
  const width = wide ? "max-w-2xl" : "max-w-md";
  return (
    <div className="flex items-center justify-center h-screen bg-background">
      <div
        className={`w-full ${width} p-8 rounded-xl border border-border/60 bg-card shadow-sm`}
      >
        {children}
      </div>
    </div>
  );
}

/** Title-case a provider id for display when no credential spec exists. */
function prettyFallback(id: string): string {
  return id
    .split(/[_-]/)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}
