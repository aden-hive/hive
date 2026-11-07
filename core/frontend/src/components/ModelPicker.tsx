import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { AlertCircle, Bookmark, Check, ChevronDown, Eye, Loader2, Server, Star } from "lucide-react";
import type { LlmSection } from "@/api/config";
import {
  contextLabel,
  modelsApi,
  type EndpointModel,
  type ModelChoice,
  type ModelsOverview,
  type SlotSummary,
} from "@/api/models";
import { LLM_PROVIDERS } from "@/context/ModelContext";
import { ProviderLogo } from "@/components/ProviderLogo";
import { SearchInput } from "@/components/SearchInput";
import { cn } from "@/lib/utils";

/**
 * Pick a model for one slot: a searchable list, grouped by where models come from. Endpoints
 * (Magpie, Ollama, ...) list theirs live; catalog providers show their models once their key is in;
 * saved setups, when given, are copied into the slot whole. Picking applies at once; a failure
 * shows its reason under the button.
 */

const MENU_HEIGHT = 420;
const MENU_WIDTH = 400;

export function providerName(id: string | null | undefined): string {
  if (!id) return "";
  return LLM_PROVIDERS.find((p) => p.id === id)?.name ?? id;
}

/** "kimi/k3 · Magpie", "Claude Sonnet · Anthropic (Claude)", or the placeholder. */
export function slotLabel(summary: SlotSummary | null): { model: string; from: string } | null {
  if (!summary) return null;
  if (summary.source === "endpoint") return { model: summary.model, from: summary.endpoint === "magpie" ? "Magpie" : summary.endpoint ?? "" };
  if (summary.source === "custom") return { model: summary.model, from: summary.api_base ?? "custom address" };
  if (summary.source === "subscription") return { model: summary.model, from: `${summary.subscription} subscription` };
  return { model: summary.model, from: providerName(summary.provider) };
}

/** The saved setup a slot was copied from, judged by what the slot's summary shows of it. */
function savedSetupOf(summary: SlotSummary | null, saved: Record<string, LlmSection>): string | null {
  if (!summary || summary.endpoint) return null;
  const same = ([, s]: [string, LlmSection]) =>
    s.model === summary.model &&
    (s.provider ?? null) === summary.provider &&
    (s.api_base ?? null) === summary.api_base &&
    (s.max_context_tokens ?? null) === summary.max_context_tokens;
  return Object.entries(saved).find(same)?.[0] ?? null;
}

interface ModelPickerProps {
  overview: ModelsOverview;
  value: SlotSummary | null;
  /** Shown when the slot has no model of its own ("Same as the main model", "None"). */
  placeholder: string;
  onPick: (choice: ModelChoice) => Promise<void>;
  /** Offered first in the list when given: returns the slot to its default. */
  onClear?: () => Promise<void>;
  /** Saved setups by name, offered as a group of their own; picking one calls `onPickSaved`. */
  saved?: Record<string, LlmSection>;
  onPickSaved?: (name: string) => Promise<void>;
  ariaLabel?: string;
}

interface Row {
  key: string;
  /** A model to pick, or the name of a saved setup to copy in. */
  choice: ModelChoice | { saved: string };
  label: string;
  hint: string | null;
  recommended?: boolean;
  vision?: boolean;
}

