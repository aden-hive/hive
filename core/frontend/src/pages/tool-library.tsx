import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Wrench, Crown, Network, Server, Plus, Loader2, AlertCircle } from "lucide-react";
import { queensApi } from "@/api/queens";
import { coloniesApi, type ColonySummary } from "@/api/colonies";
import { slugToDisplayName, sortQueenProfiles } from "@/lib/colony-registry";
import QueenToolsSection from "@/components/QueenToolsSection";
import { QueenSelect } from "@/components/QueenSelect";
import ColonyToolsSection from "@/components/ColonyToolsSection";
import McpServersPanel from "@/components/McpServersPanel";
import { isQueenDecommissioned, useMe } from "@/lib/me";

type Tab = "queens" | "colonies" | "mcp";

export default function ToolLibrary({ embedded = false }: { embedded?: boolean } = {}) {
  const [searchParams] = useSearchParams();
  // Deep-link target, e.g. from the queen profile panel's "Configure tools"
  // link: /skills-library?tab=mcp&queen=<id> lands on the Queens tab with that
  // queen already selected.
  const initialQueenId = searchParams.get("queen");
  const [tab, setTab] = useState<Tab>("queens");
  const [mcpAddOpen, setMcpAddOpen] = useState(false);

  // The add-MCP action sits next to the tab bar: in our own page header when
  // standalone, or inline beside the sub-tabs when embedded in the Skills
  // page (which supplies the outer header).
  const addMcpButton =
    tab === "mcp" ? (
      <button
        onClick={() => setMcpAddOpen(true)}
        className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-primary text-primary-foreground text-xs font-medium hover:bg-primary/90"
      >
        <Plus className="w-3.5 h-3.5" />
        Add MCP Server
      </button>
    ) : null;

  const tabBar = (
    <div className="flex items-center gap-1">
      <TabButton active={tab === "queens"} onClick={() => setTab("queens")} icon={<Crown className="w-3.5 h-3.5" />}>
        By Queen
      </TabButton>
      <TabButton active={tab === "colonies"} onClick={() => setTab("colonies")} icon={<Network className="w-3.5 h-3.5" />}>
        By Colony
      </TabButton>
      <TabButton active={tab === "mcp"} onClick={() => setTab("mcp")} icon={<Server className="w-3.5 h-3.5" />}>
        MCP Servers
      </TabButton>
    </div>
  );

  return (
    <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
      {/* Header. When embedded in the Skills page's "MCP Tools" tab the host
          supplies the page title + top border, so we drop our own title and
          border to avoid a stacked double header — keeping only the sub-tabs. */}
      <div className={embedded ? "px-6 pt-4 pb-3" : "px-6 py-4 border-b border-border/60"}>
        {!embedded && (
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-baseline gap-3">
              <h2
                data-tour="tour-queen-configs"
                className="text-base font-semibold text-foreground flex items-center gap-2"
              >
                <Wrench className="w-5 h-5 text-primary" />
                Agent Access
              </h2>
              <span className="text-xs text-muted-foreground">
                Choose the apps and capabilities each agent can use, and connect your own integrations.
              </span>
            </div>
            {addMcpButton}
          </div>
        )}
        {embedded && (
          <p className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider mb-2">
            Tool Access · who can use which tools
          </p>
        )}
        <div className="flex items-center justify-between gap-2">
          {tabBar}
          {embedded && addMcpButton}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto">
        {tab === "queens" && <QueensTab initialQueenId={initialQueenId} />}
        {tab === "colonies" && <ColoniesTab />}
        {tab === "mcp" && (
          <div className="px-6 py-6 max-w-4xl">
            <McpServersPanel addOpen={mcpAddOpen} setAddOpen={setMcpAddOpen} />
          </div>
        )}
      </div>
    </div>
  );
}

