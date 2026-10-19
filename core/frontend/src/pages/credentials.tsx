import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import {
  KeyRound,
  Search,
  Trash2,
  Loader2,
  ExternalLink,
  AlertCircle,
  Link2,
  Info,
  X,
  Check,
  Plus,
  ChevronLeft,
  ChevronRight,
} from "lucide-react";
import {
  credentialsApi,
  type CredentialSpec,
  type CredentialAccount,
} from "@/api/credentials";
import SettingsModal from "@/components/SettingsModal";
import AddCredentialModal from "@/components/AddCredentialModal";
import SentinelConnectorsSection, {
  SENTINEL_CHANNEL_COUNT,
  sentinelConnectedCount,
} from "@/components/SentinelConnectorsSection";
import { sentinelApi, type SentinelCredentialStatus } from "@/api/sentinel";
import { SearchInput } from "@/components/SearchInput";
import { getProviderLogo } from "@/data/providerLogos";
import { ProviderLogo } from "@/components/ProviderLogo";
import {
  BYOK_CATALOG_SPECS,
  BYOK_CATALOG_IDS,
  BYOK_POPULARITY,
  BYOK_CREDENTIAL_FIELDS,
  type BYOKCredentialField,
} from "@/data/byokCatalog";
import {
  VISIBLE_CREDENTIAL_IDS,
  credentialIdToProvider,
} from "@/lib/visible-tools";
import { useQueensAuthorizationPrompt } from "@/context/QueensAuthorizationPromptContext";
import { useQueenDisconnectPrompt } from "@/context/QueenDisconnectPromptContext";

// Providers visible in the catalog but not yet connectable. Their tile
// renders with a "Coming soon" badge and the Authorize button is
// disabled — gives users a preview of what's on the roadmap without
// letting them kick off a half-broken OAuth flow. Empty today; add a
// credential_id here to bring back the gated preview treatment.
const COMING_SOON_CREDS = new Set<string>([]);

// Aden's API tags accounts with system-default aliases ("primary",
// "default") for the first/only account on a provider. Showing them
// next to the email reads as a "selected" status, which it isn't —
// it's just metadata. Hide these so only user-meaningful aliases
// (custom names the user picked) show up as a sub-label.
const SYSTEM_ALIASES = new Set(["primary", "default"]);

function meaningfulAlias(alias: string | undefined | null, email: string): string {
  if (!alias) return "";
  if (alias === email) return "";
  if (SYSTEM_ALIASES.has(alias.toLowerCase())) return "";
  return alias;
}

// Two-line marketing copy per provider. The runtime catalog ships a
// terse one-liner; this map fills the second line with what each
// integration actually does so every card occupies the same vertical
// footprint. Falls through to `spec.description` for unknown ids.
const RICH_DESCRIPTIONS: Record<string, string> = {
  // OAuth
  google:
    "Gmail, Calendar, Drive, Docs, and Sheets. One Google grant unlocks every Hive tool that hits a Google API.",
  github:
    "Repos, issues, pull requests, and actions. Fine-grained or classic personal access tokens both work.",
  hubspot:
    "Contacts, deals, marketing emails, and pipelines. Used by sales queens that update HubSpot directly.",
  notion_token:
    "Pages, databases, and blocks across any workspace you authorize. Hive reads context and writes updates as your queens work.",
  slack:
    "Send DMs, post to channels, and react. Per-channel scopes apply once you've granted the workspace.",
  aden_api_key:
    "Hive's platform key — signs every credential and runtime request. Mints automatically on login.",
  // LLM API keys
  anthropic:
    "Claude Opus, Sonnet, and Haiku. Bring your own key to bypass Hive's bundled allotment.",
  openai:
    "GPT-4o, GPT-4.1, o3, o4-mini, plus embeddings. Bring your own key to control billing directly.",
  gemini:
    "Gemini 2.5 Pro and Flash. Add a Google AI Studio key to route eligible turns straight to Google.",
  openrouter:
    "Single key, every model — Llama, DeepSeek, Mistral and more. Useful for benchmarking alternatives.",
  deepseek:
    "DeepSeek V3 and R1 reasoning models. Cheap throughput for bulk tool-using turns.",
  mistral:
    "Mistral Large, Codestral, and Magistral. Strong fit for European data-residency requirements.",
  groq:
    "LPU-backed inference for sub-second responses. Llama and Mixtral models at high throughput.",
  together:
    "Open-source model proxy — Llama, Qwen, DeepSeek, Mixtral and more behind one key.",
  cerebras:
    "Wafer-scale inference at extreme tokens-per-second. Llama 3.1 and 3.3 with very low latency.",
  kimi: "Moonshot Kimi K2 with 1M+ token context. Good for long-document and multi-file agents.",
  minimax:
    "abab and M1 models. Strong on Chinese, multimodal inputs, and long-context tasks.",
  hive: "Hive's routed model pool. Falls back here when no other provider key is configured.",
};

function richDescription(spec: { credential_id: string; description?: string | null }): string {
  const id = spec.credential_id;
  if (RICH_DESCRIPTIONS[id]) return RICH_DESCRIPTIONS[id];
  // Tolerate runtime suffix variants: "openai_api_key", "anthropic_key",
  // "notion_token". Strip the most common ones and try the bare provider
  // name before falling back to whatever description the spec ships.
  const base = id.replace(/_(api_key|api|key|token|oauth)$/i, "");
  if (base !== id && RICH_DESCRIPTIONS[base]) return RICH_DESCRIPTIONS[base];
  return spec.description || "";
}

// Emoji fallback for credentials without an SVG logo
const CRED_EMOJI_FALLBACK: Record<string, string> = {
  aden_api_key: "🔑",
  serper: "🔍",
  serpapi: "🔍",
  news: "📰",
  newsapi: "📰",
  apify: "🕷️",
  attio: "📇",
  greenhouse: "🌱",
  lusha: "👤",
  microsoft_graph: "Ⓜ️",
  pushover: "🔔",
  tines: "🔄",
  langfuse: "📡",
  redshift: "🔴",
  azure_sql: "🔷",
  apollo: "🚀",
};

function CredIcon({ credId, size = 20 }: { credId: string; size?: number }) {
  const logo = getProviderLogo(credId);
  if (logo) return <ProviderLogo provider={credId} size={size} />;
  const emoji =
    CRED_EMOJI_FALLBACK[credId] ??
    Object.entries(CRED_EMOJI_FALLBACK).find(([k]) => credId.startsWith(k))?.[1] ??
    "🔑";
  return <span style={{ fontSize: size * 0.85 }}>{emoji}</span>;
}

// Group credentials that share a credential_group
interface CredGroup {
  groupKey: string;
  label: string;
  specs: CredentialSpec[];
  allAvailable: boolean;
  anyAvailable: boolean;
}