export default function ModelPicker({ overview, value, placeholder, onPick, onClear, saved, onPickSaved, ariaLabel }: ModelPickerProps) {
  const [open, setOpen] = useState(false);
  const [rect, setRect] = useState<DOMRect | null>(null);
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [live, setLive] = useState<Record<string, EndpointModel[] | { error: string } | "loading">>({});
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);

  const reachable = useMemo(() => overview.endpoints.filter((e) => e.running), [overview.endpoints]);

  // An endpoint's models are asked for when the list opens (Magpie's change as its providers do).
  useEffect(() => {
    if (!open) return;
    for (const endpoint of reachable) {
      if (live[endpoint.name]) continue;
      setLive((l) => ({ ...l, [endpoint.name]: "loading" }));
      modelsApi
        .endpointModels(endpoint.name)
        .then((r) => setLive((l) => ({ ...l, [endpoint.name]: r.models })))
        .catch((e: unknown) => setLive((l) => ({ ...l, [endpoint.name]: { error: e instanceof Error ? e.message : String(e) } })));
    }
  }, [open, reachable, live]);

  useLayoutEffect(() => {
    setRect(open ? triggerRef.current?.getBoundingClientRect() ?? null : null);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      const target = e.target as Node;
      if (triggerRef.current?.contains(target) || menuRef.current?.contains(target)) return;
      setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    const onResize = () => setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    window.addEventListener("resize", onResize);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
      window.removeEventListener("resize", onResize);
    };
  }, [open]);

  const groups = useMemo(() => {
    const q = query.trim().toLowerCase();
    const matches = (row: Row, group: string) => !q || `${row.label} ${row.key} ${group}`.toLowerCase().includes(q);
    const out: Array<{ key: string; title: string; logo?: string; saved?: boolean; note?: string; rows: Row[] }> = [];
    for (const endpoint of reachable) {
      const title = endpoint.name === "magpie" ? "Magpie" : endpoint.name;
      const state = live[endpoint.name];
      const rows: Row[] = Array.isArray(state)
        ? state.map((m) => ({
            key: `endpoint:${endpoint.name}:${m.id}`,
            choice: { source: "endpoint", endpoint: endpoint.name, model: m.id },
            label: m.label ? `${m.label} (${m.id})` : m.id,
            hint: contextLabel(m.max_context_tokens),
          }))
        : [];
      const note = state === "loading" || state === undefined ? "Asking it for its models…" : !Array.isArray(state) ? state.error : undefined;
      const shown = rows.filter((r) => matches(r, title));
      if (shown.length || note) out.push({ key: `endpoint:${endpoint.name}`, title, note, rows: shown });
    }
    for (const provider of overview.providers.filter((p) => p.connected)) {
      const title = providerName(provider.id);
      const rows = provider.models
        .map<Row>((m) => ({
          key: `catalog:${provider.id}:${m.id}`,
          choice: { source: "catalog", provider: provider.id, model: m.id },
          label: m.label,
          hint: contextLabel(m.max_context_tokens),
          recommended: m.recommended,
          vision: m.supports_vision,
        }))
        .filter((r) => matches(r, title));
      if (rows.length) out.push({ key: `catalog:${provider.id}`, title, logo: provider.id, rows });
    }
    if (saved && onPickSaved) {
      const title = "Saved setups";
      const rows = Object.entries(saved)
        .sort(([a], [b]) => a.localeCompare(b))
        .map<Row>(([name, s]) => ({
          key: `saved:${name}`,
          choice: { saved: name },
          label: name,
          hint: s.model ?? null,
        }))
        .filter((r) => matches(r, `${title} ${r.hint ?? ""}`));
      // First: a short list of the user's own, which an endpoint's hundreds of models would bury.
      if (rows.length) out.unshift({ key: "saved", title, saved: true, rows });
    }
    return out;
  }, [overview, reachable, live, query, saved, onPickSaved]);

  const savedName = saved ? savedSetupOf(value, saved) : null;
  const isCurrent = (choice: Row["choice"]) =>
    "saved" in choice
      ? choice.saved === savedName
      : !!value &&
        !savedName &&
        value.model === choice.model &&
        (choice.source === "endpoint" ? value.endpoint === choice.endpoint : value.source === "catalog" && value.provider === choice.provider);
  const pickRow = (choice: Row["choice"]) => ("saved" in choice ? onPickSaved!(choice.saved) : onPick(choice));

  const apply = async (run: () => Promise<void>) => {
    setOpen(false);
    setBusy(true);
    setError(null);
    try {
      await run();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const shown = slotLabel(value);
  const label = shown && savedName ? { ...shown, from: savedName } : shown;
  const style: React.CSSProperties | null = rect
    ? (() => {
        const width = Math.max(rect.width, MENU_WIDTH);
        const left = Math.max(8, Math.min(rect.left, window.innerWidth - width - 8));
        const openUp = rect.bottom + MENU_HEIGHT > window.innerHeight && rect.top > window.innerHeight - rect.bottom;
        return openUp
          ? { position: "fixed", bottom: window.innerHeight - rect.top + 4, left, width }
          : { position: "fixed", top: rect.bottom + 4, left, width };
      })()
    : null;

  return (
    <div className="min-w-0">
      <button
        ref={triggerRef}
        type="button"
        aria-label={ariaLabel}
        aria-haspopup="listbox"
        aria-expanded={open}
        disabled={busy}
        onClick={() => setOpen((o) => !o)}
        className={cn(
          "w-full flex items-center gap-2 rounded-lg border border-border/60 bg-background px-3 py-2 text-left hover:border-primary/40 transition-colors disabled:opacity-60",
          open && "border-primary/60",
        )}
      >
        {savedName ? (
          <Bookmark className="w-4 h-4 shrink-0 text-muted-foreground" />
        ) : value?.source === "catalog" && value.provider ? (
          <ProviderLogo provider={value.provider} size={18} />
        ) : (
          <Server className="w-4 h-4 shrink-0 text-muted-foreground" />
        )}
        <span className="min-w-0 flex-1">
          {label ? (
            <>
              <span className="block truncate text-sm text-foreground">{label.model}</span>
              <span className="block truncate text-[11px] text-muted-foreground">
                {label.from}
                {value?.max_context_tokens ? ` · ${contextLabel(value.max_context_tokens)} context` : ""}
              </span>
            </>
          ) : (
            <span className="block truncate text-sm text-muted-foreground">{placeholder}</span>
          )}
        </span>
        {busy ? <Loader2 className="w-4 h-4 animate-spin text-muted-foreground" /> : <ChevronDown className="w-4 h-4 text-muted-foreground/60" />}
      </button>
      {error && (
        <div role="alert" className="mt-1.5 flex items-start gap-1.5 text-xs text-destructive">
          <AlertCircle className="w-3.5 h-3.5 mt-px shrink-0" /> {error}
        </div>
      )}

      {open &&
        style &&
        createPortal(
          <div
            ref={menuRef}
            role="listbox"
            style={{ ...style, maxHeight: MENU_HEIGHT }}
            className="z-50 flex flex-col rounded-lg border border-border/60 bg-card shadow-xl"
          >
            <div className="p-2 border-b border-border/50">
              <SearchInput value={query} onChange={setQuery} placeholder="Search models" autoFocus />
            </div>
            <div className="overflow-y-auto p-1">
              {onClear && !query && (
                <button
                  type="button"
                  role="option"
                  aria-selected={!value}
                  onClick={() => apply(onClear)}
                  className="w-full flex items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-sm hover:bg-muted"
                >
                  <span className="flex-1">{placeholder}</span>
                  {!value && <Check className="w-3.5 h-3.5 text-primary" />}
                </button>
              )}
              {groups.map((group) => (
                <div key={group.key} className="mt-1">
                  <div className="flex items-center gap-1.5 px-2.5 pt-1.5 pb-1 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
                    {group.logo ? (
                      <ProviderLogo provider={group.logo} size={12} />
                    ) : group.saved ? (
                      <Bookmark className="w-3 h-3" />
                    ) : (
                      <Server className="w-3 h-3" />
                    )}
                    {group.title}
                  </div>
                  {group.note && <div className="px-2.5 pb-1 text-xs text-muted-foreground">{group.note}</div>}
                  {group.rows.map((row) => {
                    const current = isCurrent(row.choice);
                    return (
                      <button
                        key={row.key}
                        type="button"
                        role="option"
                        aria-selected={current}
                        onClick={() => apply(() => pickRow(row.choice))}
                        className="w-full flex items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-sm hover:bg-muted"
                      >
                        <span className="min-w-0 flex-1 truncate">{row.label}</span>
                        {row.recommended && <Star className="w-3 h-3 shrink-0 text-amber-500" aria-label="Recommended" />}
                        {row.vision && <Eye className="w-3 h-3 shrink-0 text-muted-foreground/70" aria-label="Sees images" />}
                        {row.hint && <span className="shrink-0 text-[11px] text-muted-foreground">{row.hint}</span>}
                        {current && <Check className="w-3.5 h-3.5 shrink-0 text-primary" />}
                      </button>
                    );
                  })}
                </div>
              ))}
              {groups.length === 0 && (
                <div className="px-2.5 py-3 text-sm text-muted-foreground">
                  {query ? "No model matches." : "Nothing to pick yet: add a key or an endpoint under Providers."}
                </div>
              )}
            </div>
          </div>,
          document.body,
        )}
    </div>
  );
}
