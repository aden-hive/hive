/**
 * SlashCommandMenu — floating command palette triggered by "/" in home page input.
 *
 * Rendered via a React portal so it is never clipped by overflow containers.
 * Positioned above the anchor textarea using getBoundingClientRect().
 */

import { useEffect, useCallback } from "react";
import ReactDOM from "react-dom";
import { History } from "lucide-react";

export interface SlashCommand {
  id: string;
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  description: string;
}

export const SLASH_COMMANDS: SlashCommand[] = [
  {
    id: "resume",
    icon: History,
    label: "/resume",
    description: "Continue a previous session",
  },
];

interface SlashCommandMenuProps {
  /** Text typed after the "/" — used to filter commands. */
  query: string;
  /** Textarea element this menu is anchored to. */
  anchorEl: HTMLTextAreaElement | null;
  /** Currently highlighted row index. */
  activeIndex: number;
  /** Called when a command is confirmed (click or Enter). */
  onSelect: (command: SlashCommand) => void;
  /** Called when the menu should dismiss. */
  onClose: () => void;
}

export default function SlashCommandMenu({
  query,
  anchorEl,
  activeIndex,
  onSelect,
  onClose,
}: SlashCommandMenuProps) {
  const filtered = SLASH_COMMANDS.filter((c) =>
    c.id.startsWith(query.toLowerCase())
  );

  // Auto-close if nothing matches the current query
  useEffect(() => {
    if (filtered.length === 0) onClose();
  }, [filtered.length, onClose]);

  // Close on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (anchorEl && anchorEl.contains(e.target as Node)) return;
      onClose();
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [anchorEl, onClose]);

  const handleSelect = useCallback(
    (cmd: SlashCommand) => {
      onSelect(cmd);
    },
    [onSelect]
  );

  if (!anchorEl || filtered.length === 0) return null;

  const rect = anchorEl.getBoundingClientRect();
  const style: React.CSSProperties = {
    position: "fixed",
    left: rect.left,
    bottom: window.innerHeight - rect.top + 8,
    width: rect.width,
    zIndex: 9999,
  };

  return ReactDOM.createPortal(
    <div
      style={style}
      role="listbox"
      aria-label="Slash commands"
      className="rounded-xl border border-border/60 bg-card shadow-2xl shadow-black/30 overflow-hidden"
    >
      <div className="px-3 py-2 border-b border-border/20">
        <p className="text-[10px] font-semibold text-muted-foreground/50 uppercase tracking-wider">
          Commands
        </p>
      </div>
      {filtered.map((cmd, i) => (
        <button
          key={cmd.id}
          role="option"
          aria-selected={i === activeIndex}
          onClick={() => handleSelect(cmd)}
          className={`w-full flex items-center gap-3 px-4 py-3 text-left transition-colors ${
            i === activeIndex
              ? "bg-primary/10 text-foreground"
              : "text-muted-foreground hover:bg-muted/40 hover:text-foreground"
          }`}
        >
          <cmd.icon
            className={`w-4 h-4 flex-shrink-0 ${
              i === activeIndex ? "text-primary" : "text-muted-foreground/60"
            }`}
          />
          <div className="min-w-0 flex-1 flex items-baseline gap-2">
            <span className="text-sm font-semibold">{cmd.label}</span>
            <span className="text-xs text-muted-foreground truncate">
              {cmd.description}
            </span>
          </div>
          {i === activeIndex && (
            <kbd className="text-[10px] text-muted-foreground/50 border border-border/40 rounded px-1 py-0.5 font-mono flex-shrink-0">
              ↵
            </kbd>
          )}
        </button>
      ))}
    </div>,
    document.body
  );
}
