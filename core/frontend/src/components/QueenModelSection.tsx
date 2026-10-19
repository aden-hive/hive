import { useCallback, useEffect, useState } from "react";
import { AlertCircle, Cpu, Loader2 } from "lucide-react";
import { queensApi } from "@/api/queens";
import { configApi, type LlmSection } from "@/api/config";
import { ApiError } from "@/api/client";

/**
 * The queen's own model: a section in the main LLM slot's shape, stored under `queen_llm` in
 * configuration.json. Without one she uses the main model (Settings → AI Model). Like the
 * slot editor, it shows and saves the section verbatim, or copies a saved provider into it.
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

export default function QueenModelSection({ queenId }: { queenId: string }) {
  const [section, setSection] = useState<LlmSection | null>(null);
  const [defaultModel, setDefaultModel] = useState<string>("");
  const [library, setLibrary] = useState<Record<string, LlmSection>>({});
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // The JSON being edited; null = editor closed.
  const [text, setText] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [own, lib] = await Promise.all([queensApi.getLlm(queenId), configApi.getProviderLibrary()]);
      setSection(own.section);
      setDefaultModel(own.default_model ?? "");
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
      setText(null);
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't save her model");
    } finally {
      setBusy(false);
    }
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
    <div className="rounded-lg border border-border/60 px-3 py-2.5 text-sm">
      {loading ? (
        <p className="text-muted-foreground inline-flex items-center gap-2">
          <Loader2 className="w-3.5 h-3.5 animate-spin" /> Loading…
        </p>
      ) : (
        <>
          <div className="flex items-start gap-2">
            <Cpu className="w-4 h-4 mt-0.5 text-muted-foreground flex-shrink-0" />
            <div className="min-w-0 flex-1">
              {section ? (
                <p className="text-foreground break-words">{summary(section)}</p>
              ) : (
                <p className="text-foreground">
                  Main model <span className="text-muted-foreground">· {defaultModel || "AI Model → LLM"}</span>
                </p>
              )}
              <p className="text-[11px] text-muted-foreground">
                {section ? "Her own model. Her running chats use it now." : "She uses the main model from Settings → AI Model."}
              </p>
            </div>
          </div>
          {text === null ? (
            <div className="mt-2 flex flex-wrap items-center gap-2">
              {names.length > 0 && (
                <select
                  aria-label="Use a saved provider"
                  value=""
                  disabled={busy}
                  onChange={(e) => e.target.value && void save(library[e.target.value])}
                  className="text-[11px] rounded-md border border-border/60 bg-background text-muted-foreground px-1.5 py-1 outline-none focus:border-primary/50"
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
                className="text-[11px] font-medium px-2 py-1 rounded-md border border-primary/30 text-primary hover:bg-primary/10 transition-colors"
              >
                {section ? "Edit" : "Set her own model"}
              </button>
              {section && (
                <button
                  onClick={() => void save(null)}
                  disabled={busy}
                  className="text-[11px] font-medium px-2 py-1 rounded-md border border-border/60 text-muted-foreground hover:text-foreground transition-colors"
                >
                  Use the main model
                </button>
              )}
              {busy && <Loader2 className="w-3.5 h-3.5 animate-spin text-muted-foreground" />}
            </div>
          ) : (
            <div className="mt-2">
              <textarea
                aria-label="Her model, as JSON"
                value={text}
                onChange={(e) => setText(e.target.value)}
                rows={8}
                spellCheck={false}
                className="w-full rounded-md border border-border/60 bg-background px-2.5 py-2 text-[11.5px] font-mono text-foreground outline-none focus:border-primary/50 resize-y"
              />
              <div className="mt-2 flex items-center justify-end gap-2">
                <button
                  onClick={() => {
                    setText(null);
                    setError(null);
                  }}
                  className="text-[11px] font-medium px-2.5 py-1.5 rounded-md border border-border/60 text-muted-foreground hover:text-foreground transition-colors"
                >
                  Cancel
                </button>
                <button
                  onClick={saveText}
                  disabled={busy}
                  className="text-[11px] font-medium px-2.5 py-1.5 rounded-md bg-primary text-primary-foreground disabled:opacity-50 inline-flex items-center gap-1"
                >
                  {busy ? <Loader2 className="w-3 h-3 animate-spin" /> : null}
                  Save
                </button>
              </div>
            </div>
          )}
          {error && (
            <p className="mt-1.5 text-[11px] text-red-500 inline-flex items-start gap-1">
              <AlertCircle className="w-3 h-3 mt-0.5 flex-shrink-0" /> {error}
            </p>
          )}
        </>
      )}
    </div>
  );
}
