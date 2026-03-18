import { useState, useCallback } from "react";
import { useAuth } from "@/hooks/useAuth";
import { AuthPage } from "@/pages/AuthPage";
import { AppSidebar } from "@/components/nexus/AppSidebar";
import { ChatView } from "@/components/nexus/ChatView";
import { ExecutionPanel } from "@/components/nexus/ExecutionPanel";
import { DashboardPage } from "@/pages/DashboardPage";
import { SettingsPage } from "@/pages/SettingsPage";
import { TemplatesPage } from "@/pages/TemplatesPage";
import { LogsPage } from "@/pages/LogsPage";
import { useSessions } from "@/hooks/useSessions";
import { useExecutionSteps } from "@/hooks/useExecutionSteps";
import { Loader2 } from "lucide-react";
import type { AgentTemplate } from "@/data/mock-data";

type View = "chat" | "dashboard" | "settings" | "templates" | "logs";

const Index = () => {
  const { user, loading: authLoading } = useAuth();
  const [activeView, setActiveView] = useState<View>("chat");
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [executionOpen, setExecutionOpen] = useState(false);
  const [activeTemplate, setActiveTemplate] = useState<AgentTemplate | null>(null);
  const sessionHook = useSessions();
  const executionHook = useExecutionSteps();

  const handleApplyTemplate = useCallback(async (template: AgentTemplate) => {
    setActiveTemplate(template);
    // Create a new session with the template name
    const sid = await sessionHook.createSession(template.title);
    if (sid) {
      sessionHook.setActiveSessionId(sid);
    }
    executionHook.reset();
    setActiveView("chat");
  }, [sessionHook, executionHook]);

  if (authLoading) {
    return (
      <div className="flex h-screen w-full items-center justify-center bg-background">
        <Loader2 className="w-8 h-8 animate-spin text-primary" />
      </div>
    );
  }

  if (!user) return <AuthPage />;

  return (
    <div className="flex h-screen w-full bg-background text-foreground antialiased overflow-hidden">
      <AppSidebar
        activeView={activeView}
        onViewChange={setActiveView}
        isOpen={sidebarOpen}
        onToggle={() => setSidebarOpen(!sidebarOpen)}
        sessions={sessionHook.sessions}
        activeSessionId={sessionHook.activeSessionId}
        onSelectSession={(id) => {
          sessionHook.setActiveSessionId(id);
          setActiveView("chat");
          setSidebarOpen(false);
          executionHook.reset();
          // Clear template when switching to a non-template session
          setActiveTemplate(null);
        }}
        onNewSession={async () => {
          await sessionHook.createSession();
          setActiveView("chat");
          setSidebarOpen(false);
          executionHook.reset();
          setActiveTemplate(null);
        }}
        onSignOut={() => {}}
        activeTemplate={activeTemplate}
      />

      <main className="flex-1 flex min-w-0 overflow-hidden">
        {activeView === "chat" && (
          <>
            <ChatView
              sessionId={sessionHook.activeSessionId}
              onCreateSession={sessionHook.createSession}
              onUpdateTitle={sessionHook.updateSessionTitle}
              onToggleSidebar={() => setSidebarOpen(!sidebarOpen)}
              onToggleExecution={() => setExecutionOpen(!executionOpen)}
              executionHook={executionHook}
              activeTemplate={activeTemplate}
            />
            <ExecutionPanel
              isOpen={executionOpen}
              onClose={() => setExecutionOpen(false)}
              steps={executionHook.steps}
              tokenUsage={executionHook.tokenUsage}
              activeTemplate={activeTemplate}
            />
          </>
        )}
        {activeView === "dashboard" && <DashboardPage />}
        {activeView === "settings" && <SettingsPage activeTemplate={activeTemplate} />}
        {activeView === "templates" && (
          <TemplatesPage
            activeTemplateId={activeTemplate?.id}
            onApplyTemplate={handleApplyTemplate}
          />
        )}
        {activeView === "logs" && <LogsPage />}
      </main>
    </div>
  );
};

export default Index;
