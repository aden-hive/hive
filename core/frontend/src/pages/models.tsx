import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { AlertCircle, ChevronRight, Cpu, ExternalLink, KeyRound, Loader2, Plus, RefreshCw, Server, Trash2, TriangleAlert } from "lucide-react";
import { credentialsApi } from "@/api/credentials";
import { modelsApi, type ModelChoice, type ModelEndpoint, type ModelsOverview, type RoleSlot, type SlotId } from "@/api/models";
import ModelPicker, { providerName } from "@/components/ModelPicker";
import { isJudgeSetup, ProviderConfigEditor, ProviderSlots, SavedSetups, useProviderConfig } from "@/components/ProviderManager";
import { ProviderLogo } from "@/components/ProviderLogo";
import { useModelOptional } from "@/context/ModelContext";

/**
 * Models: which model each part of Hive uses, and where models come from. A model is picked from a
 * searchable list (endpoints such as Magpie list theirs live); providers' keys, endpoints, saved
 * setups and detected subscriptions are kept below. The raw slot editor stays under Advanced.
 */

const ROLE_SLOTS: Array<{ slot: RoleSlot; title: string; description: string; placeholder: string; clearable: boolean }> = [
  { slot: "llm", title: "Main model", description: "Every queen thinks with it, unless she has her own.", placeholder: "Pick a model", clearable: false },
  { slot: "worker_llm", title: "Workers", description: "The workers a colony sends out.", placeholder: "Same as the main model", clearable: true },
  {
    slot: "vision_fallback",
    title: "Vision fallback",
    description: "Describes images for a model that can't see them.",
    placeholder: "None",
    clearable: true,
  },
];

function Section({ title, lede, children }: { title: string; lede: string; children: React.ReactNode }) {
  return (
    <section className="mb-8">
      <h3 className="text-sm font-semibold text-foreground">{title}</h3>
      <p className="text-xs text-muted-foreground mt-0.5 mb-3">{lede}</p>
      {children}
    </section>
  );
}

function ErrorLine({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <div role="alert" className="mt-2 flex items-start gap-1.5 text-xs text-destructive">
      <AlertCircle className="w-3.5 h-3.5 mt-px shrink-0" /> {message}
    </div>
  );
}

const message = (e: unknown) => (e instanceof Error ? e.message : String(e));

