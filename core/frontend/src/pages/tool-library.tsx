import { useEffect, useMemo, useState } from "react";
import { Wrench, Crown, Network, Server, Loader2, AlertCircle } from "lucide-react";
import { queensApi } from "@/api/queens";
import { coloniesApi, type ColonySummary } from "@/api/colonies";
import { slugToDisplayName, sortQueenProfiles } from "@/lib/colony-registry";
import QueenToolsSection from "@/components/QueenToolsSection";
import ColonyToolsSection from "@/components/ColonyToolsSection";
import McpServersPanel from "@/components/McpServersPanel";

type Tab = "queens" | "colonies" | "mcp";

export default function ToolLibrary() {
  const [tab, setTab] = useState<Tab>("queens");

  return (
    <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
      {/* Header */}
      <div className="px-6 py-4 border-b border-border/60">
        <div className="flex items-baseline gap-3 mb-3">
          <h2 className="text-lg font-semibold text-foreground flex items-center gap-2">
            <Wrench className="w-5 h-5 text-primary" />
            Tool Configuration
          </h2>
          <span className="text-xs text-muted-foreground">
            Curate which tools each queen and colony can call, and register your own MCP servers.
          </span>
        </div>
        <div className="flex items-center gap-1">
          <TabButton active={tab === "queens"} onClick={() => setTab("queens")} icon={<Crown className="w-3.5 h-3.5" />}>
            Queens
          </TabButton>
          <TabButton active={tab === "colonies"} onClick={() => setTab("colonies")} icon={<Network className="w-3.5 h-3.5" />}>
            Colonies
          </TabButton>
          <TabButton active={tab === "mcp"} onClick={() => setTab("mcp")} icon={<Server className="w-3.5 h-3.5" />}>
            MCP Servers
          </TabButton>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto">
        {tab === "queens" && <QueensTab />}
        {tab === "colonies" && <ColoniesTab />}
        {tab === "mcp" && (
          <div className="px-6 py-6 max-w-4xl">
            <McpServersPanel />
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
      className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium ${
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

function QueensTab() {
  const [queens, setQueens] = useState<Array<{ id: string; name: string; title: string }> | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    queensApi
      .list()
      .then((r) => {
        const sorted = sortQueenProfiles(r.queens);
        setQueens(sorted);
        if (sorted.length > 0) setSelected((prev) => prev ?? sorted[0].id);
      })
      .catch((e: Error) => setError(e.message || "Failed to load queens"));
  }, []);

  if (error) return <ErrorBlock message={error} />;
  if (queens === null) return <LoadingBlock label="Loading queens…" />;
  if (queens.length === 0)
    return <EmptyBlock label="No queens yet. Create one to curate its tools." />;

  return (
    <div className="flex h-full">
      <SidePicker>
        {queens.map((q) => (
          <PickerItem
            key={q.id}
            active={selected === q.id}
            onClick={() => setSelected(q.id)}
            primary={q.name}
            secondary={q.title}
          />
        ))}
      </SidePicker>
      <div className="flex-1 overflow-y-auto px-6 py-5 min-w-0">
        {selected ? (
          <>
            {(() => {
              const queen = queens.find((q) => q.id === selected);
              return queen ? (
                <div className="mb-4 pb-3 border-b border-border/40">
                  <h3 className="text-base font-semibold text-foreground">
                    {queen.name}
                  </h3>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    {queen.title}
                  </p>
                </div>
              ) : null;
            })()}
            <QueenToolsSection queenId={selected} />
          </>
        ) : (
          <EmptyBlock label="Pick a queen to edit her tool allowlist." />
        )}
      </div>
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
    <div className="flex h-full">
      <SidePicker>
        {sorted.map((c) => (
          <PickerItem
            key={c.name}
            active={selected === c.name}
            onClick={() => setSelected(c.name)}
            primary={slugToDisplayName(c.name)}
            secondary={
              c.has_allowlist
                ? `${c.enabled_count ?? 0} tools allowed · ${c.queen_name ?? ""}`
                : `all tools · ${c.queen_name ?? ""}`
            }
            tertiary={c.name}
          />
        ))}
      </SidePicker>
      <div className="flex-1 overflow-y-auto px-6 py-5 min-w-0">
        {selected ? (
          <>
            <div className="mb-4 pb-3 border-b border-border/40">
              <h3 className="text-base font-semibold text-foreground">
                {slugToDisplayName(selected)}
              </h3>
              <p className="text-[11px] text-muted-foreground font-mono mt-0.5">
                {selected}
              </p>
            </div>
            <ColonyToolsSection colonyName={selected} />
          </>
        ) : (
          <EmptyBlock label="Pick a colony to edit its tool allowlist." />
        )}
      </div>
    </div>
  );
}

// ----- Shared primitives --------------------------------------------------

function SidePicker({ children }: { children: React.ReactNode }) {
  return (
    <div className="w-[260px] flex-shrink-0 border-r border-border/60 overflow-y-auto py-3 px-2 flex flex-col gap-1">
      {children}
    </div>
  );
}

function PickerItem({
  active,
  onClick,
  primary,
  secondary,
  tertiary,
}: {
  active: boolean;
  onClick: () => void;
  primary: string;
  secondary?: string;
  tertiary?: string;
}) {
  return (
    <button
      onClick={onClick}
      className={`text-left px-3 py-2 rounded-md text-sm ${
        active
          ? "bg-primary/15 text-primary"
          : "text-foreground hover:bg-muted/30"
      }`}
    >
      <div className="font-medium truncate">{primary}</div>
      {secondary && (
        <div className="text-[11px] text-muted-foreground truncate">
          {secondary}
        </div>
      )}
      {tertiary && (
        <div className="text-[10px] text-muted-foreground/60 font-mono truncate">
          {tertiary}
        </div>
      )}
    </button>
  );
}

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
