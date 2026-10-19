import type { LucideIcon } from "lucide-react";
import { Sparkles, BookOpen, Component, Database, MousePointerClick, CheckCircle2 } from "lucide-react";

export interface TutorialStep {
  /** Stable id for analytics + debugging. */
  id: string;
  /** Title shown in the step card. */
  title: string;
  /** 1–2 sentence body. Plain text — no markdown. */
  body: string;
  /** Lucide icon rendered in the card header. */
  icon: LucideIcon;
  /**
   * `data-tour` value on the element to spotlight. When null the overlay
   * shows a centered, full-screen modal (welcome + finale) — unless `demo`
   * is set, which renders a scripted colony mock instead.
   */
  target: string | null;
  /** Optional route to navigate to before measuring the target. */
  route?: string;
  /** Optional alignment hint for the card relative to the spotlighted element. */
  placement?: "auto" | "right" | "bottom" | "left" | "top";
  /**
   * When true this step renders the scripted colony split-view demo
   * (TutorialColonyDemo) as a full-screen backdrop instead of spotlighting a
   * real element. It's still a numbered content step, not a bookend.
   */
  demo?: boolean;
  /**
   * Which state of the scripted demo to render: the running plan ("plan",
   * default) or the Data tab filled with warm leads ("data"). Only read when
   * `demo` is true.
   */
  demoView?: "plan" | "data";
}

/**
 * The tour walks the outcome, not the org chart: pick a playbook → the
 * colony works it → warm leads land in the Data tab → connect the browser
 * to make it real. Welcome and finale are centered bookends; the two colony
 * steps render a scripted split-view demo.
 */
export const TUTORIAL_STEPS: TutorialStep[] = [
  {
    id: "welcome",
    title: "Welcome to Hive",
    body: "Hive Agents work in colonies. Let's build your first colony.",
    icon: Sparkles,
    target: null,
  },
  {
    id: "playbook",
    title: "Pick a playbook",
    body: "No blank page. Pick a proven playbook — Lead Generation, Outbound BDR — and Hive spins up a colony that runs it.",
    icon: BookOpen,
    target: "tour-playbook-card",
    route: "/",
    placement: "bottom",
  },
  {
    id: "colony-chat",
    title: "Your colony gets to work",
    body: "That's the whole setup. The playbook becomes the brief — your queen plans the mission and starts working it, like a teammate.",
    icon: Component,
    // `demo` fills the content pane with the scripted colony; the spotlight
    // then highlights the conversation half of it.
    target: "tour-demo-chat",
    demo: true,
    placement: "right",
  },
  {
    id: "colony-data",
    title: "Warm leads, ready to use",
    body: "Everything she finds lands in the Data tab — enriched, scored, export-ready. Warm leads stack up here as the colony works.",
    icon: Database,
    target: "tour-demo-panel",
    demo: true,
    demoView: "data",
    placement: "left",
  },
  {
    // A centered explainer (no spotlight target): a screenshot of an agent
    // driving the browser + an "install the extension" secondary CTA. The
    // custom content is rendered by the `step.id === "browser"` branch in
    // TutorialOverlay (mirrors the "done" step's DoneCta).
    id: "browser",
    title: "Your agents can run the browser",
    body: "Hive agents take over your browser chores. Connect the browser extension and a queen can browse and engage for you, they're especially good at lead gen on social platforms like LinkedIn. ",
    icon: MousePointerClick,
    target: null,
    // Keep the scripted colony backdrop (from the demo steps) behind the
    // centered card instead of revealing the real home page underneath.
    demo: true,
    demoView: "data",
  },
  {
    id: "done",
    title: "You're ready",
    // The done step is the only one rendered as a centered bookend with
    // a custom CTA (book an onboarding session with Vincent). See the
    // ``DoneCta`` branch in TutorialOverlay.tsx.
    body: "Want a hand getting set up? Book a 1:1 onboarding session - we'll wire your queens to your tools and deliver your use case in 15 minutes.",
    icon: CheckCircle2,
    target: null,
  },
];
