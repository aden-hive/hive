import { useCallback, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { ArrowRight, ArrowLeft, Calendar, X } from "lucide-react";

/** Solid LinkedIn brand mark — Lucide's Linkedin is outline-only. */
function LinkedinSolid({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="currentColor"
      aria-hidden
      className={className}
    >
      <path d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433a2.062 2.062 0 01-2.063-2.065 2.063 2.063 0 112.063 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z" />
    </svg>
  );
}
import { TutorialContext, useTutorialState } from "./useTutorial";
import type { TutorialStep } from "./steps";
import TutorialColonyDemo from "./TutorialColonyDemo";
import vincentAvatar from "@/assets/vincent.jpeg";
import browserPreview from "@/assets/browser_extension_preview.png";
import { BROWSER_EXT_STORE_URL } from "@/components/BrowserStatusBadge";

// Onboarding-session CTA on the final "You're ready" step.
const ONBOARDING_CALENDLY_URL = "https://calendly.com/contact_aden/openhive";
const HOST_LINKEDIN_URL = "https://www.linkedin.com/in/vincentjiangx/";
const HOST_NAME = "Vincent Jiang";
const HOST_TITLE = "Founder";
const HOST_INITIALS = "VJ";
const HOST_AVATAR_SRC: string | null = vincentAvatar;

/** OpenHive honeycomb mark used on the bookend (welcome + done) cards. */
function HiveMark({ size = 28 }: { size?: number }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 64 64"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.2"
      strokeLinejoin="round"
      width={size}
      height={size}
      className="text-primary"
    >
      <g transform="translate(32,32) scale(1.15) translate(-32,-32)">
        <polygon points="20,14 25.2,17 25.2,23 20,26 14.8,23 14.8,17" />
        <polygon points="32,7 37.2,10 37.2,16 32,19 26.8,16 26.8,10" />
        <polygon points="44,14 49.2,17 49.2,23 44,26 38.8,23 38.8,17" />
        <polygon points="44,28 49.2,31 49.2,37 44,40 38.8,37 38.8,31" />
        <polygon points="32,35 37.2,38 37.2,44 32,47 26.8,44 26.8,38" />
        <polygon points="20,28 25.2,31 25.2,37 20,40 14.8,37 14.8,31" />
        <polygon points="32,21 37.2,24 37.2,30 32,33 26.8,30 26.8,24" />
      </g>
    </svg>
  );
}

/**
 * Onboarding-session card rendered inside the final "You're ready" step.
 * Shows the host's avatar + name and a primary CTA that opens the
 * Calendly link in the user's default browser via Electron's
 * shell.openExternal (so the booking flow doesn't get trapped inside
 * the app window).
 */
function DoneCta() {
  return (
    <div className="mt-3 -mx-1 px-3 py-3 rounded-lg border border-primary/25 bg-primary/[0.04]">
      <div className="flex items-center gap-2.5 mb-2.5">
        <div className="w-9 h-9 rounded-full bg-primary/15 flex items-center justify-center overflow-hidden flex-shrink-0">
          {HOST_AVATAR_SRC ? (
            <img
              src={HOST_AVATAR_SRC}
              alt={HOST_NAME}
              className="w-full h-full object-cover"
            />
          ) : (
            <span className="text-[11px] font-bold text-primary">
              {HOST_INITIALS}
            </span>
          )}
        </div>
        <div className="min-w-0">
          <p className="text-[12px] font-semibold text-foreground leading-tight">
            {HOST_NAME}
          </p>
          <p className="text-[10.5px] text-muted-foreground leading-tight mt-0.5 flex items-center gap-1">
            {HOST_TITLE}
            <button
              onClick={() => window.open(HOST_LINKEDIN_URL, "_blank", "noopener")}
              title="LinkedIn"
              aria-label="Open LinkedIn profile"
              className="text-muted-foreground/60 hover:text-[#0A66C2] transition-colors"
            >
              <LinkedinSolid className="w-2.5 h-2.5" />
            </button>
          </p>
        </div>
      </div>
      <button
        onClick={() => window.open(ONBOARDING_CALENDLY_URL, "_blank", "noopener")}
        className="w-full inline-flex items-center justify-center gap-1.5 text-[11.5px] font-medium bg-primary text-primary-foreground hover:bg-primary/90 px-3 py-1.5 rounded-md transition-colors"
      >
        <Calendar className="w-3 h-3" />
        Book onboarding session
      </button>
    </div>
  );
}