function groupSpecs(specs: CredentialSpec[]): CredGroup[] {
  const groups = new Map<string, CredentialSpec[]>();
  const ungrouped: CredentialSpec[] = [];

  for (const spec of specs) {
    if (spec.credential_group) {
      const existing = groups.get(spec.credential_group) || [];
      existing.push(spec);
      groups.set(spec.credential_group, existing);
    } else {
      ungrouped.push(spec);
    }
  }

  const result: CredGroup[] = [];

  for (const [groupKey, members] of groups) {
    result.push({
      groupKey,
      label: members[0].credential_name,
      specs: members,
      allAvailable: members.every((s) => s.available),
      anyAvailable: members.some((s) => s.available),
    });
  }

  for (const spec of ungrouped) {
    result.push({
      groupKey: spec.credential_id,
      label: spec.credential_name,
      specs: [spec],
      allAvailable: spec.available,
      anyAvailable: spec.available,
    });
  }

  // Sort: connected first, then alphabetically
  result.sort((a, b) => {
    if (a.anyAvailable !== b.anyAvailable) return a.anyAvailable ? -1 : 1;
    return a.label.localeCompare(b.label);
  });

  return result;
}

// Discrete pagination for the API Keys grid. The BYOK catalog is ~700
// placeholder cards; mounting them all at once is heavy and overwhelming.
// We render one page at a time. Search still runs over the full catalog
// (see `filtered`) — pagination only chunks whatever the current result
// set is, so nothing becomes unfindable.
const API_KEYS_PAGE_SIZE = 24;

// Build the windowed list of page numbers: first and last are always
// shown, a one-page sibling window brackets the current page, and "…"
// fills the gaps. Pages are 1-indexed here for readability; callers
// convert to the 0-indexed page state.
function pageWindow(current: number, total: number): Array<number | "ellipsis"> {
  if (total <= 7) return Array.from({ length: total }, (_, i) => i + 1);
  const siblings = 1;
  const left = Math.max(2, current - siblings);
  const right = Math.min(total - 1, current + siblings);
  const items: Array<number | "ellipsis"> = [1];
  if (left > 2) items.push("ellipsis");
  for (let i = left; i <= right; i++) items.push(i);
  if (right < total - 1) items.push("ellipsis");
  items.push(total);
  return items;
}

function PaginationBar({
  page,
  pageCount,
  onChange,
}: {
  // 0-indexed, already clamped to [0, pageCount - 1].
  page: number;
  pageCount: number;
  onChange: (page: number) => void;
}) {
  if (pageCount <= 1) return null;
  const items = pageWindow(page + 1, pageCount);
  return (
    <nav className="flex items-center justify-center gap-1" aria-label="API Keys pages">
      <button
        type="button"
        onClick={() => {
          if (page > 0) onChange(page - 1);
        }}
        aria-disabled={page === 0}
        aria-label="Previous page"
        className={`flex items-center justify-center w-8 h-8 rounded-md transition-colors ${
          page === 0
            ? "text-muted-foreground/40 cursor-not-allowed"
            : "text-muted-foreground hover:text-foreground hover:bg-muted"
        }`}
      >
        <ChevronLeft className="w-4 h-4" />
      </button>
      {items.map((it, i) =>
        it === "ellipsis" ? (
          <span
            key={`ellipsis-${i}`}
            className="w-8 h-8 flex items-center justify-center text-xs text-muted-foreground/50 select-none"
            aria-hidden
          >
            …
          </span>
        ) : (
          <button
            key={it}
            type="button"
            onClick={() => onChange(it - 1)}
            aria-current={it - 1 === page ? "page" : undefined}
            aria-label={`Page ${it}`}
            className={`min-w-8 h-8 px-2 rounded-md text-xs font-medium transition-colors ${
              it - 1 === page
                ? "bg-primary text-primary-foreground"
                : "text-muted-foreground hover:text-foreground hover:bg-muted"
            }`}
          >
            {it}
          </button>
        ),
      )}
      <button
        type="button"
        onClick={() => {
          if (page < pageCount - 1) onChange(page + 1);
        }}
        aria-disabled={page === pageCount - 1}
        aria-label="Next page"
        className={`flex items-center justify-center w-8 h-8 rounded-md transition-colors ${
          page === pageCount - 1
            ? "text-muted-foreground/40 cursor-not-allowed"
            : "text-muted-foreground hover:text-foreground hover:bg-muted"
        }`}
      >
        <ChevronRight className="w-4 h-4" />
      </button>
    </nav>
  );
}

