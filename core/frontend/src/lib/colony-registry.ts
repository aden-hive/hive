import type { LucideIcon } from "lucide-react";
import {
  Mail,
  Shield,
  Briefcase,
  Globe,
  DollarSign,
  Calculator,
  Search,
  Newspaper,
  Radar,
  Reply,
  MapPin,
  Calendar,
  UserPlus,
  Twitter,
  Hexagon,
} from "lucide-react";

/** Agent slug → queen persona mapping. */
export const QUEEN_REGISTRY: Record<
  string,
  { name: string; role: string }
> = {
  email_inbox_management: { name: "Mary", role: "Inbox Coordinator" },
  vulnerability_assessment: { name: "Liz", role: "Security Analyst" },
  job_hunter: { name: "Catherine", role: "Recruiter" },
  reddit_engagement: { name: "Cleopatra", role: "Growth Lead" },
  sales_pipeline: { name: "Victoria", role: "Finance Ops" },
  finance_controller: { name: "Diana", role: "DevOps Commander" },
  deep_research_agent: { name: "Athena", role: "Research Lead" },
  tech_news_reporter: { name: "Elena", role: "News Editor" },
  competitive_intel_agent: { name: "Sophia", role: "Intel Analyst" },
  email_reply_agent: { name: "Grace", role: "Reply Manager" },
  hubspot_revenue_leak_detector: { name: "Freya", role: "Revenue Analyst" },
  local_business_extractor: { name: "Ivy", role: "Data Miner" },
  meeting_scheduler: { name: "Nora", role: "Schedule Manager" },
  sdr_agent: { name: "Pearl", role: "SDR Lead" },
  twitter_news_agent: { name: "Ruby", role: "Social Manager" },
};

/** Agent slug → icon mapping */
export const COLONY_ICONS: Record<string, LucideIcon> = {
  email_inbox_management: Mail,
  job_hunter: Briefcase,
  vulnerability_assessment: Shield,
  deep_research_agent: Search,
  tech_news_reporter: Newspaper,
  competitive_intel_agent: Radar,
  email_reply_agent: Reply,
  hubspot_revenue_leak_detector: DollarSign,
  local_business_extractor: MapPin,
  meeting_scheduler: Calendar,
  sdr_agent: UserPlus,
  twitter_news_agent: Twitter,
  reddit_engagement: Globe,
  sales_pipeline: DollarSign,
  finance_controller: Calculator,
};

/** Agent slug → color mapping */
export const COLONY_COLORS: Record<string, string> = {
  email_inbox_management: "hsl(38,80%,55%)",
  job_hunter: "hsl(30,85%,58%)",
  vulnerability_assessment: "hsl(15,70%,52%)",
  deep_research_agent: "hsl(210,70%,55%)",
  tech_news_reporter: "hsl(270,60%,55%)",
  competitive_intel_agent: "hsl(190,70%,45%)",
  email_reply_agent: "hsl(45,80%,55%)",
  hubspot_revenue_leak_detector: "hsl(145,60%,42%)",
  local_business_extractor: "hsl(350,65%,55%)",
  meeting_scheduler: "hsl(220,65%,55%)",
  sdr_agent: "hsl(165,55%,45%)",
  twitter_news_agent: "hsl(200,85%,55%)",
  reddit_engagement: "hsl(15,90%,55%)",
  sales_pipeline: "hsl(145,60%,42%)",
  finance_controller: "hsl(38,75%,50%)",
};

/** Convert agent path to slug: "exports/email_inbox_management" → "email_inbox_management".
 *  Splits on both POSIX "/" and Windows "\" separators — on Windows the colony
 *  path arrives back-slashed (e.g. "...\colonies\credential-test"), and a
 *  "/"-only split would return the whole path as the slug (breaking colony ids,
 *  route hrefs, and unread-count storage keys). */
export function agentSlug(path: string): string {
  return path.replace(/[/\\]+$/, "").split(/[/\\]/).pop() || path;
}

/** Convert slug to display name: "email_inbox_management" → "inbox-management" (colony style) */
export function slugToColonyId(slug: string): string {
  return slug
    .replace(/_/g, "-")
    .replace(/^email-/, "")
    .replace(/-agent$/, "");
}

/** Convert slug to human-readable name: "email_inbox_management" → "Inbox Management" */
/** Explicit display names for colonies whose slug doesn't title-case nicely —
 *  acronyms (ICP) or a brand name that differs from the on-disk directory. The
 *  runtime's discovery title-cases the slug, so this override wins in the
 *  renderer (see ColonyContext). */
export const COLONY_DISPLAY_NAME_OVERRIDES: Record<string, string> = {
  // The starter/demo colony's slug is `icp_outreach`; title-casing would render
  // "Icp Outreach", so brand the acronym properly.
  icp_outreach: "ICP Outreach",
};

