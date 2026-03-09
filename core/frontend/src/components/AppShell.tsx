/**
 * AppShell — persistent layout wrapper for Home and MyAgents pages.
 *
 * Renders: TopBar (full width) + full-width page content below.
 * Workspace has its own full layout and does NOT use this wrapper.
 */

import TopBar from "@/components/TopBar";

interface AppShellProps {
  children: React.ReactNode;
}

export default function AppShell({ children }: AppShellProps) {
  return (
    <div className="h-screen bg-background flex flex-col overflow-hidden">
      <TopBar />
      <div className="flex-1 min-h-0 overflow-y-auto">
        {children}
      </div>
    </div>
  );
}
