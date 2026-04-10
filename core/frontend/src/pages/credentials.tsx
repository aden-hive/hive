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
} from "lucide-react";
import {
  credentialsApi,
  type CredentialSpec,
  type CredentialAccount,
} from "@/api/credentials";
import SettingsModal from "@/components/SettingsModal";

// Icon map for known credentials (credential_id → emoji/symbol)
const CRED_ICONS: Record<string, string> = {
  aden_api_key: "🔑",
  pinecone: "🌲",
  brave_search: "🦁",
  serper: "🔍",
  google_search: "🔍",
  serpapi: "🔍",
  sendgrid: "📧",
  resend: "📧",
  brevo: "📧",
  twilio: "📱",
  stripe: "💳",
  razorpay: "💳",
  aws_s3: "☁️",
  supabase: "⚡",
  shopify: "🛒",
  slack: "💬",
  discord: "💬",
  telegram: "💬",
  github: "🐙",
  gitlab: "🦊",
  google: "🔵",
  google_analytics: "📊",
  google_maps: "🗺️",
  google_search_console: "📈",
  hubspot: "🟠",
  salesforce: "☁️",
  intercom: "💬",
  jira: "📋",
  linear: "📐",
  notion: "📝",
  airtable: "📊",
  asana: "📋",
  trello: "📋",
  zendesk: "🎫",
  freshdesk: "🎫",
  pagerduty: "🔔",
  postgres: "🐘",
  mongodb: "🍃",
  redis: "🔴",
  bigquery: "📊",
  snowflake: "❄️",
  twitter: "🐦",
  reddit: "🤖",
  youtube: "▶️",
  cloudflare: "🌐",
  vercel: "▲",
  docker_hub: "🐳",
  huggingface: "🤗",
  apollo: "🚀",
  pipedrive: "📈",
  calcom: "📅",
  calendly: "📅",
  zoom: "📹",
  confluence: "📖",
  obsidian: "💎",
  plaid: "🏦",
  quickbooks: "📒",
  cloudinary: "🖼️",
  news: "📰",
  newsapi: "📰",
  apify: "🕷️",
  attio: "📇",
  greenhouse: "🌱",
  lusha: "👤",
  mattermost: "💬",
  microsoft_graph: "Ⓜ️",
  n8n: "⚙️",
  pushover: "🔔",
  sap: "🏢",
  terraform: "🏗️",
  tines: "🔄",
  databricks: "🧱",
  kafka: "📨",
  langfuse: "📡",
  powerbi: "📊",
  redshift: "🔴",
  azure_sql: "🔷",
  gcp_vision: "👁️",
  zoho_crm: "📇",
};