export function slugToDisplayName(slug: string): string {
  const override = COLONY_DISPLAY_NAME_OVERRIDES[slug];
  if (override) return override;
  return slug
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

/** Get queen info for an agent slug, with fallback */
export function getQueenForAgent(slug: string): { name: string; role: string } {
  return QUEEN_REGISTRY[slug] || { name: "Queen", role: "Agent Manager" };
}

/** Get icon for an agent slug, with fallback */
export function getColonyIcon(slug: string): LucideIcon {
  return COLONY_ICONS[slug] || Hexagon;
}

/** Get color for an agent slug, with fallback */
export function getColonyColor(slug: string): string {
  return COLONY_COLORS[slug] || "hsl(45,95%,58%)";
}

/** Fixed display order for queen profiles. GTM team leads, then the rest. */
export const QUEEN_DISPLAY_ORDER: string[] = [
  // GTM & core team display order — Growth leads
  "queen_growth",
  "queen_sales",
  "queen_market_research",
  "queen_content_creation",
  "queen_lead_gen",
  "queen_outbound",
  "queen_brand_design",
  "queen_operations",
  // Remaining catalog queens
  "queen_technology",
  "queen_finance_fundraising",
  "queen_talent",
  "queen_product_strategy",
  "queen_legal",
];

/**
 * Queens active by default for a brand-new user (the GTM core team).
 * Used as the fallback active set when the user has no queen preferences yet
 * — e.g. they skipped or abandoned onboarding, so the signup site never wrote
 * the decommissioned seed. Mirrors the signup site's QUEEN_FUNCTIONS. Keep in
 * sync with NON_DEFAULT_QUEEN_IDS over there.
 */
export const DEFAULT_ACTIVE_QUEEN_IDS: string[] = [
  "queen_growth",
  // Head of RevOps (id `queen_sales`) owns the CRM — see CRM_SETUP_QUEEN_ID — so
  // she has to be on the starting team: the setup door routes into her DM, and a
  // decommissioned queen can't host a conversation.
  "queen_sales",
  "queen_content_creation",
  "queen_lead_gen",
  "queen_outbound",
  "queen_brand_design",
];

/**
 * Catalog queens hidden by default for a brand-new user. The exact complement
 * of {@link DEFAULT_ACTIVE_QUEEN_IDS} within the catalog. Written as an
 * explicit decommissioned seed the first time such a user toggles any queen,
 * so the implicit default survives later per-queen edits.
 */
export const DEFAULT_HIDDEN_QUEEN_IDS: string[] = [
  "queen_market_research",
  "queen_technology",
  "queen_product_strategy",
  "queen_finance_fundraising",
  "queen_legal",
  "queen_talent",
  "queen_operations",
];

/**
 * Canonical queen ordering used on every surface (sidebar, org chart,
 * colony picker, libraries) so the order is consistent app-wide.
 *
 * Priority:
 *   1. The user's configured order — `preferences.queens` keys, in the order
 *      they were set during onboarding. Pass these as `preferredIds`.
 *   2. The default-active GTM order (`DEFAULT_ACTIVE_QUEEN_IDS`) — covers
 *      active queens the user never explicitly configured (e.g. skipped
 *      onboarding, or re-hired from the org chart).
 *   3. The remaining catalog order (`QUEEN_DISPLAY_ORDER`).
 *   4. Anything unknown, last (stable among themselves).
 *
 * Recency/activity is deliberately NOT part of the baseline — the order stays
 * stable so a new user sees exactly the team they configured. Surface activity
 * with badges, or a separate "Recent" section, instead of reordering here.
 */
export function orderQueens<T extends { id: string }>(
  profiles: T[],
  preferredIds: string[] = [],
): T[] {
  const rank = (id: string): number => {
    const p = preferredIds.indexOf(id);
    if (p !== -1) return p;
    const a = DEFAULT_ACTIVE_QUEEN_IDS.indexOf(id);
    if (a !== -1) return 1_000 + a;
    const d = QUEEN_DISPLAY_ORDER.indexOf(id);
    if (d !== -1) return 2_000 + d;
    return 3_000;
  };
  // Array.prototype.sort is stable (V8), so equal-rank items keep input order.
  return [...profiles].sort((a, b) => rank(a.id) - rank(b.id));
}

/**
 * Back-compat wrapper — fixed catalog order with no per-user preferences.
 * Prefer {@link orderQueens} with `preferredIds` so the user's configured
 * order wins.
 */
export function sortQueenProfiles<T extends { id: string }>(profiles: T[]): T[] {
  return orderQueens(profiles);
}

