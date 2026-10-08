import {
  Users,
  X,
  Loader2,
  Square,
  CheckSquare,
  Send,
  History,
  RotateCw,
  Sparkles,
  ArrowDown,
  Download,
  Maximize2,
} from "lucide-react";
import { DEMO_COLONY_TITLE } from "./demoColony";

/**
 * A self-contained, non-interactive mock of the colony workspace, shown during
 * the "Inside a colony" tutorial step. The overlay renders it edge-to-edge into
 * the real content pane (right of the live sidebar, below the live header), so
 * it reads as if the user has opened a real colony — only the data is scripted.
 * No backend session, no API calls, nothing in the sidebar.
 *
 * Structure and styling deliberately mirror the real colony page: the chat
 * transcript on the left (ChatPanel) and the tabbed COLONY panel on the right
 * (ColonyPanel → Overview → TaskListPanel). Task-row icons match
 * TaskItem.tsx: amber spinner = in progress, muted square = pending, emerald
 * check = done.
 */
type DemoTaskStatus = "in_progress" | "pending" | "completed";

const DEMO_TASKS: { label: string; status: DemoTaskStatus }[] = [
  { label: "Define ICP & search criteria", status: "in_progress" },
  { label: "Pull candidate companies from data sources", status: "pending" },
  { label: "Enrich contacts — emails & LinkedIn", status: "pending" },
  { label: "Score & rank leads by fit", status: "pending" },
  { label: "Draft personalized outreach", status: "pending" },
];

/** Scripted rows for the Data-tab view — the "warm leads" payoff moment.
 *  Columns mirror what the real DataTab renders for a leads table, trimmed
 *  to fit the 380px panel. */
const DEMO_LEADS: { name: string; company: string; fit: number }[] = [
  { name: "Maya Chen", company: "Parcelio", fit: 94 },
  { name: "Jordan Reyes", company: "Driftlane", fit: 91 },
  { name: "Sam Okafor", company: "Quillbase", fit: 88 },
  { name: "Priya Nair", company: "Loopwell", fit: 86 },
  { name: "Alex Fontaine", company: "Nestor AI", fit: 83 },
  { name: "Dana Whitfield", company: "Corely", fit: 79 },
];

function TaskStatusIcon({ status }: { status: DemoTaskStatus }) {
  if (status === "in_progress")
    return <Loader2 className="h-3.5 w-3.5 animate-spin text-amber-500" aria-label="in progress" />;
  if (status === "completed")
    return <CheckSquare className="h-3.5 w-3.5 text-emerald-600" aria-label="completed" />;
  return <Square className="h-3.5 w-3.5 text-muted-foreground/60" aria-label="pending" />;
}

/** Mirrors ColonyPanel's TabButton (non-interactive here). */
function DemoTab({ label, active }: { label: string; active?: boolean }) {
  return (
    <div
      className={`flex-1 whitespace-nowrap px-3 py-2 text-xs font-medium text-center border-b-2 ${
        active
          ? "border-primary text-foreground"
          : "border-transparent text-muted-foreground"
      }`}
    >
      {label}
    </div>
  );
}

/** Compact leads view — mirrors the real DataTab anatomy at panel width:
 *  table-picker chips (selected count, amber "+N" freshness badge on the
 *  unviewed table), a DataGrid-style table (semibold humanized headers, sort
 *  arrow, column rules, primary/5 zebra, mono cells, right-aligned numerics,
 *  bordered value pills), the amber flash on the freshest row, and the
 *  dot + row-count footer. Non-interactive; the "Warm" pills stay the payoff
 *  the tour copy points at, and the italic "more" row (real grid's truncation
 *  idiom) carries the "still working" narrative. */