/** Full-color Chrome logo (Lucide's Chrome is a monochrome outline). Gradient
 *  ids are namespaced so they can't collide with other inline SVGs. */
function ChromeLogo({ className }: { className?: string }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 48 48"
      className={className}
      aria-hidden
    >
      <defs>
        <linearGradient id="chrome-a" x1="3.2173" y1="15" x2="44.7812" y2="15" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="#d93025" />
          <stop offset="1" stopColor="#ea4335" />
        </linearGradient>
        <linearGradient id="chrome-b" x1="20.7219" y1="47.6791" x2="41.5039" y2="11.6837" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="#fcc934" />
          <stop offset="1" stopColor="#fbbc04" />
        </linearGradient>
        <linearGradient id="chrome-c" x1="26.5981" y1="46.5015" x2="5.8161" y2="10.506" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="#1e8e3e" />
          <stop offset="1" stopColor="#34a853" />
        </linearGradient>
      </defs>
      <circle cx="24" cy="23.9947" r="12" style={{ fill: "#fff" }} />
      <path d="M24,12H44.7812a23.9939,23.9939,0,0,0-41.5639.0029L13.6079,30l.0093-.0024A11.9852,11.9852,0,0,1,24,12Z" style={{ fill: "url(#chrome-a)" }} />
      <circle cx="24" cy="24" r="9.5" style={{ fill: "#1a73e8" }} />
      <path d="M34.3913,30.0029,24.0007,48A23.994,23.994,0,0,0,44.78,12.0031H23.9989l-.0025.0093A11.985,11.985,0,0,1,34.3913,30.0029Z" style={{ fill: "url(#chrome-b)" }} />
      <path d="M13.6086,30.0031,3.218,12.006A23.994,23.994,0,0,0,24.0025,48L34.3931,30.0029l-.0067-.0068a11.9852,11.9852,0,0,1-20.7778.007Z" style={{ fill: "url(#chrome-c)" }} />
    </svg>
  );
}

/**
 * Screenshot preview + "install extension" CTA for the browser step. New users
 * don't have the bridge connected yet, so we show a still of an agent driving
 * the browser and offer a secondary link to the Chrome Web Store listing. The
 * primary "Next" button (tour footer) still advances the tour as usual.
 */
function BrowserPreviewCta() {
  return (
    <div className="mt-3">
      <img
        src={browserPreview}
        alt="A Hive agent driving the browser to find and engage leads on LinkedIn"
        className="w-full rounded-lg border border-border/60"
      />
      <button
        onClick={() => window.open(BROWSER_EXT_STORE_URL, "_blank", "noopener")}
        className="mt-3 w-full inline-flex items-center justify-center gap-2 text-[11.5px] font-medium text-foreground bg-muted/50 hover:bg-muted border border-border/60 hover:border-border px-3 py-2 rounded-lg transition-colors"
      >
        <ChromeLogo className="w-3.5 h-3.5" />
        Install the browser extension now
      </button>
    </div>
  );
}

interface Rect {
  top: number;
  left: number;
  width: number;
  height: number;
}

/**
 * Find the spotlight target by data-tour attribute. Returns null until the
 * element appears in the DOM — handy on steps that navigate to a new page.
 */
