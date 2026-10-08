// Skill "capsules" — color-coded chips that represent a skill from the live
// skill library. Two surfaces consume this module:
//
//   1. The composers (New Chat / Queen DM / Colony chat) build a typeahead
//      from the *live* skill index (see use-skill-index.ts) and pin selected
//      skills as capsules. On send, `buildSteeredMessage` appends a steering
//      instruction to the LLM-visible message so the agent actually uses the
//      attached skill.
//
//   2. The prompt cards (home + library) show capsules *inferred* from the
//      prompt text via `inferSkillCapsules` — purely indicative chips so a
//      reader can see at a glance which skills a recipe leans on.
//
// Both surfaces share one domain → color palette so a "LinkedIn Automation"
// chip looks the same whether it's on a card or pinned in the composer.

export type SkillDomain =
  | "growth"
  | "sales"
  | "ops"
  | "support"
  | "finance"
  | "product"
  | "data"
  | "research"
  | "comms"
  | "general";

export interface SkillCapsule {
  /** Addressing key — the skill's library name (e.g. "hive.browser-automation")
   *  for live capsules, or a stable slug for inferred card chips. This is what
   *  gets injected into the steering instruction. */
  name: string;
  /** Human display label (e.g. "Browser Automation"). */
  label: string;
  description?: string;
  domain: SkillDomain;
}

// Default domain palette. growth=green, ops=blue, finance=amber, support=violet
// per the product spec; the rest fill out the wheel without colliding.
export const DOMAIN_COLORS: Record<SkillDomain, { chip: string; dot: string }> = {
  growth: { chip: "bg-emerald-500/10 text-emerald-600 border-emerald-500/20", dot: "bg-emerald-500" },
  sales: { chip: "bg-teal-500/10 text-teal-600 border-teal-500/20", dot: "bg-teal-500" },
  ops: { chip: "bg-blue-500/10 text-blue-600 border-blue-500/20", dot: "bg-blue-500" },
  support: { chip: "bg-violet-500/10 text-violet-600 border-violet-500/20", dot: "bg-violet-500" },
  finance: { chip: "bg-amber-500/10 text-amber-600 border-amber-500/20", dot: "bg-amber-500" },
  product: { chip: "bg-fuchsia-500/10 text-fuchsia-600 border-fuchsia-500/20", dot: "bg-fuchsia-500" },
  data: { chip: "bg-cyan-500/10 text-cyan-600 border-cyan-500/20", dot: "bg-cyan-500" },
  research: { chip: "bg-indigo-500/10 text-indigo-600 border-indigo-500/20", dot: "bg-indigo-500" },
  comms: { chip: "bg-rose-500/10 text-rose-600 border-rose-500/20", dot: "bg-rose-500" },
  general: { chip: "bg-slate-500/10 text-slate-600 border-slate-500/20", dot: "bg-slate-500" },
};

export function capsuleColor(domain: SkillDomain) {
  return DOMAIN_COLORS[domain] ?? DOMAIN_COLORS.general;
}

// Acronyms that should stay upper-cased when prettifying a skill name.
const ACRONYMS = new Set([
  "crm", "seo", "api", "ats", "dm", "pr", "hr", "ai", "sdr", "kpi", "roi",
  "csv", "pdf", "url", "ui", "ux", "nps", "io", "qa",
]);

/** "hive.browser-automation" → "Browser Automation". */
export function formatSkillLabel(name: string): string {
  const stripped = name.replace(/^hive\./i, "");
  return stripped
    .split(/[.\-_\s]+/)
    .filter(Boolean)
    .map((w) =>
      ACRONYMS.has(w.toLowerCase())
        ? w.toUpperCase()
        : w.charAt(0).toUpperCase() + w.slice(1),
    )
    .join(" ");
}