export default function CredentialsPage() {
  const { openPrompt: openQueensAuthorizationPrompt } =
    useQueensAuthorizationPrompt();
  const { openPrompt: openQueenDisconnectPrompt } = useQueenDisconnectPrompt();
  const [settingsOpen, setSettingsOpen] = useState(false);
  // Manual "Add credential" modal. `locked` fixes the provider (opened from a
  // card's "Add another account"); null `addModal` = closed; `{locked: null}`
  // = open with an editable provider field (any/custom provider).
  const [addModal, setAddModal] = useState<
    | {
        locked: {
          credentialId: string;
          name: string;
          defaultKeyName?: string;
          defaultFields?: BYOKCredentialField[];
        } | null;
      }
    | null
  >(null);
  const [specs, setSpecs] = useState<CredentialSpec[]>([]);
  // Global sentinel alert-channel status (Telegram bot / Slack app). Owned here
  // so the header count and the Sentinel cards share one source of truth.
  const [sentinelCreds, setSentinelCreds] = useState<SentinelCredentialStatus | null>(null);
  const [hasAdenKey, setHasAdenKey] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [inputValue, setInputValue] = useState("");
  const [saving, setSaving] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [popover, setPopover] = useState<{
    id: string;
    rect: DOMRect;
    spec: CredentialSpec;
  } | null>(null);
  const [authorizeModal, setAuthorizeModal] = useState<{
    spec: CredentialSpec;
    // Aliases that existed for this provider *before* the user clicked Authorize.
    // Used to detect which rows in `currentAccounts` are brand-new.
    snapshotAliases: string[];
    // Latest accounts list for this provider, refreshed on every resync.
    // Starts equal to the snapshot at open time.
    currentAccounts: CredentialAccount[];
    status: "waiting" | "checking" | "not_found" | "success";
    newAccount: CredentialAccount | null;
    // Orthogonal to `status`: true while a background (focus-triggered)
    // probe is in flight. Drives the inline "Checking…" indicator.
    probing: boolean;
    // Human-readable result of the last background probe, shown inline
    // for a short time. null = nothing to show.
    probeResult: string | null;
  } | null>(null);
  const pendingDetectedRef = useRef<{ toolProvider: string; account: CredentialAccount } | null>(null);
  const lastFocusFetch = useRef(0);
  // Mirror of authorizeModal so runResyncCheck can read its state
  // synchronously without going through a setState updater (which runs
  // asynchronously in React 18 and broke the previous "detectedFresh"
  // pattern — the post-setState side effect saw the pre-updater value).
  const authorizeModalRef = useRef<typeof authorizeModal>(null);
  useEffect(() => {
    authorizeModalRef.current = authorizeModal;
  }, [authorizeModal]);

  const fetchSpecs = useCallback(async () => {
    try {
      setError(null);
      const data = await credentialsApi.listSpecs();
      // Filter to the curated set we actually authorize through Aden.
      // The runtime keeps the full catalog so MCP tools that depend on
      // a less-common credential (e.g. apollo, attio) still work if a
      // user pastes one — but they don't get rendered as a Connect tile
      // here, since there's no OAuth UI for them.
      // Curated visibility for OAuth-able specs the backend ships today
      // (centralized in `lib/visible-tools`), augmented by the BYOK
      // placeholder catalog so the API Keys section is populated with every
      // enterprise SaaS we plan to support. Placeholders are deduped against
      // any real spec so the backend always wins.
      const visible = data.specs.filter((s) => VISIBLE_CREDENTIAL_IDS.has(s.credential_id));
      const backendIds = new Set(data.specs.map((s) => s.credential_id));
      // Surface manually-added local accounts on BYOK placeholder cards (which
      // have no backend spec): hydrate each placeholder with its accounts from
      // the provider→accounts map so a key added via the modal shows up.
      const abp = data.accounts_by_provider || {};
      const placeholders = BYOK_CATALOG_SPECS.filter((s) => !backendIds.has(s.credential_id)).map((s) => {
        const accts = abp[s.credential_id] || [];
        return accts.length > 0 ? { ...s, accounts: accts, available: true } : s;
      });
      // Custom providers the user typed in the Add-key modal: their local
      // accounts land in `accounts_by_provider` under an id that matches no
      // backend spec and isn't in the BYOK catalog, so without a synthetic
      // spec the card never renders and the key silently disappears from the
      // API Keys section. Group local accounts by their credential_id and mint
      // an available spec for each unrecognized one (available → sorts to the
      // top, alongside the other connected cards).
      const coveredIds = new Set<string>([
        ...visible.map((s) => s.credential_id),
        ...placeholders.map((s) => s.credential_id),
      ]);
      const customAccounts = new Map<string, CredentialAccount[]>();
      for (const [provider, accts] of Object.entries(abp)) {
        for (const a of accts) {
          if (a.source !== "local") continue;
          const id = a.credential_id || provider;
          if (!id || coveredIds.has(id)) continue;
          const list = customAccounts.get(id) ?? [];
          list.push(a);
          customAccounts.set(id, list);
        }
      }
      const customSpecs: CredentialSpec[] = [...customAccounts.entries()].map(
        ([id, accts]) => ({
          credential_name: id.replace(/[_-]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()),
          credential_id: id,
          env_var: "",
          description: "",
          help_url: "",
          api_key_instructions: "",
          tools: [],
          aden_supported: false,
          direct_api_key_supported: true,
          credential_key: "api_key",
          credential_group: "",
          available: true,
          accounts: accts,
        }),
      );
      setSpecs([...visible, ...placeholders, ...customSpecs]);
      setHasAdenKey(data.has_aden_key);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to load credentials"
      );
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchSentinelCreds = useCallback(async () => {
    try {
      setSentinelCreds(await sentinelApi.credentialStatus());
    } catch {
      /* non-fatal — sentinel cards just render as not-connected */
    }
  }, []);

  useEffect(() => {
    fetchSpecs();
    fetchSentinelCreds();
  }, [fetchSpecs, fetchSentinelCreds]);

  // Re-fetch on window focus (after OAuth return)
  useEffect(() => {
    const handleFocus = () => {
      const now = Date.now();
      if (now - lastFocusFetch.current < 3000) return;
      lastFocusFetch.current = now;
      fetchSpecs();
      fetchSentinelCreds();
    };
    window.addEventListener("focus", handleFocus);
    return () => window.removeEventListener("focus", handleFocus);
  }, [fetchSpecs, fetchSentinelCreds]);

  const handleSave = async (spec: CredentialSpec) => {
    if (!inputValue.trim()) return;
    setSaving(true);
    try {
      await credentialsApi.save(spec.credential_id, {
        [spec.credential_key]: inputValue.trim(),
      });
      setEditingId(null);
      setInputValue("");
      await fetchSpecs();
    } catch {
      setError(`Failed to save ${spec.credential_name}`);
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (spec: CredentialSpec) => {
    setSaving(true);
    try {
      await credentialsApi.delete(spec.credential_id);
      setDeletingId(null);
      await fetchSpecs();
    } catch {
      setError(`Failed to delete ${spec.credential_name}`);
    } finally {
      setSaving(false);
    }
  };

  // Remove a single manually-added local account (source='local'); distinct
  // from handleDelete which removes the un-aliased store credential.
  const handleDeleteLocalAccount = useCallback(
    async (credentialId: string, alias: string) => {
      try {
        await credentialsApi.deleteLocal(credentialId, alias);
        await fetchSpecs();
      } catch {
        setError(`Failed to remove ${credentialId}/${alias}`);
      }
    },
    [fetchSpecs],
  );

  // OAuth removal: open the queens-disconnect prompt first so the user
  // sees exactly which queens will lose tools. Apply rewrites those
  // queens' sidecars, then sends the user to Aden where the actual
  // account removal happens — OAuth credential lifecycle lives on
  // hive.open-hive.com, not on the local runtime (the local
  // ``DELETE /credentials/{id}`` only knows about API-key credentials
  // and returns 404 for OAuth providers). The
  // ``credential_provider_disconnected`` SSE that Aden eventually
  // fires is absorbed by the dedup window inside the prompt context.
  const handleOAuthDisconnect = useCallback(
    (spec: CredentialSpec) => {
      const toolProvider = credentialIdToProvider(spec.credential_id);
      if (!toolProvider) return;
      const primary = spec.accounts?.[0] ?? null;
      openQueenDisconnectPrompt(toolProvider, primary, async () => {
        // Refresh so we mirror whatever the runtime did on disconnect.
        await fetchSpecs();
      });
    },
    [openQueenDisconnectPrompt, fetchSpecs],
  );

  const handleConnect = (spec: CredentialSpec) => {
    // Aden-backed provider (Google / GitHub / HubSpot / Notion / Slack):
    // always route through the open-hive.com browser flow — open the
    // dashboard's Integrations tab and show the blocking modal that
    // polls for the new alias. The "direct API key" branch was removed
    // so every provider in this curated list behaves identically.
    if (spec.aden_supported) {
      const initial = spec.accounts ?? [];
      setAuthorizeModal({
        spec,
        snapshotAliases: initial.map((a) => a.alias),
        currentAccounts: initial,
        status: "waiting",
        newAccount: null,
        probing: false,
        probeResult: null,
      });
      return;
    }
    setEditingId(spec.credential_id);
    setInputValue("");
    setDeletingId(null);
  };

  // Called from the AuthorizeModal: force-resync and check whether a new
  // account for this provider has shown up since the modal opened.
  //
  // `silent=true` is used by the focus-based auto-probe: a miss stays in
  // "waiting" (the user may still be mid-flow on Aden) so we don't shout
  // "couldn't find a new account" every time they tab back. Only an
  // explicit button click (silent=false) can surface the "not_found" state.
  //
  // ``credentialsApi.resync()`` POSTs to the local Python runtime over HTTP;
  // the console.log calls below trace the request/response.
  const runResyncCheck = useCallback(
    async (silent: boolean = false) => {
      setAuthorizeModal((prev) => {
        if (!prev) return prev;
        if (silent) {
          return { ...prev, probing: true, probeResult: null };
        }
        return { ...prev, status: "checking" };
      });
      console.log(
        `[credentials] resync POST /api/credentials/resync (silent=${silent})`,
      );
      try {
        const resp = await credentialsApi.resync();
        console.log("[credentials] resync ←", resp);
        // Detect synchronously from the ref so the side effect doesn't
        // race the setState updater (React 18 batches updaters; reading
        // the post-update value from a closure variable doesn't work).
        const prev = authorizeModalRef.current;
        let detected: { toolProvider: string; account: CredentialAccount } | null = null;
        let nextModalState:
          | typeof authorizeModal
          | "keep" = "keep";
        if (prev) {
          // The backend keys ``accounts_by_provider`` by the tool-provider
          // name (``notion``), not the credential_id (``notion_token``).
          // Look up under both so we don't miss Notion's accounts.
          const credentialId = prev.spec.credential_id;
          const toolProvider = credentialIdToProvider(credentialId);
          const current: CredentialAccount[] =
            (toolProvider
              ? resp.accounts_by_provider[toolProvider]
              : undefined) ??
            resp.accounts_by_provider[credentialId] ??
            [];
          const before = new Set(prev.snapshotAliases);
          // Prefer a genuinely new alias. Both silent (focus) probe AND
          // explicit click fall back to the first existing account so
          // re-authorising the same email also pops the queens dialog
          // — the silent probe fires when the user tabs back from the
          // OAuth flow, so an account present at that moment is a
          // strong signal they finished authorising. Prompt-context
          // dedup keyed on ``${provider}:${alias}`` (30s window)
          // absorbs repeat openings.
          const fresh =
            current.find((a) => !before.has(a.alias)) ??
            current[0] ??
            null;
          if (fresh && toolProvider) {
            detected = { toolProvider, account: fresh };
            nextModalState = {
              ...prev,
              currentAccounts: current,
              status: "success",
              newAccount: fresh,
              probing: false,
              probeResult: null,
            };
          } else if (silent) {
            nextModalState = {
              ...prev,
              currentAccounts: current,
              probing: false,
              probeResult: "No new account yet",
            };
          } else {
            nextModalState = {
              ...prev,
              currentAccounts: current,
              status: "not_found",
              newAccount: null,
              probing: false,
              probeResult: null,
            };
          }
        }
        if (nextModalState !== "keep") {
          setAuthorizeModal(nextModalState);
        }
        if (detected) {
          pendingDetectedRef.current = detected;
        }
        // Refresh the page data so any new accounts render behind the modal.
        await fetchSpecs();
      } catch (err) {
        console.error("[credentials] resync failed:", err);
        // Pull the runtime's error message off the ApiError so the user
        // sees the actual cause instead of a generic "not_found". The
        // most common case is the runtime returning 400 with
        // "Aden API key not configured" — that means the desktop never
        // pushed an API key to the runtime, usually because the user
        // signed in before the auto-bootstrap code shipped.
        const errBody =
          err && typeof err === "object" && "body" in err
            ? (err as { body?: { error?: string } }).body
            : null;
        const message =
          errBody?.error ||
          (err instanceof Error ? err.message : "Resync failed");
        setAuthorizeModal((prev) => {
          if (!prev) return prev;
          if (silent) {
            return {
              ...prev,
              probing: false,
              probeResult: message,
            };
          }
          return {
            ...prev,
            status: "not_found",
            probing: false,
            probeResult: message,
          };
        });
      }
    },
    [fetchSpecs, openQueensAuthorizationPrompt]
  );

  // Clear the short-lived probe result after a couple seconds so the inline
  // "No new account yet" message doesn't linger forever.
  useEffect(() => {
    if (!authorizeModal?.probeResult) return;
    const t = setTimeout(() => {
      setAuthorizeModal((prev) =>
        prev && prev.probeResult ? { ...prev, probeResult: null } : prev
      );
    }, 2500);
    return () => clearTimeout(t);
  }, [authorizeModal?.probeResult]);

  // When the modal is open and the user tabs back into Hive, opportunistically
  // resync in silent mode — if the new account is there we auto-close; if not,
  // we stay in "waiting" so the user isn't scolded for alt-tabbing mid-flow.
  useEffect(() => {
    if (!authorizeModal || authorizeModal.status === "checking") return;
    const onFocus = () => {
      runResyncCheck(true);
    };
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [authorizeModal, runResyncCheck]);

  // Filtered specs
  const filtered = useMemo(() => {
    if (!searchQuery.trim()) return specs;
    const q = searchQuery.toLowerCase();
    return specs.filter(
      (s) =>
        s.credential_name.toLowerCase().includes(q) ||
        s.description.toLowerCase().includes(q) ||
        s.env_var.toLowerCase().includes(q) ||
        s.tools.some((t) => t.toLowerCase().includes(q))
    );
  }, [specs, searchQuery]);

  // Split into API Keys vs OAuth. Credentials that support direct popup
  const apiKeySpecs = useMemo(
    () => filtered.filter((s) => !s.aden_supported),
    [filtered]
  );
  const oauthSpecs = useMemo(
    () =>
      filtered.filter(
        (s) => s.aden_supported && s.credential_id !== "aden_api_key"
      ),
    [filtered]
  );

  // Aden platform key (special — shown at top of OAuth if present)
  const adenSpec = useMemo(
    () => filtered.find((s) => s.credential_id === "aden_api_key"),
    [filtered]
  );

  const apiKeyGroups = useMemo(() => groupSpecs(apiKeySpecs), [apiKeySpecs]);
  const oauthGroups = useMemo(() => groupSpecs(oauthSpecs), [oauthSpecs]);

  // Ordering for the API Keys grid: "By Popularity" (GTM relevancy baked into
  // the BYOK catalog) is the default; "name" keeps groupSpecs' connected-first
  // alphabetical order untouched.
  const [apiKeySort, setApiKeySort] = useState<"popularity" | "name">(
    "popularity",
  );
  const sortedApiKeyGroups = useMemo(() => {
    if (apiKeySort === "name") return apiKeyGroups;
    const popularity = (g: CredGroup) =>
      Math.max(...g.specs.map((s) => BYOK_POPULARITY[s.credential_id] ?? 0));
    return [...apiKeyGroups].sort((a, b) => {
      if (a.anyAvailable !== b.anyAvailable) return a.anyAvailable ? -1 : 1;
      return popularity(b) - popularity(a) || a.label.localeCompare(b.label);
    });
  }, [apiKeyGroups, apiKeySort]);

  // Header counts include the Sentinel alert channels (Telegram, Slack), which
  // live outside `specs` but are shown on this page as Built-in Connections.
  const activeCount =
    specs.filter((s) => s.available).length + sentinelConnectedCount(sentinelCreds);
  const totalCount = specs.length + SENTINEL_CHANNEL_COUNT;

  const apiKeyConnected = apiKeySpecs.filter((s) => s.available).length;

  // Discrete pagination over the API Keys grid (the large list). `filtered`
  // already narrowed the full catalog by the search query, so this only
  // chunks the resulting groups into pages.
  const [apiKeyPage, setApiKeyPage] = useState(0);
  // Reset to the first page whenever the search query changes. Done during
  // render via a previous-value compare rather than an effect: a passive
  // effect flushes after commit, so it would paint one frame of a stale page
  // against the new, smaller result set before snapping back to page 1. React
  // discards this in-render re-render before paint, so there's no flicker.
  const [apiKeyPageQuery, setApiKeyPageQuery] = useState(searchQuery);
  if (apiKeyPageQuery !== searchQuery) {
    setApiKeyPageQuery(searchQuery);
    setApiKeyPage(0);
  }
  const apiKeyPageCount = Math.max(
    1,
    Math.ceil(sortedApiKeyGroups.length / API_KEYS_PAGE_SIZE),
  );
  // Clamp for display: if the list shrank below the stored page (search or
  // deletion), fall back to the last valid page without an extra setState.
  const apiKeyPageClamped = Math.min(apiKeyPage, apiKeyPageCount - 1);
  const apiKeyStart = apiKeyPageClamped * API_KEYS_PAGE_SIZE;
  const pagedApiKeyGroups = useMemo(
    () =>
      sortedApiKeyGroups.slice(apiKeyStart, apiKeyStart + API_KEYS_PAGE_SIZE),
    [sortedApiKeyGroups, apiKeyStart],
  );
  const apiKeySectionRef = useRef<HTMLDivElement | null>(null);
  const goToApiKeyPage = useCallback(
    (next: number) => {
      setApiKeyPage(Math.max(0, Math.min(next, apiKeyPageCount - 1)));
      // Scroll the section back to its top so the new page starts in view.
      apiKeySectionRef.current?.scrollIntoView({
        block: "start",
        behavior: "smooth",
      });
    },
    [apiKeyPageCount],
  );

  // Nudge toward search once the user reaches the pagination controls. Paging
  // through ~30 pages is tedious, and the header search (pinned above the
  // scroll area, always visible) queries the full catalog. When the pagination
  // bar scrolls into view we give that search input a subdued ring so the eye
  // is drawn back up to it. Re-arms whenever the bar mounts/unmounts (page
  // count crosses 1).
  const paginationRef = useRef<HTMLDivElement | null>(null);
  const [searchNudge, setSearchNudge] = useState(false);
  useEffect(() => {
    const el = paginationRef.current;
    if (!el) {
      setSearchNudge(false);
      return;
    }
    const io = new IntersectionObserver(
      ([entry]) => setSearchNudge(entry.isIntersecting),
      { threshold: 0 },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [apiKeyPageCount]);

  const renderCard = (group: CredGroup) => {
    const primary = group.specs[0];
    const isConnected = group.allAvailable;
    const isEditing = group.specs.some((s) => editingId === s.credential_id);
    const isDeleting = group.specs.some((s) => deletingId === s.credential_id);
    const hasInstructions = primary.api_key_instructions || primary.help_url;
    // Any Aden-backed provider renders the OAuth-style layout: a chip
    // under the description + an "Add another account" affordance.
    // Accounts are sourced from Aden, so lifecycle (add/remove) happens
    // on hive.adenhq.com; Hive just mirrors what it sees. For providers
    // that *also* accept a pasted key (e.g. GitHub), the chip falls back
    // to "••••••••" until an OAuth account is connected.
    const isPureOAuth =
      primary.aden_supported &&
      primary.credential_id !== "aden_api_key";
    // BYOK catalog providers are no longer "coming soon": they now accept a
    // manually-added local key via the Add-credential modal. Only OAuth
    // providers gated in COMING_SOON_CREDS (e.g. slack) stay disabled.
    const isByok = BYOK_CATALOG_IDS.has(primary.credential_id);
    const isComingSoon = COMING_SOON_CREDS.has(primary.credential_id);
    const accounts = primary.accounts ?? [];
    // Manually-added / agent-collected accounts (LocalCredentialRegistry).
    // Rendered as removable alias rows under non-OAuth cards.
    const localAccounts = accounts.filter((a) => a.source === "local");

    const statusTone = isComingSoon
      ? "muted"
      : isConnected
        ? "connected"
        : primary.aden_supported
          ? "oauth"
          : "api";
    const statusLabel = isComingSoon
      ? "Soon"
      : isConnected
        ? "Connected"
        : primary.aden_supported
          ? "OAuth"
          : "API key";

    const primaryAccount = accounts[0];
    const primaryEmail = primaryAccount?.identity?.email || "";
    const primaryLabel =
      primaryEmail || primaryAccount?.alias || "connected";
    const extraAccounts = Math.max(0, accounts.length - 1);

    return (
      <div
        key={group.groupKey}
        data-tour="tour-credentials-card"
        className="rounded-lg border border-border/50 bg-card p-3 flex flex-col h-full min-h-[124px] transition-colors hover:border-border/80"
      >
        {/* Row 1 — logo + name + status */}
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2 min-w-0">
            <div className="w-10 h-10 rounded-md bg-muted/30 flex items-center justify-center flex-shrink-0">
              <CredIcon credId={primary.credential_id} size={26} />
            </div>
            <h3 className="text-[13px] font-semibold text-foreground leading-tight truncate">
              {primary.credential_name}
            </h3>
          </div>
          <span className="inline-flex items-center gap-1 text-[10px] font-medium tracking-wide flex-shrink-0">
            {statusTone === "connected" && (
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" aria-hidden />
            )}
            {statusTone === "oauth" && (
              <span className="w-1.5 h-1.5 rounded-full border border-muted-foreground/40" aria-hidden />
            )}
            {statusTone === "api" && (
              <span className="w-1.5 h-1.5 rounded-full border border-muted-foreground/40" aria-hidden />
            )}
            <span
              className={
                statusTone === "connected"
                  ? "text-emerald-600/90"
                  : statusTone === "oauth"
                    ? "text-primary/85"
                    : "text-muted-foreground/70"
              }
            >
              {statusLabel}
            </span>
          </span>
        </div>

        {/* Row 2 — description, full width below. BYOK stubs ship an empty
            description so placeholder cards stay clean; only curated blurbs
            (RICH_DESCRIPTIONS or real backend specs) render here. */}
        {richDescription(primary) && (
          <p className="text-[10.5px] text-muted-foreground/80 mt-1.5 line-clamp-2 leading-snug">
            {richDescription(primary)}
          </p>
        )}

        {/* Row 3 — connected account chip (collapsed, +N for extras).
            For Aden-backed providers that *also* accept a pasted key
            (e.g. GitHub), fall back to "••••••••" until an OAuth
            account is on file. */}
        {isConnected && isPureOAuth && (
          <div className="flex flex-col gap-1 mt-2">
            {accounts.map((acct) => {
              const email = acct.identity?.email || "";
              const label = email || acct.alias || "connected";
              return (
                <div
                  key={`${acct.credential_id}:${acct.alias}`}
                  className="flex items-center gap-1.5 text-xs text-muted-foreground min-w-0"
                >
                  <KeyRound className="w-3 h-3 flex-shrink-0" />
                  <span className="truncate text-foreground">{label}</span>
                </div>
              );
            })}
          </div>
        )}

        {/* Spacer — pushes the action row to the bottom */}
        <div className="flex-1" />

        {/* Divider between card body and the action row — single
            consistent line on every card. */}
        <div className="border-t border-border/40 mt-2.5" aria-hidden />

        {/* Action row — always pinned to card bottom */}
        <div className="pt-2.5">
          {isDeleting ? (
            <div className="flex items-center gap-2 px-3 py-2 rounded-lg border border-destructive/30 bg-destructive/5">
              <AlertCircle className="w-3.5 h-3.5 text-destructive flex-shrink-0" />
              <span className="text-xs text-destructive flex-1">
                Remove this credential?
              </span>
              <button
                onClick={() => handleDelete(primary)}
                disabled={saving}
                className="px-3 py-1 rounded-md text-xs font-medium bg-destructive text-destructive-foreground hover:bg-destructive/90 disabled:opacity-50 transition-colors"
              >
                {saving ? <Loader2 className="w-3 h-3 animate-spin" /> : "Remove"}
              </button>
              <button
                onClick={() => setDeletingId(null)}
                className="px-2 py-1 rounded-md text-xs text-muted-foreground hover:bg-muted transition-colors"
              >
                Cancel
              </button>
            </div>
          ) : isEditing ? (
            group.specs.map((spec) =>
              editingId === spec.credential_id ? (
                <div key={spec.credential_id} className="flex flex-col gap-2">
                  {group.specs.length > 1 && (
                    <span className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">
                      {spec.credential_name}
                    </span>
                  )}
                  <div className="flex gap-2">
                    <input
                      type="password"
                      value={inputValue}
                      onChange={(e) => setInputValue(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") handleSave(spec);
                        if (e.key === "Escape") {
                          setEditingId(null);
                          setInputValue("");
                        }
                      }}
                      placeholder={`Paste ${spec.credential_name} key...`}
                      autoFocus
                      className="flex-1 px-3 py-1.5 rounded-md border border-border bg-background text-xs text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary/40"
                    />
                    <button
                      onClick={() => handleSave(spec)}
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
                </div>
              ) : null
            )
          ) : isConnected && isPureOAuth ? (
            <div className="flex items-center justify-between">
              <button
                onClick={() => handleConnect(primary)}
                disabled={isComingSoon}
                title={isComingSoon ? "Coming soon" : undefined}
                className="flex items-center gap-1.5 text-xs font-medium text-primary hover:text-primary/80 transition-colors disabled:text-muted-foreground disabled:cursor-not-allowed disabled:hover:text-muted-foreground"
              >
                <Plus className="w-3 h-3" />
                Add another account
              </button>
              <button
                onClick={() => handleOAuthDisconnect(primary)}
                disabled={isComingSoon}
                title={
                  isComingSoon
                    ? "Coming soon"
                    : `Remove ${primary.credential_name} access`
                }
                className="flex items-center gap-1 text-[11px] text-muted-foreground hover:text-destructive transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
              >
                <Trash2 className="w-3 h-3" />
                Remove
              </button>
            </div>
          ) : isConnected && localAccounts.length > 0 ? (
            // Manually-added / agent-collected local accounts: list each alias
            // with its own remove, plus an "Add another account" affordance.
            <div className="flex flex-col gap-1.5">
              {localAccounts.map((acct) => {
                const email = acct.identity?.email || "";
                const label = email || acct.alias || "connected";
                const sub = email ? meaningfulAlias(acct.alias, email) : "";
                return (
                  <div
                    key={`${acct.credential_id}:${acct.alias}`}
                    className="flex items-center justify-between gap-2 min-w-0"
                  >
                    <div className="flex items-center gap-1.5 text-xs text-foreground min-w-0">
                      <KeyRound className="w-3 h-3 flex-shrink-0 text-muted-foreground" />
                      <span className="truncate">{label}</span>
                      {sub && (
                        <span className="truncate text-muted-foreground/60">· {sub}</span>
                      )}
                    </div>
                    <button
                      onClick={() =>
                        handleDeleteLocalAccount(
                          acct.credential_id || primary.credential_id,
                          acct.alias,
                        )
                      }
                      className="flex items-center gap-1 text-[11px] text-muted-foreground hover:text-destructive transition-colors flex-shrink-0"
                    >
                      <Trash2 className="w-3 h-3" />
                      Remove
                    </button>
                  </div>
                );
              })}
              <button
                onClick={() =>
                  setAddModal({
                    locked: {
                      credentialId: primary.credential_id,
                      name: primary.credential_name,
                      defaultKeyName: primary.credential_key,
                      defaultFields: BYOK_CREDENTIAL_FIELDS[primary.credential_id],
                    },
                  })
                }
                className="flex items-center gap-1 text-xs font-medium text-primary hover:text-primary/80 transition-colors"
              >
                <Plus className="w-3 h-3" />
                Add another account
              </button>
            </div>
          ) : isConnected ? (
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                <KeyRound className="w-3 h-3" />
                <span>••••••••</span>
              </div>
              <div className="flex items-center gap-1">
                <button
                  onClick={() => { setEditingId(primary.credential_id); setInputValue(""); setDeletingId(null); }}
                  className="text-[11px] text-muted-foreground hover:text-foreground transition-colors"
                >
                  Update
                </button>
                <button
                  onClick={() => {
                    setDeletingId(primary.credential_id);
                    setEditingId(null);
                    setInputValue("");
                  }}
                  className="flex items-center gap-1 text-[11px] text-muted-foreground hover:text-destructive transition-colors"
                >
                  <Trash2 className="w-3 h-3" />
                  Remove
                </button>
              </div>
            </div>
          ) : (
            <div className="flex items-center justify-between">
              <button
                onClick={() =>
                  isByok
                    ? setAddModal({
                        locked: {
                          credentialId: primary.credential_id,
                          name: primary.credential_name,
                          defaultKeyName: primary.credential_key,
                          defaultFields: BYOK_CREDENTIAL_FIELDS[primary.credential_id],
                        },
                      })
                    : handleConnect(primary)
                }
                disabled={
                  isComingSoon ||
                  (primary.aden_supported &&
                    !primary.direct_api_key_supported &&
                    !hasAdenKey &&
                    primary.credential_id !== "aden_api_key")
                }
                title={isComingSoon ? "Coming soon" : undefined}
                className="flex items-center gap-1.5 text-xs font-medium text-primary hover:text-primary/80 transition-colors disabled:text-muted-foreground disabled:cursor-not-allowed"
              >
                {primary.aden_supported ? (
                  <>
                    <ExternalLink className="w-3 h-3" />
                    Authorize
                  </>
                ) : (
                  <>
                    <span className="text-sm">+</span> Add account
                    <span className="text-muted-foreground/50">›</span>
                  </>
                )}
              </button>
              {hasInstructions && (
                <div className="flex items-center gap-2">
                  <span className="w-px h-3.5 bg-border/60" aria-hidden />
                  <button
                    onClick={(e) => {
                      const rect = e.currentTarget.getBoundingClientRect();
                      setPopover(
                        popover?.id === group.groupKey
                          ? null
                          : { id: group.groupKey, rect, spec: primary }
                      );
                    }}
                    className="flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground transition-colors"
                  >
                    <Info className="w-3 h-3" />
                    How to get key
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    );
  };

  return (
    <>
      {/* Content */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Page header */}
        <div className="px-6 py-4 border-b border-border/60">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <h2 className="text-lg font-semibold text-foreground flex items-center gap-2">
                <KeyRound className="w-5 h-5 text-primary" />
                Credentials
              </h2>
              {!loading && (
                <span className="text-xs text-muted-foreground">
                  {activeCount} active &middot; {totalCount} available
                </span>
              )}
            </div>
            <SearchInput
              className={`w-64 rounded-lg ring-primary/30 transition-shadow duration-500 ${
                searchNudge ? "ring-2" : "ring-0"
              }`}
              value={searchQuery}
              onChange={setSearchQuery}
              placeholder="Search credentials…"
            />
          </div>
        </div>

        <div className="flex-1 overflow-y-auto">
        <div className="max-w-6xl mx-auto px-6 py-6">

          {/* Error */}
          {error && (
            <div className="mb-6 px-4 py-3 rounded-lg border border-destructive/20 bg-destructive/5 text-sm text-destructive flex items-center gap-2">
              <AlertCircle className="w-4 h-4 flex-shrink-0" />
              {error}
            </div>
          )}

          {/* Loading */}
          {loading && (
            <div className="flex items-center justify-center py-20">
              <Loader2 className="w-6 h-6 animate-spin text-muted-foreground" />
            </div>
          )}

          {!loading && (
            <>
              {/* Built-in Connections — OAuth integrations + Sentinel alert
                  channels in one grid. Each card carries its own type chip
                  (OAuth / Alerts / Connected) so the kinds stay distinguishable. */}
              <div className="mb-8">
                <div className="flex items-center gap-2 mb-1.5">
                  <Link2 className="w-4 h-4 text-muted-foreground" />
                  <h3 className="text-sm font-semibold text-foreground">
                    Built-in Connections
                  </h3>
                </div>
                <p className="text-[11.5px] text-muted-foreground/80 mb-4 leading-snug">
                  Integrations and alert channels. Turn alerts on in a colony's{" "}
                  <span className="text-foreground">Automations</span> tab.
                </p>
                {searchQuery.trim() && oauthGroups.length === 0 && !adenSpec ? (
                  <p className="text-sm text-muted-foreground py-4">
                    No connectors match your search
                  </p>
                ) : (
                  <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                    {/* Aden Platform key card first — same grid as the
                        rest so every connector card sizes consistently. */}
                    {adenSpec &&
                      renderCard({
                        groupKey: "aden_api_key",
                        label: "Aden Platform",
                        specs: [adenSpec],
                        allAvailable: adenSpec.available,
                        anyAvailable: adenSpec.available,
                      })}
                    {oauthGroups.map(renderCard)}
                    {/* Sentinel alert channels — only when not searching, since
                        they aren't part of the credential-spec filter. */}
                    {!searchQuery.trim() && (
                      <SentinelConnectorsSection
                        creds={sentinelCreds}
                        onReload={fetchSentinelCreds}
                      />
                    )}
                  </div>
                )}
              </div>

              {/* API Keys section */}
              <div ref={apiKeySectionRef} className="scroll-mt-6">
                <div className="flex items-center gap-2 mb-4">
                  <KeyRound className="w-4 h-4 text-muted-foreground" />
                  <h3 className="text-sm font-semibold text-foreground">
                    API Keys
                  </h3>
                  <span className="text-xs text-muted-foreground bg-muted/50 px-2 py-0.5 rounded-full">
                    {apiKeyConnected}/{apiKeySpecs.length}
                  </span>
                  <select
                    value={apiKeySort}
                    onChange={(e) => {
                      setApiKeySort(e.target.value as "popularity" | "name");
                      setApiKeyPage(0);
                    }}
                    aria-label="Sort API keys"
                    className="ml-auto h-7 bg-muted/30 border border-border/50 rounded-md px-2 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-primary/40"
                  >
                    <option value="popularity">Most used</option>
                    <option value="name">Name (A–Z)</option>
                  </select>
                  <button
                    onClick={() => setAddModal({ locked: null })}
                    className="flex items-center justify-center gap-1.5 h-7 px-3 rounded-md text-xs font-medium bg-primary text-primary-foreground hover:bg-primary/90 transition-colors"
                  >
                    <Plus className="w-3.5 h-3.5" />
                    Add key
                  </button>
                </div>
                {sortedApiKeyGroups.length === 0 ? (
                  <p className="text-sm text-muted-foreground py-4">
                    {searchQuery
                      ? "No API keys match your search"
                      : "No API key credentials available"}
                  </p>
                ) : (
                  <>
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                      {pagedApiKeyGroups.map(renderCard)}
                    </div>
                    {apiKeyPageCount > 1 && (
                      <div
                        ref={paginationRef}
                        className="mt-6 flex flex-col items-center gap-2"
                      >
                        <PaginationBar
                          page={apiKeyPageClamped}
                          pageCount={apiKeyPageCount}
                          onChange={goToApiKeyPage}
                        />
                        <p className="text-[11px] text-muted-foreground/70">
                          Showing {apiKeyStart + 1}–
                          {Math.min(
                            apiKeyStart + API_KEYS_PAGE_SIZE,
                            sortedApiKeyGroups.length,
                          )}{" "}
                          of {sortedApiKeyGroups.length}
                        </p>
                      </div>
                    )}
                  </>
                )}
              </div>
            </>
          )}
        </div>
      </div>
      </div>

      {/* Instructions popover — fixed position, floats over everything */}
      {popover && (
        <>
          <div
            className="fixed inset-0 z-40"
            onClick={() => setPopover(null)}
          />
          <div
            className="fixed z-50 w-80 bg-card border border-border/60 rounded-xl shadow-xl overflow-hidden animate-in fade-in zoom-in-95 duration-150"
            style={{
              top: Math.min(popover.rect.bottom + 8, window.innerHeight - 300),
              left: Math.min(popover.rect.left, window.innerWidth - 340),
            }}
          >
            <div className="flex items-center justify-between px-4 py-3 border-b border-border/40">
              <div className="flex items-center gap-2">
                <span className="inline-flex items-center">
                  <CredIcon credId={popover.spec.credential_id} size={18} />
                </span>
                <span className="text-sm font-semibold text-foreground">
                  {popover.spec.credential_name}
                </span>
              </div>
              <button
                onClick={() => setPopover(null)}
                className="p-1 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            </div>
            <div className="px-4 py-3 space-y-3 max-h-64 overflow-y-auto">
              {popover.spec.api_key_instructions && (
                <pre className="whitespace-pre-wrap font-sans text-[12px] leading-relaxed text-muted-foreground">
                  {popover.spec.api_key_instructions}
                </pre>
              )}
              {popover.spec.help_url && (
                <a
                  href={popover.spec.help_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1.5 text-xs font-medium text-primary hover:text-primary/80 transition-colors"
                >
                  <ExternalLink className="w-3 h-3" />
                  Open docs
                </a>
              )}
            </div>
          </div>
        </>
      )}

      {/* Authorize modal — blocks while the user finishes OAuth on Aden. */}
      {authorizeModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
          <div className="w-[420px] max-w-[92vw] rounded-2xl border border-border/60 bg-card shadow-xl overflow-hidden">
            <div className="flex items-start justify-between px-5 pt-5 pb-3">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-lg bg-muted/40 flex items-center justify-center">
                  <CredIcon credId={authorizeModal.spec.credential_id} size={22} />
                </div>
                <div>
                  <h3 className="text-sm font-semibold text-foreground">
                    Connect {authorizeModal.spec.credential_name}
                  </h3>
                  <p className="text-[11px] text-muted-foreground mt-0.5">
                    Authorization happens on the Aden platform
                  </p>
                </div>
              </div>
              {authorizeModal.status !== "checking" && (
                <button
                  onClick={() => setAuthorizeModal(null)}
                  className="p-1 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
                >
                  <X className="w-4 h-4" />
                </button>
              )}
            </div>

            <div className="px-5 pb-5">
              {/* Detected accounts list — always shown so the user can see
                  exactly what Hive currently sees on Aden's side. New rows
                  (not in the open-time snapshot) are badged. */}
              {(() => {
                const before = new Set(authorizeModal.snapshotAliases);
                const rows = authorizeModal.currentAccounts;
                return (
                  <div className="mb-4">
                    <div className="flex items-center justify-between mb-2">
                      <div className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                        Detected {authorizeModal.spec.credential_name} accounts
                      </div>
                      {authorizeModal.probing ? (
                        <div className="flex items-center gap-1.5 text-[10px] text-muted-foreground">
                          <Loader2 className="w-3 h-3 animate-spin" />
                          Checking…
                        </div>
                      ) : authorizeModal.probeResult ? (
                        <div className="text-[10px] text-muted-foreground">
                          {authorizeModal.probeResult}
                        </div>
                      ) : null}
                    </div>
                    {rows.length === 0 ? (
                      <div className="text-xs text-muted-foreground italic px-3 py-2.5 rounded-lg border border-border/40 bg-muted/20">
                        None yet
                      </div>
                    ) : (
                      <ul className="flex flex-col gap-1.5">
                        {rows.map((acct) => {
                          const isNew = !before.has(acct.alias);
                          const email = acct.identity?.email || "";
                          const label = email || acct.alias || "connected";
                          const sub = email ? meaningfulAlias(acct.alias, email) : "";
                          return (
                            <li
                              key={`${acct.provider}:${acct.alias}:${acct.credential_id}`}
                              className={`flex items-center justify-between gap-2 px-3 py-2 rounded-lg border text-xs ${
                                isNew
                                  ? "border-emerald-500/40 bg-emerald-500/5"
                                  : "border-border/40 bg-muted/20"
                              }`}
                            >
                              <div className="flex items-center gap-2 min-w-0">
                                <KeyRound
                                  className={`w-3 h-3 flex-shrink-0 ${
                                    isNew
                                      ? "text-emerald-600"
                                      : "text-muted-foreground"
                                  }`}
                                />
                                <span className="truncate text-foreground">
                                  {label}
                                </span>
                                {sub && (
                                  <span className="truncate text-muted-foreground/60">
                                    · {sub}
                                  </span>
                                )}
                              </div>
                              {isNew && (
                                <span className="text-[10px] font-semibold uppercase tracking-wider text-emerald-600 flex-shrink-0">
                                  New
                                </span>
                              )}
                            </li>
                          );
                        })}
                      </ul>
                    )}
                  </div>
                );
              })()}

              {authorizeModal.status === "waiting" && (
                <>
                  <p className="text-xs text-muted-foreground mb-4">
                    Finish signing in to{" "}
                    {authorizeModal.spec.credential_name} in the Aden tab that
                    just opened, then click <em>I&apos;ve authorized</em> to
                    sync.
                  </p>
                  <div className="flex items-center gap-2 justify-end">
                    <button
                      onClick={() => setAuthorizeModal(null)}
                      className="px-3 py-1.5 rounded-md text-xs text-muted-foreground hover:bg-muted transition-colors"
                    >
                      Cancel
                    </button>
                    <button
                      onClick={() => runResyncCheck(false)}
                      className="px-3 py-1.5 rounded-md text-xs font-medium bg-primary text-primary-foreground hover:bg-primary/90 transition-colors"
                    >
                      I&apos;ve authorized
                    </button>
                  </div>
                </>
              )}

              {authorizeModal.status === "checking" && (
                <div className="flex items-center gap-3 py-4 text-xs text-muted-foreground">
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Syncing from Aden…
                </div>
              )}

              {authorizeModal.status === "not_found" && (
                <>
                  {authorizeModal.probeResult ? (
                    <div className="mb-4 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-destructive">
                      {authorizeModal.probeResult}
                    </div>
                  ) : null}
                  <p className="text-xs text-muted-foreground mb-4">
                    No new account detected yet. Please finish the
                    authentication step in the other tab, then retry.
                  </p>
                  <div className="flex items-center gap-2 justify-end">
                    <button
                      onClick={() => setAuthorizeModal(null)}
                      className="px-3 py-1.5 rounded-md text-xs text-muted-foreground hover:bg-muted transition-colors"
                    >
                      Cancel
                    </button>
                    <button
                      onClick={() => runResyncCheck(false)}
                      className="px-3 py-1.5 rounded-md text-xs font-medium bg-primary text-primary-foreground hover:bg-primary/90 transition-colors"
                    >
                      Retry
                    </button>
                  </div>
                </>
              )}

              {authorizeModal.status === "success" && authorizeModal.newAccount && (
                <>
                  <div className="flex items-center gap-2 mb-4 text-xs">
                    <div className="w-5 h-5 rounded-full bg-emerald-500/20 flex items-center justify-center flex-shrink-0">
                      <Check className="w-3 h-3 text-emerald-600" />
                    </div>
                    <span className="text-foreground">
                      Connected as{" "}
                      <strong>
                        {authorizeModal.newAccount.identity?.email ||
                          authorizeModal.newAccount.alias}
                      </strong>
                    </span>
                  </div>
                  <div className="flex items-center justify-end">
                    <button
                      onClick={() => {
                        const detected = pendingDetectedRef.current;
                        pendingDetectedRef.current = null;
                        setAuthorizeModal(null);
                        if (detected) {
                          openQueensAuthorizationPrompt(detected.toolProvider, detected.account);
                        }
                      }}
                      className="flex items-center gap-1.5 px-4 py-1.5 rounded-md text-xs font-semibold bg-emerald-600 text-white hover:bg-emerald-600/90 transition-colors"
                    >
                      <Check className="w-3 h-3" />
                      Finish
                    </button>
                  </div>
                </>
              )}
            </div>
          </div>
        </div>
      )}

      {addModal && (
        <AddCredentialModal
          open
          lockedProvider={addModal.locked}
          onSaved={fetchSpecs}
          onClose={() => setAddModal(null)}
        />
      )}

      <SettingsModal
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
      />
    </>
  );
}