function useTargetRect(target: string | null, navTick: number): Rect | null {
  const [rect, setRect] = useState<Rect | null>(null);

  useLayoutEffect(() => {
    if (!target) {
      setRect(null);
      return;
    }
    let cancelled = false;
    let frame = 0;
    let observer: ResizeObserver | null = null;
    let observedEl: HTMLElement | null = null;

    const measure = () => {
      const el = document.querySelector<HTMLElement>(`[data-tour="${target}"]`);
      if (!el) {
        if (!cancelled) frame = window.requestAnimationFrame(measure);
        return;
      }
      const r = el.getBoundingClientRect();
      // Pad the spotlight so the rounded mask doesn't clip the element's hover ring.
      // Bail on identical rects so ResizeObserver-driven re-measures don't loop.
      setRect((prev) => {
        const next = {
          top: r.top - 8,
          left: r.left - 8,
          width: r.width + 16,
          height: r.height + 16,
        };
        return prev &&
          prev.top === next.top &&
          prev.left === next.left &&
          prev.width === next.width &&
          prev.height === next.height
          ? prev
          : next;
      });
      // Targets can grow after first paint (cards whose content renders
      // async), shift when surrounding layout settles, or be remounted by a
      // list re-render — keep the spotlight glued by re-measuring on
      // target/body size changes, re-attaching if the matched node changed.
      if (el !== observedEl) {
        observer?.disconnect();
        observer = new ResizeObserver(measure);
        observer.observe(el);
        observer.observe(document.body);
        observedEl = el;
      }
    };

    frame = window.requestAnimationFrame(measure);

    const onResize = () => measure();
    window.addEventListener("resize", onResize);
    window.addEventListener("scroll", onResize, true);

    return () => {
      cancelled = true;
      window.cancelAnimationFrame(frame);
      observer?.disconnect();
      window.removeEventListener("resize", onResize);
      window.removeEventListener("scroll", onResize, true);
    };
  }, [target, navTick]);

  return rect;
}

/** Position the step card so it never clips off-screen. */
function cardStyle(
  rect: Rect | null,
  placement: TutorialStep["placement"],
  cardW = 360,
  cardH = 200,
): React.CSSProperties {
  const margin = 16;
  const vw = typeof window !== "undefined" ? window.innerWidth : 1280;
  const vh = typeof window !== "undefined" ? window.innerHeight : 800;

  if (!rect) {
    return {
      top: `calc(50% - ${cardH / 2}px)`,
      left: `calc(50% - ${cardW / 2}px)`,
      width: cardW,
    };
  }

  const tryPlace = (p: NonNullable<TutorialStep["placement"]>) => {
    if (p === "right") return { top: rect.top, left: rect.left + rect.width + margin };
    if (p === "left") return { top: rect.top, left: rect.left - cardW - margin };
    if (p === "bottom") return { top: rect.top + rect.height + margin, left: rect.left };
    if (p === "top") return { top: rect.top - cardH - margin, left: rect.left };
    return { top: rect.top, left: rect.left + rect.width + margin };
  };

  const order: NonNullable<TutorialStep["placement"]>[] =
    placement && placement !== "auto"
      ? [placement, "right", "bottom", "left", "top"]
      : ["right", "bottom", "left", "top"];

  for (const p of order) {
    const pos = tryPlace(p);
    if (pos.top >= margin && pos.left >= margin && pos.top + cardH + margin <= vh && pos.left + cardW + margin <= vw) {
      return { ...pos, width: cardW };
    }
  }

  return {
    top: Math.min(Math.max(margin, rect.top), vh - cardH - margin),
    left: Math.min(Math.max(margin, rect.left + rect.width + margin), vw - cardW - margin),
    width: cardW,
  };
}

/** SVG mask that dims the page but cuts out the spotlight rectangle. */
function SpotlightMask({ rect }: { rect: Rect | null }) {
  if (!rect) {
    return <div className="absolute inset-0 bg-black/55 pointer-events-auto" />;
  }
  return (
    <svg className="absolute inset-0 w-full h-full pointer-events-auto" aria-hidden>
      <defs>
        <mask id="tour-spot">
          <rect width="100%" height="100%" fill="white" />
          <rect
            x={rect.left}
            y={rect.top}
            width={rect.width}
            height={rect.height}
            rx={14}
            ry={14}
            fill="black"
          />
        </mask>
        <filter id="tour-glow" x="-20%" y="-20%" width="140%" height="140%">
          <feGaussianBlur stdDeviation="6" result="b" />
          <feMerge>
            <feMergeNode in="b" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>
      <rect width="100%" height="100%" fill="rgba(0,0,0,0.55)" mask="url(#tour-spot)" />
      <rect
        x={rect.left}
        y={rect.top}
        width={rect.width}
        height={rect.height}
        rx={14}
        ry={14}
        fill="none"
        stroke="hsl(var(--primary))"
        strokeOpacity="0.9"
        strokeWidth="2"
        filter="url(#tour-glow)"
      />
    </svg>
  );
}