// Keyword → domain. First match wins (order matters — more specific first).
const DOMAIN_KEYWORDS: Array<[SkillDomain, string[]]> = [
  ["sales", ["linkedin", "outbound", "prospect", "sdr", "bdr", "crm", "hubspot", "salesforce", "lead", "outreach", "cold email"]],
  ["finance", ["invoice", "expense", "ledger", "cash-flow", "cashflow", "accounting", "reconcil", "10-k", "earnings", "billing", "budget"]],
  ["support", ["zendesk", "intercom", "ticket", "support", "nps", "onboarding", "helpdesk", "review repl"]],
  ["ops", ["browser", "scrape", "navigate", "crawl", "pagerduty", "jira", "incident", "on-call", "vendor", "automation", "workflow"]],
  ["research", ["research", "monitor", "brief", "sources", "intelligence", "news", "trend"]],
  ["data", ["enrich", "spreadsheet", "csv", "airtable", "analytics", "dedup", "firmographic", "dataset"]],
  ["comms", ["slack", "email", "notify", "newsletter", "inbox", "message"]],
  ["product", ["github", "pull request", "repo", "feature", "roadmap", "deploy", "code"]],
  ["growth", ["seo", "marketing", "growth", "campaign", "ad ", "content", "social", "twitter", "reddit", "tiktok", "youtube", "blog"]],
];

// Compact form of a label for chips: first two substantive words. Connector
// words ("&", "and", "of", …) don't count toward the limit and are never left
// dangling at the end, so "SEO & Content" stays whole instead of truncating
// to "SEO &". The full label still shows on hover via the chip's title.
const CONNECTOR_WORD = /^(&|and|of|for|the)$/i;
export function shortSkillLabel(label: string): string {
  const out: string[] = [];
  let substantive = 0;
  for (const w of label.split(/\s+/)) {
    if (substantive >= 2) break;
    out.push(w);
    if (!CONNECTOR_WORD.test(w)) substantive++;
  }
  while (out.length > 0 && CONNECTOR_WORD.test(out[out.length - 1])) out.pop();
  return out.join(" ");
}

/** Best-effort domain for a free-text blob (skill name + description, or prompt). */
export function deriveDomain(text: string): SkillDomain {
  const t = text.toLowerCase();
  for (const [domain, keywords] of DOMAIN_KEYWORDS) {
    if (keywords.some((k) => t.includes(k))) return domain;
  }
  return "general";
}

// Curated catalog used to *infer* indicative capsules from prompt text. These
// don't need to match the live skill library 1:1 — they're reading aids on the
// cards. Order = priority when capping the chip count.
interface CatalogEntry {
  name: string;
  label: string;
  domain: SkillDomain;
  keywords: string[];
}

const SKILL_CATALOG: CatalogEntry[] = [
  { name: "linkedin-automation", label: "LinkedIn Automation", domain: "sales", keywords: ["linkedin", "connection request", "pending connection"] },
  { name: "crm-sync", label: "CRM Sync", domain: "sales", keywords: ["crm", "hubspot", "salesforce", "pipeline"] },
  { name: "email-outreach", label: "Email Outreach", domain: "sales", keywords: ["cold email", "outreach", "drip", "sequence", "inbox", "email sequence"] },
  { name: "lead-enrichment", label: "Lead Enrichment", domain: "data", keywords: ["enrich", "apollo", "clearbit", "zoominfo", "firmographic", "verified work email", "verified email"] },
  { name: "browser-automation", label: "Browser Automation", domain: "ops", keywords: ["google maps", "navigate", "scrape", "crawl", "browser", "website ui", "web ui"] },
  { name: "web-research", label: "Web Research", domain: "research", keywords: ["research", "monitor", "sources", "brief", "trending", "intelligence"] },
  { name: "spreadsheet", label: "Spreadsheet", domain: "data", keywords: ["spreadsheet", "google sheet", "csv", "airtable"] },
  { name: "slack-notify", label: "Slack", domain: "comms", keywords: ["slack"] },
  { name: "github", label: "GitHub", domain: "product", keywords: ["github", "pull request", "pr queue", "repo"] },
  { name: "finance-analysis", label: "Finance Analysis", domain: "finance", keywords: ["invoice", "expense", "cash-flow", "cashflow", "ledger", "reconcil", "10-k", "earnings"] },
  { name: "support-desk", label: "Support Desk", domain: "support", keywords: ["zendesk", "intercom", "ticket", "support intent", "nps"] },
  { name: "incident-ops", label: "Incident Ops", domain: "ops", keywords: ["pagerduty", "jira", "incident", "on-call", "alert"] },
  { name: "social-media", label: "Social Media", domain: "growth", keywords: ["twitter", "reddit", "tiktok", "instagram", "youtube", "quora"] },
  { name: "seo-content", label: "SEO & Content", domain: "growth", keywords: ["seo", "blog", "landing page", "newsletter", "glossary"] },
];

