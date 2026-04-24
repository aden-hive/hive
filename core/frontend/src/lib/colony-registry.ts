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
import type { Template } from "@/types/colony";

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

/** Convert agent path to slug: "exports/email_inbox_management" → "email_inbox_management" */
export function agentSlug(path: string): string {
  return path.replace(/\/$/, "").split("/").pop() || path;
}

/** Convert slug to display name: "email_inbox_management" → "inbox-management" (colony style) */
export function slugToColonyId(slug: string): string {
  return slug
    .replace(/_/g, "-")
    .replace(/^email-/, "")
    .replace(/-agent$/, "");
}

/** Convert slug to human-readable name: "email_inbox_management" → "Inbox Management" */
export function slugToDisplayName(slug: string): string {
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

/** Fixed display order for queen profiles */
export const QUEEN_DISPLAY_ORDER: string[] = [
  "queen_technology",
  "queen_operations",
  "queen_growth",
  "queen_finance_fundraising",
  "queen_talent",
  "queen_product_strategy",
  "queen_brand_design",
  "queen_legal",
];

/** Sort queen profiles by fixed display order */
export function sortQueenProfiles<T extends { id: string }>(profiles: T[]): T[] {
  return [...profiles].sort((a, b) => {
    const ia = QUEEN_DISPLAY_ORDER.indexOf(a.id);
    const ib = QUEEN_DISPLAY_ORDER.indexOf(b.id);
    return (ia === -1 ? 999 : ia) - (ib === -1 ? 999 : ib);
  });
}

/** Pre-defined templates for the home page */
export const TEMPLATES: Template[] = [
  {
    id: "reddit-engagement",
    title: "Reddit Engagement Bot",
    description:
      "Monitor subreddits and auto-draft contextual replies that mention your...",
    category: "Marketing & Growth",
    icon: "Globe",
    agentPath: "examples/reddit_engagement",
  },
  {
    id: "competitive-intel",
    title: "Competitive Intelligence",
    description:
      "Track HackerNews & Product Hunt for competitors and auto-generate comparis...",
    category: "Operations & Analytics",
    icon: "Search",
    agentPath: "examples/competitive_intel_agent",
  },
  {
    id: "outbound-sales",
    title: "Outbound Sales Pipeline",
    description:
      "Enrich target accounts, generate personalized scripts, and automate...",
    category: "Sales & Biz Dev",
    icon: "MessageSquare",
    agentPath: "examples/sdr_agent",
  },
  {
    id: "devops-incident",
    title: "DevOps Incident Commander",
    description:
      "Auto-triage P1 alerts, create Slack war rooms, and pull relevant runbooks instantly.",
    category: "Engineering & DevOps",
    icon: "Terminal",
    agentPath: "examples/devops_incident",
  },
];