/**
 * Bookends (welcome + finale) render as centered "OpenHive" modals with no step
 * number. Identified by id — other targetless steps (the `demo` steps, and the
 * centered "browser" screenshot step) are still numbered content steps.
 */
function isBookendStep(s: TutorialStep): boolean {
  return s.id === "welcome" || s.id === "done";
}

function StepCard({
  step,
  steps,
  index,
  total,
  rect,
  onPrev,
  onNext,
  onFinish,
  onComplete,
}: {
  step: TutorialStep;
  steps: TutorialStep[];
  index: number;
  total: number;
  rect: Rect | null;
  onPrev: () => void;
  onNext: () => void;
  /** Closes the tour without navigation. Wired to the X button and ESC. */
  onFinish: () => void;
  /** "Done with the tour" — closes AND navigates to the new-chat home so
   *  users land somewhere they can immediately act. Wired to the Finish
   *  button on the last step only. */
  onComplete: () => void;
}) {
  const Icon = step.icon;
  const isFirst = index === 0;
  const isLast = index === total - 1;
  const isBookend = isBookendStep(step);

  // Count position among content (non-bookend) steps only, so the label is
  // correct regardless of how many bookends are present — the finale is
  // dropped for India timezones.
  const contentSteps = steps.filter((s) => !isBookendStep(s));
  const stepCount = contentSteps.length;
  const stepNumber = contentSteps.indexOf(step) + 1;

  // The browser step is a wide, centered screenshot card — give it a bigger
  // footprint so the preview image reads clearly.
  const isBrowser = step.id === "browser";
  const style = cardStyle(
    rect,
    step.placement,
    isBrowser ? 640 : 360,
    isBrowser ? 580 : 200,
  );

  return (
    <div
      className="absolute z-10 bg-card border border-border/60 rounded-xl shadow-2xl p-5 pointer-events-auto animate-in fade-in zoom-in-95 duration-200"
      style={style}
    >
      <button
        onClick={onFinish}
        className="absolute top-3 right-3 p-1 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
        title="Skip tour"
        aria-label="Skip tour"
      >
        <X className="w-3.5 h-3.5" />
      </button>

      <div className="flex items-center gap-2.5 mb-2.5">
        {isBookend ? (
          <HiveMark size={24} />
        ) : (
          <div className="w-7 h-7 rounded-lg bg-primary/12 flex items-center justify-center">
            <Icon className="w-3.5 h-3.5 text-primary" />
          </div>
        )}
        <span className="text-[10px] font-semibold text-muted-foreground/70 uppercase tracking-[0.14em]">
          {isBookend ? "OpenHive" : `Step ${stepNumber} of ${stepCount}`}
        </span>
      </div>

      <h3 className="text-[15px] font-semibold text-foreground mb-1.5 leading-snug">
        {step.title}
      </h3>
      <p className="text-[12.5px] text-muted-foreground leading-relaxed">
        {step.body}
      </p>

      {step.id === "done" && <DoneCta />}
      {step.id === "browser" && <BrowserPreviewCta />}

      <div className="flex items-center justify-between mt-4 pt-3 border-t border-border/40">
        <div className="flex items-center gap-1.5">
          {Array.from({ length: total }).map((_, i) => (
            <span
              key={i}
              className={`h-1 rounded-full transition-all ${
                i === index ? "bg-primary w-5" : "bg-muted-foreground/25 w-1.5"
              }`}
              aria-hidden
            />
          ))}
        </div>
        <div className="flex items-center gap-1.5">
          {!isFirst && (
            <button
              onClick={onPrev}
              className="inline-flex items-center gap-1 text-[11px] font-medium text-muted-foreground hover:text-foreground px-2 py-1 rounded-md hover:bg-muted/40 transition-colors"
            >
              <ArrowLeft className="w-3 h-3" />
              Back
            </button>
          )}
          <button
            onClick={isLast ? onComplete : onNext}
            className="inline-flex items-center gap-1.5 text-[12px] font-medium bg-primary text-primary-foreground hover:bg-primary/90 px-3 py-1.5 rounded-md transition-colors"
          >
            {isLast ? "Finish" : isFirst ? "Begin" : "Next"}
            {!isLast && <ArrowRight className="w-3 h-3" />}
          </button>
        </div>
      </div>
    </div>
  );
}

