/**
 * Live Mermaid renderer for the chat bubble.
 *
 * Renders a mermaid source string to an inline SVG. Mermaid is
 * lazy-loaded so non-diagram messages don't pay the ~600 KB cost.
 *
 * Theme follows the OpenHive light/dark setting. Errors render a
 * tiny pill so the agent gets feedback for the next turn.
 */

import { useEffect, useRef, useState } from "react";
import { AlertCircle } from "lucide-react";

interface Props {
  source: string;
  theme?: "light" | "dark";
}

let _mermaidInitialized = false;

export default function MermaidBlock({ source, theme = "light" }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let disposed = false;

    (async () => {
      try {
        const mermaid = (await import("mermaid")).default;
        if (!_mermaidInitialized) {
          mermaid.initialize({
            startOnLoad: false,
            theme: theme === "dark" ? "dark" : "default",
            securityLevel: "loose",
            fontFamily:
              "'Inter Tight', -apple-system, BlinkMacSystemFont, system-ui, sans-serif",
          });
          _mermaidInitialized = true;
        }
        if (disposed || !ref.current) return;

        // Unique id per render to avoid conflicting injected styles.
        const id = `mmd-${Math.random().toString(36).slice(2, 10)}`;
        const { svg } = await mermaid.render(id, source);
        if (disposed || !ref.current) return;
        ref.current.innerHTML = svg;
      } catch (e) {
        if (!disposed) {
          setError(e instanceof Error ? e.message : String(e));
        }
      }
    })();

    return () => {
      disposed = true;
    };
  }, [source, theme]);

  if (error) {
    return (
      <div
        className="flex items-center gap-2 text-[11px] text-muted-foreground px-2.5 py-1.5 rounded-md border border-border/40 bg-muted/30"
        role="alert"
      >
        <AlertCircle className="w-3 h-3 shrink-0" />
        <span>diagram syntax invalid: {error}</span>
      </div>
    );
  }

  return (
    <div
      ref={ref}
      // Match EChartsBlock: transparent so the diagram blends with the
      // chat bubble; rounded corners and inner padding give breathing
      // room without adding a visible card.
      className="w-full overflow-x-auto rounded-lg bg-transparent p-4 [&_svg]:max-w-full [&_svg]:h-auto [&_svg]:mx-auto"
    />
  );
}