function getCredIcon(credId: string): string {
  // Try exact match, then prefix match
  if (CRED_ICONS[credId]) return CRED_ICONS[credId];
  for (const [key, icon] of Object.entries(CRED_ICONS)) {
    if (credId.startsWith(key)) return icon;
  }
  return "🔑";
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

export default function CredentialsPage() {
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [specs, setSpecs] = useState<CredentialSpec[]>([]);
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
  const lastFocusFetch = useRef(0);

  const fetchSpecs = useCallback(async () => {
    try {
      setError(null);
      const data = await credentialsApi.listSpecs();
      setSpecs(data.specs);
      setHasAdenKey(data.has_aden_key);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to load credentials"
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchSpecs();
  }, [fetchSpecs]);

  // Re-fetch on window focus (after OAuth return)
  useEffect(() => {
    const handleFocus = () => {
      const now = Date.now();
      if (now - lastFocusFetch.current < 3000) return;
      lastFocusFetch.current = now;
      fetchSpecs();
    };
    window.addEventListener("focus", handleFocus);
    return () => window.removeEventListener("focus", handleFocus);
  }, [fetchSpecs]);

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

  const handleConnect = (spec: CredentialSpec) => {
    // Pure-OAuth provider: open Aden and show the blocking modal that waits
    // for the user to finish authorizing before we resync and close.
    if (spec.aden_supported && !spec.direct_api_key_supported) {
      window.open("https://hive.adenhq.com/", "_blank", "noopener");
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
    if (spec.credential_id === "aden_api_key") {
      // Aden platform key — open tab and also allow pasting the key below.
      window.open("https://hive.adenhq.com/", "_blank", "noopener");
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
  const runResyncCheck = useCallback(
    async (silent: boolean = false) => {
      setAuthorizeModal((prev) => {
        if (!prev) return prev;
        if (silent) {
          return { ...prev, probing: true, probeResult: null };
        }
        return { ...prev, status: "checking" };
      });
      try {
        const resp = await credentialsApi.resync();
        setAuthorizeModal((prev) => {
          if (!prev) return prev;
          const provider = prev.spec.credential_id;
          const current = resp.accounts_by_provider[provider] ?? [];
          const before = new Set(prev.snapshotAliases);
          const fresh = current.find((a) => !before.has(a.alias)) ?? null;
          if (fresh) {
            return {
              ...prev,
              currentAccounts: current,
              status: "success",
              newAccount: fresh,
              probing: false,
              probeResult: null,
            };
          }
          if (silent) {
            // Stay in "waiting" — user may still be mid-authorization.
            // Surface a short-lived inline result so they know we checked.
            return {
              ...prev,
              currentAccounts: current,
              probing: false,
              probeResult: "No new account yet",
            };
          }
          return {
            ...prev,
            currentAccounts: current,
            status: "not_found",
            newAccount: null,
            probing: false,
            probeResult: null,
          };
        });
        // Refresh the page data so any new accounts render behind the modal.
        await fetchSpecs();
      } catch {
        setAuthorizeModal((prev) => {
          if (!prev) return prev;
          if (silent) {
            return {
              ...prev,
              probing: false,
              probeResult: "Check failed",
            };
          }
          return { ...prev, status: "not_found", probing: false };
        });
      }
    },
    [fetchSpecs]
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

  // Split into API Keys vs OAuth
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

  const activeCount = specs.filter((s) => s.available).length;
  const totalCount = specs.length;

  const apiKeyConnected = apiKeySpecs.filter((s) => s.available).length;
  const oauthConnected = oauthSpecs.filter((s) => s.available).length;

  const renderCard = (group: CredGroup) => {
    const primary = group.specs[0];
    const icon = getCredIcon(primary.credential_id);
    const isConnected = group.allAvailable;
    const isEditing = group.specs.some((s) => editingId === s.credential_id);
    const isDeleting = group.specs.some((s) => deletingId === s.credential_id);
    const hasInstructions = primary.api_key_instructions || primary.help_url;
    // Pure-OAuth providers (Aden-backed, no API key paste path) render each
    // connected account as its own row and expose an "Add another account"
    // affordance. Accounts are sourced from Aden, so lifecycle (add/remove)
    // happens on hive.adenhq.com; Hive just mirrors what it sees.
    const isPureOAuth =
      primary.aden_supported &&
      !primary.direct_api_key_supported &&
      primary.credential_id !== "aden_api_key";
    const accounts = primary.accounts ?? [];

    return (
      <div
        key={group.groupKey}
        className={`rounded-xl border p-4 flex flex-col transition-colors ${
          isConnected
            ? "border-primary/30 bg-primary/[0.03]"
            : "border-border/60 bg-card"
        }`}
      >
        {/* Card header */}
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-muted/40 flex items-center justify-center text-xl flex-shrink-0">
              {icon}
            </div>
            <div>
              <h3 className="text-sm font-semibold text-foreground">
                {primary.credential_name}
              </h3>
              <p className="text-[11px] text-muted-foreground mt-0.5 line-clamp-2">
                {primary.description}
              </p>
            </div>
          </div>
          <span
            className={`text-[10px] font-semibold uppercase tracking-wider px-2 py-0.5 rounded-full flex-shrink-0 ${
              isConnected
                ? "bg-emerald-500/15 text-emerald-600"
                : primary.aden_supported
                  ? "bg-blue-500/10 text-blue-500"
                  : "bg-muted/60 text-muted-foreground"
            }`}
          >
            {isConnected
              ? "Connected"
              : primary.aden_supported
                ? "OAuth"
                : "API Key"}
          </span>
        </div>

        {/* Spacer — pushes the action row to the bottom */}
        <div className="flex-1" />

        {/* Action row — always pinned to card bottom */}
        <div className="pt-3">
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
          ) : isConnected && isPureOAuth && accounts.length > 0 ? (
            <div className="flex flex-col gap-1.5">
              {accounts.map((acct) => {
                const email = acct.identity?.email || "";
                const label = email || acct.alias || "connected";
                const sub = email && acct.alias && acct.alias !== email ? acct.alias : "";
                return (
                  <div
                    key={`${acct.provider}:${acct.alias}:${acct.credential_id}`}
                    className="flex items-center justify-between text-xs"
                  >
                    <div className="flex items-center gap-1.5 text-muted-foreground min-w-0">
                      <KeyRound className="w-3 h-3 flex-shrink-0" />
                      <span className="truncate text-foreground">{label}</span>
                      {sub && (
                        <span className="truncate text-muted-foreground/60">
                          · {sub}
                        </span>
                      )}
                    </div>
                  </div>
                );
              })}
              <button
                onClick={() => handleConnect(primary)}
                className="flex items-center gap-1 text-[11px] font-medium text-primary hover:text-primary/80 transition-colors mt-0.5 self-start"
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
                {(!primary.aden_supported || primary.direct_api_key_supported) && (
                  <button
                    onClick={() => { setEditingId(primary.credential_id); setInputValue(""); setDeletingId(null); }}
                    className="text-[11px] text-muted-foreground hover:text-foreground transition-colors"
                  >
                    Update
                  </button>
                )}
                <button
                  onClick={() => { setDeletingId(primary.credential_id); setEditingId(null); setInputValue(""); }}
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
                onClick={() => handleConnect(primary)}
                disabled={
                  primary.aden_supported &&
                  !primary.direct_api_key_supported &&
                  !hasAdenKey &&
                  primary.credential_id !== "aden_api_key"
                }
                className="flex items-center gap-1.5 text-xs font-medium text-primary hover:text-primary/80 transition-colors disabled:text-muted-foreground disabled:cursor-not-allowed"
              >
                {primary.aden_supported && !primary.direct_api_key_supported ? (
                  <>
                    <ExternalLink className="w-3 h-3" />
                    Authorize
                  </>
                ) : (
                  <>
                    <span className="text-sm">+</span> Add key
                    <span className="text-muted-foreground/50">›</span>
                  </>
                )}
              </button>
              {hasInstructions && (
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
      <div className="flex-1 overflow-y-auto">
        <div className="max-w-6xl mx-auto px-6 py-8">
          {/* Title + search row */}
          <div className="flex items-start justify-between mb-6">
            <div>
              <h2 className="text-2xl font-bold text-foreground">
                Credentials
              </h2>
              {!loading && (
                <p className="text-sm text-muted-foreground mt-1">
                  {activeCount} active &middot; {totalCount} available
                </p>
              )}
            </div>
            <div className="relative w-64">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground/50" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search credentials..."
                className="w-full pl-9 pr-3 py-2 rounded-lg border border-border/60 bg-card text-sm text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-primary/40"
              />
            </div>
          </div>

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
              {/* API Keys section */}
              <div className="mb-8">
                <div className="flex items-center gap-2 mb-4">
                  <KeyRound className="w-4 h-4 text-muted-foreground" />
                  <h3 className="text-sm font-semibold text-foreground">
                    API Keys
                  </h3>
                  <span className="text-xs text-muted-foreground bg-muted/50 px-2 py-0.5 rounded-full">
                    {apiKeyConnected}/{apiKeySpecs.length}
                  </span>
                </div>
                {apiKeyGroups.length === 0 ? (
                  <p className="text-sm text-muted-foreground py-4">
                    {searchQuery
                      ? "No API keys match your search"
                      : "No API key credentials available"}
                  </p>
                ) : (
                  <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                    {apiKeyGroups.map(renderCard)}
                  </div>
                )}
              </div>

              {/* OAuth section */}
              <div>
                <div className="flex items-center gap-2 mb-4">
                  <Link2 className="w-4 h-4 text-muted-foreground" />
                  <h3 className="text-sm font-semibold text-foreground">
                    OAuth Connections
                  </h3>
                  <span className="text-xs text-muted-foreground bg-muted/50 px-2 py-0.5 rounded-full">
                    {oauthConnected}/{oauthSpecs.length}
                  </span>
                </div>
                {/* Aden Platform key card first */}
                {adenSpec && (
                  <div className="mb-3">
                    {renderCard({
                      groupKey: "aden_api_key",
                      label: "Aden Platform",
                      specs: [adenSpec],
                      allAvailable: adenSpec.available,
                      anyAvailable: adenSpec.available,
                    })}
                  </div>
                )}
                {oauthGroups.length === 0 ? (
                  <p className="text-sm text-muted-foreground py-4">
                    {searchQuery
                      ? "No OAuth connections match your search"
                      : "No OAuth credentials available"}
                  </p>
                ) : (
                  <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                    {oauthGroups.map(renderCard)}
                  </div>
                )}
              </div>
            </>
          )}
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
                <span className="text-base">
                  {getCredIcon(popover.spec.credential_id)}
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
                <div className="w-10 h-10 rounded-lg bg-muted/40 flex items-center justify-center text-xl">
                  {getCredIcon(authorizeModal.spec.credential_id)}
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
                          const sub =
                            email && acct.alias && acct.alias !== email
                              ? acct.alias
                              : "";
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
                      onClick={() =>
                        window.open(
                          "https://hive.adenhq.com/",
                          "_blank",
                          "noopener"
                        )
                      }
                      className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium border border-border/60 text-foreground hover:bg-muted/50 transition-colors"
                    >
                      <ExternalLink className="w-3 h-3" />
                      Reopen Aden
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
                      onClick={() =>
                        window.open(
                          "https://hive.adenhq.com/",
                          "_blank",
                          "noopener"
                        )
                      }
                      className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium border border-border/60 text-foreground hover:bg-muted/50 transition-colors"
                    >
                      <ExternalLink className="w-3 h-3" />
                      Reopen Aden
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
                      onClick={() => setAuthorizeModal(null)}
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

      <SettingsModal
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
      />
    </>
  );
}
