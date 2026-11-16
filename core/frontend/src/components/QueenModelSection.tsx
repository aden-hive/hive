import { useCallback, useEffect, useRef, useState } from "react";
import { AlertCircle, ChevronRight, Cpu, Loader2 } from "lucide-react";
import { queensApi } from "@/api/queens";
import { configApi, type LlmSection } from "@/api/config";
import { ApiError } from "@/api/client";
import { modelsApi, type ModelChoice, type ModelsOverview } from "@/api/models";
import ModelPicker from "@/components/ModelPicker";

/**
 * The queen's own model, stored under `queen_llm` in configuration.json. Without one she uses
 * the main model (the Models page). She gets one from the same searchable list as every other
 * slot; under Advanced, her section can be edited as JSON, or a saved provider copied into it.
 * Styled for her profile page (the `qp-` classes).
 */

const TEMPLATE: LlmSection = {
  provider: "openai",
  model: "model-id",
  api_base: "https://api.example.com/v1",
  api_key: "sk-...",
};

function summary(s: LlmSection): string {
  const key = typeof s.api_key === "string" && s.api_key ? "key ****" + s.api_key.slice(-4) : s.api_key_env_var ? `key from $${s.api_key_env_var}` : "no key";
  return [s.model, s.api_base, key].filter(Boolean).join(" · ");
}

export default function QueenModelSection({ queenId, onChange }: { queenId: string; onChange?: (model: string) => void }) {
  const [section, setSection] = useState<LlmSection | null>(null);
  const [defaultModel, setDefaultModel] = useState<string>("");
  const [library, setLibrary] = useState<Record<string, LlmSection>>({});
  const [overview, setOverview] = useState<ModelsOverview | null>(null);
  const [advanced, setAdvanced] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // The JSON being edited; null = editor closed.
  const [text, setText] = useState<string | null>(null);
  // Tells the caller the model she now speaks with; a ref, so a new callback doesn't reload.
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [own, lib, models] = await Promise.all([
        queensApi.getLlm(queenId),
        configApi.getProviderLibrary(),
        // Without it she can still be set by hand under Advanced.
        modelsApi.overview().catch(() => null),
      ]);
      setOverview(models);
      setSection(own.section);
      setDefaultModel(own.default_model ?? "");
      onChangeRef.current?.(own.section?.model ?? own.default_model ?? "");
      setLibrary(lib.library);
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't load her model");
    } finally {
      setLoading(false);
    }
  }, [queenId]);
  useEffect(() => {
    void load();
  }, [load]);

  const save = async (next: LlmSection | null) => {
    setBusy(true);
    try {
      const res = await queensApi.setLlm(queenId, next);
      setSection(res.section);
      onChangeRef.current?.(res.section?.model ?? res.default_model ?? defaultModel);
      setText(null);
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't save her model");
    } finally {
      setBusy(false);
    }
  };

  const pick = async (choice: ModelChoice | null) => {
    if (choice) await modelsApi.setSlot(`queen:${queenId}`, choice);
    else await modelsApi.clearSlot(`queen:${queenId}`);
    await load();
  };

  const saveText = () => {
    if (text === null) return;
    let parsed: unknown;
    try {
      parsed = JSON.parse(text);
    } catch {
      setError("Not valid JSON");
      return;
    }
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      setError("Must be a JSON object");
      return;
    }
    void save(parsed as LlmSection);
  };

  const names = Object.keys(library);

  return (
    <div className="qp-card px-5 py-4 text-sm">
      {loading ? (
        <p className="qp-meta inline-flex items-center gap-2">
          <Loader2 className="w-3.5 h-3.5 animate-spin" /> Loading…
        </p>
      ) : (
        <>
          <div className="flex items-start gap-3">
            <span className="qp-pillar-icon">
              <Cpu className="w-4 h-4" />
            </span>
            <div className="min-w-0 flex-1">
              {section ? (
                <p className="text-[14px] text-foreground break-words">{summary(section)}</p>
              ) : (
                <p className="text-[14px] text-foreground break-words">
                  Main model <span className="text-muted-foreground">· {defaultModel || "AI Model → LLM"}</span>
                </p>
              )}
              <p className="mt-0.5 text-[12px] text-muted-foreground">
                {section ? "Her own model. Her running chats use it now." : "She uses the main model from the Models page."}
              </p>
            </div>
          </div>
          {overview && text === null && (
            <div className="mt-4">
              <ModelPicker
                overview={overview}
                value={overview.queens.find((q) => q.id === queenId) ?? null}
                placeholder="Use the main model"
                onPick={(choice) => pick(choice)}
                onClear={() => pick(null)}
                ariaLabel="Her model"
              />
            </div>
          )}
          <button
            type="button"
            onClick={() => setAdvanced((v) => !v)}
            className="mt-3 inline-flex items-center gap-1 text-[12px] text-muted-foreground hover:text-foreground"
          >
            <ChevronRight className={`w-3.5 h-3.5 transition-transform ${advanced ? "rotate-90" : ""}`} /> Advanced
          </button>
          {!advanced ? null : text === null ? (
            <div className="mt-2 flex flex-wrap items-center gap-2">
              {names.length > 0 && (
                <select
                  aria-label="Use a saved provider"
                  value=""
                  disabled={busy}
                  onChange={(e) => e.target.value && void save(library[e.target.value])}
                  className="qp-input !w-auto !py-1 text-[12px] text-muted-foreground"
                >
                  <option value="">Use a saved provider…</option>
                  {names.map((n) => (
                    <option key={n} value={n}>
                      {n}
                    </option>
                  ))}
                </select>
              )}
              <button
                onClick={() => {
                  setError(null);
                  setText(JSON.stringify(section ?? TEMPLATE, null, 2));
                }}
                disabled={busy}
                className="qp-btn"
                data-size="sm"
              >
                {section ? "Edit" : "Set her own model"}
              </button>
              {section && (
                <button onClick={() => void save(null)} disabled={busy} className="qp-btn" data-tone="quiet" data-size="sm">
                  Use the main model
                </button>
              )}
              {busy && <Loader2 className="w-3.5 h-3.5 animate-spin text-muted-foreground" />}
            </div>
          ) : (
            <div className="mt-4">
              <textarea
                aria-label="Her model, as JSON"
                value={text}
                onChange={(e) => setText(e.target.value)}
                rows={8}
                spellCheck={false}
                className="qp-editor"
              />
              <div className="qp-edit-foot">
                <span />
                <div>
                  <button
                    onClick={() => {
                      setText(null);
                      setError(null);
                    }}
                    className="qp-btn"
                    data-tone="quiet"
                    data-size="sm"
                  >
                    Cancel
                  </button>
                  <button onClick={saveText} disabled={busy} className="qp-btn" data-tone="primary" data-size="sm">
                    {busy ? <Loader2 className="w-3 h-3 animate-spin" /> : null}
                    Save
                  </button>
                </div>
              </div>
            </div>
          )}
          {error && (
            <p className="qp-error mt-2">
              <AlertCircle className="w-3.5 h-3.5" /> {error}
            </p>
          )}
        </>
      )}
    </div>
  );
}