function TabButton({
  active,
  onClick,
  icon,
  children,
}: {
  active: boolean;
  onClick: () => void;
  icon: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium ${
        active
          ? "bg-primary/15 text-primary"
          : "text-muted-foreground hover:text-foreground hover:bg-muted/30"
      }`}
    >
      {icon}
      {children}
    </button>
  );
}

// ----- Queens tab ---------------------------------------------------------

function QueensTab({ initialQueenId }: { initialQueenId?: string | null }) {
  const [queens, setQueens] = useState<Array<{ id: string; name: string; title: string }> | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const { me } = useMe();
  const visibleQueens = useMemo(
    () => (queens ?? []).filter((q) => !isQueenDecommissioned(me, q.id)),
    [queens, me],
  );

  useEffect(() => {
    queensApi
      .list()
      .then((r) => {
        const sorted = sortQueenProfiles(r.queens);
        setQueens(sorted);
      })
      .catch((e: Error) => setError(e.message || "Failed to load queens"));
  }, []);

  // Auto-select the first visible queen once available, and re-select if
  // the user decommissions the currently-selected one. A deep-link
  // (initialQueenId) wins over the first-queen default when it's valid.
  useEffect(() => {
    if (visibleQueens.length === 0) {
      setSelected(null);
      return;
    }
    setSelected((prev) => {
      if (prev && visibleQueens.some((q) => q.id === prev)) return prev;
      if (initialQueenId && visibleQueens.some((q) => q.id === initialQueenId))
        return initialQueenId;
      return visibleQueens[0].id;
    });
  }, [visibleQueens, initialQueenId]);

  if (error) return <ErrorBlock message={error} />;
  if (queens === null) return <LoadingBlock label="Loading queens…" />;
  if (visibleQueens.length === 0)
    return <EmptyBlock label="No queens yet. Create one to curate its tools." />;

  return (
    <div className="px-6 py-5">
      <div className="mb-4">
        <label className="block text-[11px] font-medium text-muted-foreground uppercase tracking-wider mb-1.5">
          Queen
        </label>
        <QueenSelect
          queens={visibleQueens}
          value={selected}
          onChange={setSelected}
          buttonClassName="w-full max-w-[320px]"
        />
      </div>
      {selected ? (
        <QueenToolsSection queenId={selected} />
      ) : (
        <EmptyBlock label="Pick a queen to edit her tool allowlist." />
      )}
    </div>
  );
}

// ----- Colonies tab -------------------------------------------------------

function ColoniesTab() {
  const [colonies, setColonies] = useState<ColonySummary[] | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    coloniesApi
      .list()
      .then((r) => {
        setColonies(r.colonies);
        if (r.colonies.length > 0)
          setSelected((prev) => prev ?? r.colonies[0].name);
      })
      .catch((e: Error) => setError(e.message || "Failed to load colonies"));
  }, []);

  const sorted = useMemo(() => {
    if (!colonies) return null;
    return [...colonies].sort((a, b) => a.name.localeCompare(b.name));
  }, [colonies]);

  if (error) return <ErrorBlock message={error} />;
  if (sorted === null) return <LoadingBlock label="Loading colonies…" />;
  if (sorted.length === 0)
    return (
      <EmptyBlock label="No colonies yet. Ask a queen to incubate one and its tools will show up here." />
    );

  return (
    <div className="px-6 py-5">
      <div className="mb-4">
        <label className="block text-[11px] font-medium text-muted-foreground uppercase tracking-wider mb-1.5">
          Colony
        </label>
        <select
          value={selected ?? ""}
          onChange={(e) => setSelected(e.target.value || null)}
          className="w-full max-w-[320px] bg-muted/30 border border-border/50 rounded-lg px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-primary/40"
        >
          {sorted.map((c) => (
            <option key={c.name} value={c.name}>
              {slugToDisplayName(c.name)}{c.queen_name ? ` — @${c.queen_name}` : ""}
            </option>
          ))}
        </select>
      </div>
      {selected ? (
        <ColonyToolsSection colonyName={selected} />
      ) : (
        <EmptyBlock label="Pick a colony to edit its tool allowlist." />
      )}
    </div>
  );
}

// ----- Shared primitives --------------------------------------------------

function LoadingBlock({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-2 text-xs text-muted-foreground px-6 py-6">
      <Loader2 className="w-3 h-3 animate-spin" />
      {label}
    </div>
  );
}

function EmptyBlock({ label }: { label: string }) {
  return (
    <div className="flex items-start gap-2 text-xs text-muted-foreground px-6 py-6">
      <AlertCircle className="w-3.5 h-3.5 mt-0.5" />
      <span>{label}</span>
    </div>
  );
}

function ErrorBlock({ message }: { message: string }) {
  return (
    <div className="flex items-start gap-2 text-xs text-destructive px-6 py-6">
      <AlertCircle className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" />
      <span>{message}</span>
    </div>
  );
}