/** Infer up to `max` indicative skill capsules from a prompt's text. */
export function inferSkillCapsules(text: string, max = 3): SkillCapsule[] {
  const t = text.toLowerCase();
  const hits: SkillCapsule[] = [];
  for (const entry of SKILL_CATALOG) {
    if (entry.keywords.some((k) => t.includes(k))) {
      hits.push({ name: entry.name, label: entry.label, domain: entry.domain });
      if (hits.length >= max) break;
    }
  }
  return hits;
}

// --- <read_skill> inline references ----------------------------------------
//
// A prompt's hand-picked skills are referenced inline in its text as
// `<read_skill>skill-name</read_skill>` markers (and stored alongside as a
// structured `tags` list). The same marker is what `buildSteeredMessage`
// appends to a chat send so the agent reads (cats the SKILL.md) and follows
// the skill it should use.
//
// The marker was historically spelled `<use_skill>`; we now emit
// `<read_skill>` but the regexes match BOTH spellings so any prompt or
// message persisted with the old marker keeps parsing/stripping/rendering.
const SKILL_MARKER_RE = /<(?:use|read)_skill>[\s\S]*?<\/(?:use|read)_skill>/g;
const SKILL_MARKER_CAPTURE_RE = /<(?:use|read)_skill>([\s\S]*?)<\/(?:use|read)_skill>/g;

/** Test whether `content` contains at least one inline skill marker. */
export function hasUseSkillTags(content: string): boolean {
  return /<(?:use|read)_skill>/.test(content);
}

/** Render skill names as concatenated `<read_skill>name</read_skill>` markers. */
export function formatUseSkillTags(skillNames: string[]): string {
  return skillNames.map((n) => `<read_skill>${n}</read_skill>`).join("");
}

/** Remove any inline skill markers (and trailing space) from text. */
export function stripUseSkillTags(content: string): string {
  return content.replace(SKILL_MARKER_RE, "").replace(/\s+$/, "");
}

/** Pull the skill names out of a content string's inline markers. */
export function parseUseSkillTags(content: string): string[] {
  const out: string[] = [];
  for (const m of content.matchAll(SKILL_MARKER_CAPTURE_RE)) {
    const name = m[1].trim();
    if (name) out.push(name);
  }
  return out;
}

/** A run of plain text, or a single inline skill reference. */
export type SkillTextSegment =
  | { type: "text"; value: string }
  | { type: "skill"; name: string };

/**
 * Split text into ordered segments — plain-text runs and inline skill
 * references — so a renderer can draw `<read_skill>name</read_skill>` markers
 * as chips in place while keeping the surrounding prose intact. Matches both
 * the new `read_skill` and legacy `use_skill` spellings.
 */
export function splitSkillMarkers(text: string): SkillTextSegment[] {
  const segments: SkillTextSegment[] = [];
  // Fresh regex instance — exec() advances lastIndex, so don't share the
  // module-level one across calls.
  const re = /<(?:use|read)_skill>([\s\S]*?)<\/(?:use|read)_skill>/g;
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) segments.push({ type: "text", value: text.slice(last, m.index) });
    const name = m[1].trim();
    if (name) segments.push({ type: "skill", name });
    last = m.index + m[0].length;
  }
  if (last < text.length) segments.push({ type: "text", value: text.slice(last) });
  return segments;
}

/**
 * Append inline `<use_skill>` markers for `skillNames` to clean content.
 * Existing markers are stripped first so re-saving stays idempotent — the
 * skill picker is the single source of truth.
 */
export function embedUseSkillTags(content: string, skillNames: string[]): string {
  const clean = stripUseSkillTags(content);
  if (skillNames.length === 0) return clean;
  return `${clean} ${formatUseSkillTags(skillNames)}`;
}

/**
 * Build the outgoing message pair for a chat send. The LLM-visible `message`
 * carries inline `<use_skill>` markers naming the attached skills; the
 * `displayMessage` stays clean so the user's chat bubble shows only what they
 * typed.
 */
export function buildSteeredMessage(
  userText: string,
  capsules: SkillCapsule[],
): { message: string; displayMessage: string } {
  if (capsules.length === 0) {
    return { message: userText, displayMessage: userText };
  }
  const tags = formatUseSkillTags(capsules.map((c) => c.name));
  return { message: `${userText}\n\n${tags}`, displayMessage: userText };
}