function DemoLeadsTable() {
  return (
    <div className="w-full h-full flex flex-col overflow-hidden">
      {/* Table picker + actions — mirrors DataTab's chip row */}
      <div className="flex items-start justify-between gap-2 mb-2 flex-shrink-0">
        <div className="flex min-w-0 flex-1 gap-1.5 overflow-hidden">
          <span className="shrink-0 whitespace-nowrap text-[10.5px] font-mono px-2 py-1 rounded border border-primary bg-primary/15 text-foreground font-medium">
            leads <span className="font-normal text-muted-foreground/70">(48)</span>
          </span>
          <span className="shrink-0 whitespace-nowrap text-[10.5px] font-mono px-2 py-1 rounded border border-amber-500/50 bg-background/40 text-muted-foreground">
            companies
            <span className="ml-1.5 inline-flex items-center gap-1 font-semibold text-amber-600 dark:text-amber-400">
              <span className="inline-flex h-1.5 w-1.5 rounded-full bg-amber-500" />
              +3
            </span>
          </span>
        </div>
        <div className="flex flex-shrink-0 items-center gap-0.5 text-muted-foreground">
          <span className="p-1.5"><Download className="w-3.5 h-3.5" /></span>
          <span className="p-1.5"><Maximize2 className="w-3.5 h-3.5" /></span>
        </div>
      </div>
      {/* Grid — mirrors DataGrid */}
      <div className="flex-1 min-h-0 border border-border/60 rounded-lg overflow-hidden">
        <table className="w-full text-[11px] border-collapse">
          <thead className="bg-card/95">
            <tr>
              <th className="text-left font-semibold text-foreground/90 border-b border-border/60 px-2 py-1.5 whitespace-nowrap">
                Name
              </th>
              <th className="text-left font-semibold text-foreground/90 border-b border-border/60 px-2 py-1.5 whitespace-nowrap">
                Company
              </th>
              <th className="text-right font-semibold text-foreground/90 border-b border-border/60 px-2 py-1.5 whitespace-nowrap">
                <span className="inline-flex items-center gap-1">
                  Fit
                  <ArrowDown className="w-3 h-3 shrink-0 text-primary" />
                </span>
              </th>
              <th className="text-left font-semibold text-foreground/90 border-b border-border/60 px-2 py-1.5 whitespace-nowrap">
                Status
              </th>
            </tr>
          </thead>
          <tbody>
            {DEMO_LEADS.map((l, i) => (
              <tr
                key={l.name}
                className={`border-b border-border/30 ${
                  // Freshest row wears the amber "just landed" flash (wins
                  // over zebra), exactly like the live grid.
                  i === DEMO_LEADS.length - 1
                    ? "bg-amber-400/20"
                    : i % 2 === 1
                      ? "bg-primary/5"
                      : ""
                }`}
              >
                <td className="border-r border-border/20 px-1.5 py-1 font-mono text-foreground/90 whitespace-nowrap">
                  {l.name}
                </td>
                <td className="border-r border-border/20 px-1.5 py-1 font-mono text-foreground/90 whitespace-nowrap">
                  {l.company}
                </td>
                <td className="border-r border-border/20 px-1.5 py-1 font-mono text-right tabular-nums text-foreground/90">
                  {l.fit}
                </td>
                <td className="px-1.5 py-1">
                  <span className="inline-flex items-center rounded-full border border-amber-500/35 bg-amber-500/10 text-amber-600 dark:text-amber-400 px-2 py-0.5 text-[10px] font-medium leading-tight">
                    Warm
                  </span>
                </td>
              </tr>
            ))}
            <tr>
              <td
                colSpan={4}
                className="px-2 py-1.5 text-center text-[10px] italic text-muted-foreground/50"
              >
                + 42 more as the colony works…
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      {/* Footer — mirrors TableView's live dot + row count + pager */}
      <div className="flex flex-shrink-0 items-center justify-between text-[10px] text-muted-foreground mt-2">
        <span className="flex items-center gap-1.5">
          <span className="w-1.5 h-1.5 rounded-full bg-primary/60 animate-pulse" />
          <span>48 rows</span>
        </span>
        <div className="flex gap-1">
          <span className="px-2 py-0.5 rounded border border-border/50 opacity-40">Prev</span>
          <span className="px-2 py-0.5 rounded border border-border/50 opacity-40">Next</span>
        </div>
      </div>
    </div>
  );
}