/**
 * Top-level wrapper. Mounted once high in the tree so the context covers
 * every page — required so the SettingsModal can call `start()` to replay
 * the tour from anywhere.
 */
export function TutorialProvider({ children }: { children: ReactNode }) {
  const state = useTutorialState();
  const { active, index, steps, next, prev, finish } = state;
  const step = steps[index];

  const navigate = useNavigate();
  const location = useLocation();
  const [navTick, setNavTick] = useState(0);
  const lastIndexRef = useRef(-1);

  const resolvedRoute = step?.route;

  // Side-effect: when entering a step that pins a route, navigate there if
  // we're not already on it. Only fires on index/active edges, so the user
  // can wander mid-step without being yanked back.
  useEffect(() => {
    if (!active) {
      lastIndexRef.current = -1;
      return;
    }
    if (lastIndexRef.current === index) return;
    lastIndexRef.current = index;
    if (resolvedRoute && location.pathname !== resolvedRoute) {
      navigate(resolvedRoute);
    }
    setNavTick((t) => t + 1);
  }, [active, index, resolvedRoute, location.pathname, navigate]);

  const rect = useTargetRect(step?.target ?? null, navTick);
  // Demo steps render the scripted colony into the real content pane, then
  // spotlight one of its regions (chat / panel) with the standard mask. We
  // measure the content pane separately so the demo fills it regardless of
  // which region the current step highlights.
  const demoRect = useTargetRect(step?.demo ? "tour-colony-canvas" : null, navTick);

  // Landing target after a completed tour: the new-chat home page, so the
  // user can immediately start a conversation instead of being stranded on
  // whatever spotlight page the last step happened to live on.
  const complete = useCallback(() => {
    finish();
    navigate("/");
  }, [finish, navigate]);

  // Keyboard nav: Esc skips, arrows step, Enter advances.
  useEffect(() => {
    if (!active) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        finish();
      } else if (e.key === "ArrowRight" || e.key === "Enter") {
        e.preventDefault();
        next();
      } else if (e.key === "ArrowLeft") {
        e.preventDefault();
        prev();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [active, next, prev, finish]);

  return (
    <TutorialContext.Provider value={state}>
      {children}
      {active && step && (
        <div className="fixed inset-0 z-[60] pointer-events-none" role="dialog" aria-modal="true">
          {step.demo && demoRect && (
            // Base layer: the scripted colony, filling the real content pane.
            // The SpotlightMask below dims it and cuts the highlighted region,
            // exactly like every other step spotlights a real element.
            <div
              className="absolute pointer-events-none overflow-hidden"
              style={{
                top: demoRect.top,
                left: demoRect.left,
                width: demoRect.width,
                height: demoRect.height,
              }}
            >
              <TutorialColonyDemo view={step.demoView ?? "plan"} />
            </div>
          )}
          <SpotlightMask rect={rect} />
          <StepCard
            step={step}
            steps={steps}
            index={index}
            total={steps.length}
            rect={rect}
            onPrev={prev}
            onNext={next}
            onFinish={finish}
            onComplete={complete}
          />
        </div>
      )}
    </TutorialContext.Provider>
  );
}

export { useTutorial } from "./useTutorial";