function EndpointCard({ endpoint, onChanged }: { endpoint: ModelEndpoint; onChanged: () => Promise<void> }) {
  const [editing, setEditing] = useState(false);
  const [base, setBase] = useState(endpoint.api_base);
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const title = endpoint.builtin ? "Magpie" : endpoint.name;

  const run = async (action: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await action();
      setEditing(false);
      setKey("");
      await onChanged();
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded-lg border border-border/60 bg-card p-3">
      <div className="flex items-center gap-2">
        <Server className="w-4 h-4 text-muted-foreground" />
        <span className="text-sm font-medium">{title}</span>
        <span
          className={`ml-1 inline-flex items-center gap-1 text-[11px] ${endpoint.running ? "text-emerald-600" : "text-muted-foreground"}`}
          title={endpoint.running ? "It answers" : "It doesn't answer"}
        >
          <span className={`w-1.5 h-1.5 rounded-full ${endpoint.running ? "bg-emerald-500" : "bg-muted-foreground/40"}`} />
          {endpoint.running ? "Running" : "Not running"}
        </span>
        {endpoint.has_key && (
          <span className="text-[11px] text-muted-foreground inline-flex items-center gap-1">
            <KeyRound className="w-3 h-3" /> key saved
          </span>
        )}
        <div className="ml-auto flex items-center gap-1">
          <button type="button" onClick={() => setEditing((v) => !v)} className="text-xs text-muted-foreground hover:text-foreground px-2 py-1">
            {editing ? "Cancel" : "Edit"}
          </button>
          {!endpoint.builtin && (
            <button
              type="button"
              title="Remove this endpoint"
              aria-label={`Remove ${title}`}
              disabled={busy}
              onClick={() => run(() => modelsApi.deleteEndpoint(endpoint.name))}
              className="p-1 text-muted-foreground hover:text-destructive"
            >
              <Trash2 className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
      </div>
      <div className="mt-1 text-xs text-muted-foreground break-all">{endpoint.api_base}</div>
      {endpoint.builtin && !endpoint.running && (
        <div className="mt-1.5 text-xs text-muted-foreground">
          A gateway on this computer in front of many vendors, subscriptions and routing groups.{" "}
          <a href="https://usemagpie.ai" target="_blank" rel="noreferrer" className="text-primary inline-flex items-center gap-0.5 hover:underline">
            Get Magpie <ExternalLink className="w-3 h-3" />
          </a>
        </div>
      )}
      {editing && (
        <div className="mt-3 grid gap-2">
          <label className="text-xs text-muted-foreground">
            Address
            <input value={base} onChange={(e) => setBase(e.target.value)} className="mt-1 w-full rounded-md border border-border/60 bg-background px-2 py-1.5 text-sm" />
          </label>
          <label className="text-xs text-muted-foreground">
            Key {endpoint.builtin ? "(a gateway key, only when Magpie is on another computer)" : "(optional)"}
            <input
              type="password"
              value={key}
              placeholder={endpoint.has_key ? "Leave empty to keep the saved key" : ""}
              onChange={(e) => setKey(e.target.value)}
              className="mt-1 w-full rounded-md border border-border/60 bg-background px-2 py-1.5 text-sm"
            />
          </label>
          <div className="flex items-center gap-2">
            <button
              type="button"
              disabled={busy}
              onClick={() => run(() => modelsApi.saveEndpoint(endpoint.name, { api_base: base, ...(key ? { api_key: key } : {}) }))}
              className="rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground disabled:opacity-60"
            >
              {busy ? "Saving…" : "Save"}
            </button>
            {endpoint.has_key && (
              <button
                type="button"
                disabled={busy}
                onClick={() => run(() => modelsApi.saveEndpoint(endpoint.name, { api_base: base, api_key: null }))}
                className="text-xs text-muted-foreground hover:text-destructive"
              >
                Remove the key
              </button>
            )}
          </div>
        </div>
      )}
      <ErrorLine message={error} />
    </div>
  );
}

function AddEndpoint({ onChanged }: { onChanged: () => Promise<void> }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [base, setBase] = useState("");
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="flex items-center gap-1.5 rounded-lg border border-dashed border-border/80 px-3 py-2.5 text-xs text-muted-foreground hover:text-foreground hover:border-primary/40"
      >
        <Plus className="w-3.5 h-3.5" /> Add an OpenAI-compatible endpoint (Ollama, vLLM, LM Studio, a gateway)
      </button>
    );
  }
  const add = async () => {
    setBusy(true);
    setError(null);
    try {
      await modelsApi.saveEndpoint(name.trim(), { api_base: base.trim(), ...(key.trim() ? { api_key: key.trim() } : {}) });
      setOpen(false);
      setName("");
      setBase("");
      setKey("");
      await onChanged();
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="rounded-lg border border-border/60 bg-card p-3 grid gap-2">
      <label className="text-xs text-muted-foreground">
        Name
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="ollama" className="mt-1 w-full rounded-md border border-border/60 bg-background px-2 py-1.5 text-sm" />
      </label>
      <label className="text-xs text-muted-foreground">
        Address
        <input
          value={base}
          onChange={(e) => setBase(e.target.value)}
          placeholder="http://localhost:11434/v1"
          className="mt-1 w-full rounded-md border border-border/60 bg-background px-2 py-1.5 text-sm"
        />
      </label>
      <label className="text-xs text-muted-foreground">
        Key (optional)
        <input type="password" value={key} onChange={(e) => setKey(e.target.value)} className="mt-1 w-full rounded-md border border-border/60 bg-background px-2 py-1.5 text-sm" />
      </label>
      <div className="flex items-center gap-2">
        <button type="button" disabled={busy || !name.trim() || !base.trim()} onClick={add} className="rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground disabled:opacity-60">
          {busy ? "Adding…" : "Add"}
        </button>
        <button type="button" onClick={() => setOpen(false)} className="text-xs text-muted-foreground hover:text-foreground">
          Cancel
        </button>
      </div>
      <ErrorLine message={error} />
    </div>
  );
}

function ProviderKey({ id, connected, onChanged }: { id: string; connected: boolean; onChanged: () => Promise<void> }) {
  const model = useModelOptional();
  const [editing, setEditing] = useState(false);
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      const check = await credentialsApi.validateKey(id, key.trim()).catch(() => ({ valid: null as boolean | null, message: "" }));
      if (check.valid === false) throw new Error(check.message || "The key was refused");
      if (model) await model.saveProviderKey(id, key.trim());
      else await credentialsApi.save(id, { api_key: key.trim() });
      setEditing(false);
      setKey("");
      await onChanged();
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  };
  const remove = async () => {
    setBusy(true);
    setError(null);
    try {
      if (model) await model.removeProviderKey(id);
      else await credentialsApi.delete(id);
      await onChanged();
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded-lg border border-border/60 bg-card px-3 py-2">
      <div className="flex items-center gap-2">
        <ProviderLogo provider={id} size={16} />
        <span className="text-sm">{providerName(id)}</span>
        {connected && <span className="text-[11px] text-emerald-600">key saved</span>}
        <div className="ml-auto flex items-center gap-2">
          <button type="button" onClick={() => setEditing((v) => !v)} className="text-xs text-muted-foreground hover:text-foreground">
            {editing ? "Cancel" : connected ? "Replace key" : "Add key"}
          </button>
          {connected && !editing && (
            <button type="button" disabled={busy} onClick={remove} className="text-xs text-muted-foreground hover:text-destructive">
              Remove
            </button>
          )}
        </div>
      </div>
      {editing && (
        <div className="mt-2 flex items-center gap-2">
          <input
            type="password"
            value={key}
            aria-label={`${providerName(id)} API key`}
            onChange={(e) => setKey(e.target.value)}
            className="flex-1 rounded-md border border-border/60 bg-background px-2 py-1.5 text-sm"
          />
          <button type="button" disabled={busy || !key.trim()} onClick={save} className="rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground disabled:opacity-60">
            {busy ? "Checking…" : "Save"}
          </button>
        </div>
      )}
      <ErrorLine message={error} />
    </div>
  );
}

export default function ModelsPage() {
  const model = useModelOptional();
  const [overview, setOverview] = useState<ModelsOverview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [advanced, setAdvanced] = useState(false);
  const [subError, setSubError] = useState<string | null>(null);
  const [judgeBusy, setJudgeBusy] = useState(false);
  const [judgeError, setJudgeError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setOverview(await modelsApi.overview());
      setError(null);
    } catch (e) {
      setError(message(e));
    }
  }, []);

  // A change here changes what the rest of the dashboard says (the "no model yet" notice, say).
  const changed = useCallback(async () => {
    await load();
    await model?.refresh();
  }, [load, model]);
  const providers = useProviderConfig(changed);

  useEffect(() => {
    void load();
  }, [load]);

  const pick = (slot: SlotId) => async (choice: ModelChoice) => {
    await modelsApi.setSlot(slot, choice);
    await changed();
  };
  const clear = (slot: SlotId) => async () => {
    await modelsApi.clearSlot(slot);
    await changed();
  };
  const switchToSubscription = async (id: string) => {
    setSubError(null);
    try {
      if (model) await model.activateSubscription(id);
      await changed();
    } catch (e) {
      setSubError(message(e));
    }
  };

  const applySavedJudge = async (name: string) => {
    setJudgeError(null);
    setJudgeBusy(true);
    try {
      await providers.applySaved(name, "judge");
    } catch (e) {
      setJudgeError(message(e));
    } finally {
      setJudgeBusy(false);
    }
  };

  const detected = overview?.subscriptions.filter((s) => s.detected) ?? [];
  // A judge isn't a chat model, so its saved setups go to the Judge row and no model list.
  const chatSetups = Object.fromEntries(Object.entries(providers.library).filter(([, s]) => !isJudgeSetup(s)));
  const judgeSetups = providers.libraryNames.filter((name) => isJudgeSetup(providers.library[name]));

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="max-w-3xl mx-auto px-6 py-6">
        <div className="flex items-center gap-2 mb-1">
          <Cpu className="w-5 h-5 text-primary" />
          <h2 className="text-lg font-semibold">Models</h2>
          <button
            type="button"
            onClick={() => {
              void load();
              void providers.reload();
            }}
            title="Refresh"
            className="ml-auto p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted"
          >
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>
        <p className="text-sm text-muted-foreground mb-6">Which model each part of Hive thinks with, and where models come from.</p>
        <ErrorLine message={error} />

        {!overview ? (
          !error && (
            <div className="flex justify-center py-12 text-muted-foreground">
              <Loader2 className="w-5 h-5 animate-spin" />
            </div>
          )
        ) : (
          <>
            <Section title="In use" lede="Picking a model applies at once; the main model switches running chats too.">
              <div className="grid gap-3">
                {ROLE_SLOTS.map((row) => (
                  <div key={row.slot} className="grid sm:grid-cols-[180px_1fr] gap-2 items-start">
                    <div>
                      <div className="text-sm font-medium">{row.title}</div>
                      <div className="text-xs text-muted-foreground">{row.description}</div>
                    </div>
                    <ModelPicker
                      overview={overview}
                      value={overview.slots[row.slot]}
                      placeholder={row.placeholder}
                      onPick={pick(row.slot)}
                      onClear={row.clearable ? clear(row.slot) : undefined}
                      saved={chatSetups}
                      onPickSaved={(name) => providers.applySaved(name, row.slot)}
                      ariaLabel={row.title}
                    />
                  </div>
                ))}
                <div className="grid sm:grid-cols-[180px_1fr] gap-2 items-start">
                  <div>
                    <div className="text-sm font-medium">Judge</div>
                    <div className="text-xs text-muted-foreground">Answers yes-or-no questions (the stall check, chiming in).</div>
                  </div>
                  <div>
                    <div className="flex flex-wrap items-center gap-2 rounded-lg border border-border/60 px-3 py-2 text-sm text-muted-foreground">
                      <span className="min-w-0 break-all">
                        {overview.judge.configured ? `${overview.judge.model ?? "set"} · ${overview.judge.api_base}` : "Not set"}
                      </span>
                      <div className="ml-auto flex items-center gap-2">
                        {judgeBusy && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                        {judgeSetups.length > 0 && (
                          <select
                            value=""
                            disabled={judgeBusy}
                            aria-label="Use a saved judge"
                            onChange={(e) => {
                              if (e.target.value) void applySavedJudge(e.target.value);
                            }}
                            className="rounded-md border border-border/60 bg-background px-1.5 py-0.5 text-xs"
                          >
                            <option value="">Use saved…</option>
                            {judgeSetups.map((name) => (
                              <option key={name} value={name}>
                                {name}
                              </option>
                            ))}
                          </select>
                        )}
                        <button type="button" onClick={() => setAdvanced(true)} className="text-xs text-primary hover:underline">
                          Edit under Advanced
                        </button>
                      </div>
                    </div>
                    <ErrorLine message={judgeError} />
                  </div>
                </div>
              </div>
              {overview.queens.length > 0 && (
                <div className="mt-4">
                  <div className="text-xs font-medium text-muted-foreground mb-1.5">Queens with a model of their own</div>
                  <div className="grid gap-1">
                    {overview.queens.map((q) => (
                      <Link
                        key={q.id}
                        to={`/queen/${q.id}/profile`}
                        className="flex items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-muted"
                      >
                        <span className="font-medium">{q.name}</span>
                        <span className="text-muted-foreground truncate">{q.model}</span>
                        <ChevronRight className="w-3.5 h-3.5 ml-auto text-muted-foreground" />
                      </Link>
                    ))}
                  </div>
                </div>
              )}
            </Section>

            <Section title="Endpoints" lede="Addresses that speak the OpenAI API and list their own models: Magpie, Ollama, vLLM, LM Studio, a gateway.">
              <div className="grid gap-2">
                {overview.endpoints.map((e) => (
                  <EndpointCard key={e.name} endpoint={e} onChanged={changed} />
                ))}
                <AddEndpoint onChanged={changed} />
              </div>
            </Section>

            <Section title="API keys" lede="A provider's models appear in the lists once its key is saved. Keys are kept in the encrypted credential store.">
              <div className="grid gap-2">
                {overview.providers.map((p) => (
                  <ProviderKey key={p.id} id={p.id} connected={p.connected} onChanged={changed} />
                ))}
              </div>
            </Section>

            <Section
              title="Saved setups"
              lede="Whole configs kept by name in configuration.json: model, address, key and any extra fields. The model lists above offer them, and a judge's is on the Judge row."
            >
              <SavedSetups cfg={providers} />
            </Section>

            {detected.length > 0 && (
              <Section title="Subscriptions" lede="Plans signed in on this computer, which can run the main model.">
                <div role="note" className="mb-3 flex items-start gap-2 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs">
                  <TriangleAlert className="w-3.5 h-3.5 mt-0.5 shrink-0 text-amber-600" />
                  <span>
                    Running a subscription unattended, on behalf of agents, may go against the terms of the plan, and the account may be limited or
                    closed. Using one is at your own risk; an API key is the supported way.
                  </span>
                </div>
                <div className="grid gap-2">
                  {detected.map((s) => (
                    <div key={s.id} className="flex items-center gap-2 rounded-lg border border-border/60 bg-card px-3 py-2">
                      <div className="min-w-0">
                        <div className="text-sm">{s.name}</div>
                        <div className="text-xs text-muted-foreground">
                          {s.description} · {s.model}
                        </div>
                      </div>
                      {s.active ? (
                        <span className="ml-auto text-xs text-emerald-600">In use</span>
                      ) : (
                        <button type="button" onClick={() => switchToSubscription(s.id)} className="ml-auto text-xs text-primary hover:underline">
                          Use as the main model
                        </button>
                      )}
                    </div>
                  ))}
                </div>
                <ErrorLine message={subError} />
              </Section>
            )}

            <section>
              <button type="button" onClick={() => setAdvanced((v) => !v)} className="flex items-center gap-1 text-sm font-semibold text-foreground">
                <ChevronRight className={`w-4 h-4 transition-transform ${advanced ? "rotate-90" : ""}`} /> Advanced
              </button>
              <p className="text-xs text-muted-foreground mt-0.5 mb-3">
                Each slot, the judge included, as written in configuration.json (fields such as extra_body).
              </p>
              {advanced && <ProviderSlots cfg={providers} />}
            </section>
          </>
        )}
        <ProviderConfigEditor cfg={providers} />
      </div>
    </div>
  );
}