export default function TutorialColonyDemo({ view = "plan" }: { view?: "plan" | "data" }) {
  return (
    <div className="h-full w-full flex bg-background overflow-hidden select-none">
      {/* Conversation (left) — mirrors ChatPanel */}
      <div className="flex-1 min-w-0 flex flex-col" data-tour="tour-demo-chat">
        <div className="flex-1 min-h-0 overflow-hidden px-5 py-6 space-y-4">
          {/* User message */}
          <div className="flex justify-end">
            <div className="max-w-[78%] rounded-2xl rounded-br-sm bg-primary text-primary-foreground px-4 py-2.5 text-[13px] leading-relaxed">
              Find 50 qualified leads for our Series A outreach — SaaS founders,
              US-based, 10–50 employees.
            </div>
          </div>
          {/* Queen reply */}
          <div className="flex items-start gap-2.5">
            <div className="w-7 h-7 rounded-full bg-primary/15 flex items-center justify-center flex-shrink-0 mt-0.5">
              <Sparkles className="w-3.5 h-3.5 text-primary" />
            </div>
            <div className="min-w-0">
              <div className="text-[11px] font-medium text-muted-foreground mb-1">
                Head of Growth
              </div>
              <div className="max-w-[94%] rounded-2xl rounded-bl-sm bg-muted/60 text-foreground px-4 py-2.5 text-[13px] leading-relaxed">
                On it. I've drafted a plan and started on your ICP — track
                progress on the right as I work through each step.
              </div>
            </div>
          </div>
        </div>
        {/* Faux composer (decorative) */}
        <div className="px-5 pb-5 flex-shrink-0">
          <div className="flex items-center gap-2 rounded-xl border border-border/60 bg-card px-3.5 py-2.5">
            <span className="flex-1 text-[13px] text-muted-foreground/60">
              Message the Head of Growth…
            </span>
            <div className="w-7 h-7 rounded-lg bg-primary/15 flex items-center justify-center">
              <Send className="w-3.5 h-3.5 text-primary" />
            </div>
          </div>
        </div>
      </div>

      {/* Colony panel (right) — mirrors ColonyPanel */}
      <aside
        className="flex-shrink-0 w-[380px] border-l border-border/60 bg-card overflow-hidden flex flex-col"
        data-tour="tour-demo-panel"
      >
        {/* Panel header */}
        <div className="flex items-center justify-between px-5 py-3.5 border-b border-border/60 flex-shrink-0">
          <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
            <Users className="w-4 h-4 text-primary" />
            COLONY
          </div>
          <X className="w-4 h-4 text-muted-foreground" />
        </div>
        {/* Tab bar — Data becomes the active tab on the leads step */}
        <div className="flex border-b border-border/60 flex-shrink-0">
          <DemoTab label="Data" active={view === "data"} />
          <DemoTab label="Plan" active={view === "plan"} />
          <DemoTab label="Automations" />
          <DemoTab label="Workers" />
        </div>
        {view === "data" ? (
          /* Data body → warm-leads grid */
          <div className="flex-1 min-h-0 overflow-hidden p-2">
            <DemoLeadsTable />
          </div>
        ) : (
          /* Plan body → embedded Tasks panel */
          <div className="flex-1 min-h-0 overflow-hidden p-2">
            <div className="w-full h-full border border-border rounded-md bg-background flex flex-col overflow-hidden">
              <div className="flex items-start justify-between gap-2 px-3 py-2 border-b border-border">
                <div className="min-w-0">
                  <span className="block text-[11px] font-medium uppercase tracking-wide text-muted-foreground tabular-nums">
                    Tasks · 1/5
                  </span>
                  <h2 className="text-sm font-semibold truncate">
                    {DEMO_COLONY_TITLE}
                  </h2>
                </div>
              </div>
              <div className="flex-1 min-h-0 overflow-y-auto p-2">
                <ul className="space-y-0.5">
                  {DEMO_TASKS.map((t) => (
                    <li key={t.label} className="flex items-start gap-2 px-1.5 py-1.5 rounded">
                      <span className="mt-0.5 flex-shrink-0">
                        <TaskStatusIcon status={t.status} />
                      </span>
                      <span
                        className={`text-sm leading-snug ${
                          t.status === "completed"
                            ? "line-through text-muted-foreground"
                            : t.status === "in_progress"
                              ? "text-foreground"
                              : "text-muted-foreground"
                        }`}
                      >
                        {t.label}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
              {/* Footer — mirrors ActionPlanFooter */}
              <div className="flex items-center gap-3 px-2.5 py-2 border-t border-border flex-shrink-0">
                <span className="inline-flex items-center gap-1.5 text-[11px] font-medium text-muted-foreground">
                  <History className="w-3 h-3" />
                  History
                </span>
                <span className="ml-auto inline-flex items-center gap-1.5 text-[11px] font-medium text-primary">
                  <RotateCw className="w-3 h-3" />
                  Update plan
                </span>
              </div>
            </div>
          </div>
        )}
      </aside>
    </div>
  );
}
