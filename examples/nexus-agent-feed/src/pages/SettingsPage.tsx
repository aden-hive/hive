import { ShieldCheck, Wrench, Cpu, Save, Loader2, RotateCcw, Layers } from "lucide-react";
import { NexusCard } from "@/components/nexus/NexusCard";
import { useSettings } from "@/hooks/useSettings";
import { useState, useEffect } from "react";
import { toast } from "sonner";
import type { AgentTemplate } from "@/data/mock-data";

const MODELS = [
  { label: "Gemini 3 Flash (Fast)", value: "google/gemini-3-flash-preview" },
  { label: "Gemini 2.5 Flash", value: "google/gemini-2.5-flash" },
  { label: "Gemini 2.5 Pro", value: "google/gemini-2.5-pro" },
  { label: "GPT-5 Mini", value: "openai/gpt-5-mini" },
  { label: "GPT-5", value: "openai/gpt-5" },
];

const STYLES = ["Concise & Professional", "Detailed & Thorough", "Casual & Friendly", "Technical & Precise"];

const ALL_TOOL_NAMES = ["Web Search", "Code Interpreter", "Knowledge Base", "API Connector", "File Manager"];

const inputClass = "w-full bg-background border border-border rounded-lg px-4 py-2.5 text-sm focus:ring-2 focus:ring-primary/15 focus:border-primary/30 outline-none text-foreground transition-all";

interface SettingsPageProps {
  activeTemplate?: AgentTemplate | null;
}

export function SettingsPage({ activeTemplate }: SettingsPageProps) {
  const { settings, setSettings, loading, saving, save } = useSettings();
  const [hasChanges, setHasChanges] = useState(false);
  const [templateApplied, setTemplateApplied] = useState(false);

  // Apply template settings when template changes
  useEffect(() => {
    if (activeTemplate && !templateApplied) {
      const cfg = activeTemplate.config;
      setSettings({
        agent_name: activeTemplate.title,
        system_prompt: cfg.systemPrompt,
        response_style: cfg.responseStyle,
        model: cfg.model,
        max_steps: cfg.maxSteps,
        memory_enabled: cfg.memoryEnabled,
        tools: settings.tools.map(t => ({
          ...t,
          enabled: cfg.enabledTools.includes(t.name),
        })),
      });
      setHasChanges(true);
      setTemplateApplied(true);
    }
  }, [activeTemplate]);

  // Reset templateApplied flag when template changes
  useEffect(() => {
    setTemplateApplied(false);
  }, [activeTemplate?.id]);

  const update = <K extends keyof typeof settings>(key: K, value: (typeof settings)[K]) => {
    setSettings({ ...settings, [key]: value });
    setHasChanges(true);
  };

  const toggleTool = (index: number) => {
    const updated = settings.tools.map((t, i) => (i === index ? { ...t, enabled: !t.enabled } : t));
    update("tools", updated);
  };

  const handleSave = async () => {
    await save(settings);
    setHasChanges(false);
    toast.success("Settings saved successfully");
  };

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <Loader2 className="w-5 h-5 animate-spin text-primary" />
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto p-6 lg:p-8 max-w-3xl mx-auto w-full">
      <header className="mb-8">
        <h1 className="text-xl font-bold text-foreground tracking-tight font-display">Agent Configuration</h1>
        <p className="text-muted-foreground text-sm mt-1">
          Define the core behavior and constraints for your AI agents.
        </p>
        {activeTemplate && (
          <div className="mt-3 flex items-center gap-2 px-3 py-2 bg-primary/5 border border-primary/15 rounded-lg w-fit">
            <Layers size={13} className="text-primary" />
            <span className="text-[12px] font-medium text-primary">
              Configured from "{activeTemplate.title}" template
            </span>
          </div>
        )}
      </header>

      <div className="space-y-6">
        {/* General */}
        <section>
          <h3 className="text-[13px] font-semibold text-foreground mb-3 flex items-center gap-2 font-display">
            <ShieldCheck size={16} className="text-primary" /> General
          </h3>
          <NexusCard className="space-y-5">
            <div>
              <label className="block text-[11px] font-semibold text-muted-foreground uppercase tracking-wide mb-1.5">Agent Name</label>
              <input type="text" value={settings.agent_name} onChange={(e) => update("agent_name", e.target.value)} className={inputClass} />
              <p className="text-[10px] text-muted-foreground/50 mt-1">This name will appear in the chat interface</p>
            </div>
            <div>
              <label className="block text-[11px] font-semibold text-muted-foreground uppercase tracking-wide mb-1.5">System Prompt</label>
              <textarea
                rows={5}
                value={settings.system_prompt}
                onChange={(e) => update("system_prompt", e.target.value)}
                className={`${inputClass} resize-none font-mono text-[12px] leading-relaxed`}
              />
              <p className="text-[10px] text-muted-foreground/50 mt-1">{settings.system_prompt.length} characters</p>
            </div>
            <div>
              <label className="block text-[11px] font-semibold text-muted-foreground uppercase tracking-wide mb-1.5">Response Style</label>
              <div className="grid grid-cols-2 gap-2">
                {STYLES.map((s) => (
                  <button
                    key={s}
                    onClick={() => update("response_style", s)}
                    className={`px-3 py-2.5 rounded-lg text-[12px] font-medium text-left transition-all border ${
                      settings.response_style === s
                        ? "border-primary bg-primary/5 text-foreground"
                        : "border-border bg-background text-muted-foreground hover:border-primary/30"
                    }`}
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>
          </NexusCard>
        </section>

        {/* Model */}
        <section>
          <h3 className="text-[13px] font-semibold text-foreground mb-3 flex items-center gap-2 font-display">
            <Cpu size={16} className="text-primary" /> Model & Limits
          </h3>
          <NexusCard className="space-y-5">
            <div>
              <label className="block text-[11px] font-semibold text-muted-foreground uppercase tracking-wide mb-1.5">Model</label>
              <select value={settings.model} onChange={(e) => update("model", e.target.value)} className={inputClass}>
                {MODELS.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
              </select>
            </div>
            <div>
              <label className="block text-[11px] font-semibold text-muted-foreground uppercase tracking-wide mb-1.5">
                Max Execution Steps
              </label>
              <div className="flex items-center gap-4">
                <input
                  type="range"
                  min={1}
                  max={50}
                  value={settings.max_steps}
                  onChange={(e) => update("max_steps", Number(e.target.value))}
                  className="flex-1 accent-primary h-1"
                />
                <span className="text-sm font-semibold text-foreground tabular-nums w-8 text-right">{settings.max_steps}</span>
              </div>
              <div className="flex justify-between text-[10px] text-muted-foreground/50 mt-1">
                <span>Fewer steps (faster)</span><span>More steps (thorough)</span>
              </div>
            </div>
            <div className="flex items-center justify-between py-1 px-1">
              <div>
                <p className="text-[13px] font-medium text-foreground">Memory</p>
                <p className="text-[11px] text-muted-foreground">Remember context across sessions</p>
              </div>
              <button
                onClick={() => update("memory_enabled", !settings.memory_enabled)}
                className={`w-10 h-[22px] rounded-full relative transition-colors ${settings.memory_enabled ? "bg-primary" : "bg-border"}`}
              >
                <div className={`absolute top-[3px] w-4 h-4 bg-card rounded-full transition-all shadow-sm ${settings.memory_enabled ? "right-[3px]" : "left-[3px]"}`} />
              </button>
            </div>
          </NexusCard>
        </section>

        {/* Tools */}
        <section>
          <h3 className="text-[13px] font-semibold text-foreground mb-3 flex items-center gap-2 font-display">
            <Wrench size={16} className="text-primary" /> Capabilities
          </h3>
          <NexusCard noPadding className="divide-y divide-border/50">
            {settings.tools.map((tool, i) => (
              <div key={i} className="px-5 py-4 flex items-center justify-between">
                <div>
                  <p className="text-[13px] font-medium text-foreground">{tool.name}</p>
                  <p className="text-[11px] text-muted-foreground mt-0.5">{tool.desc}</p>
                </div>
                <button
                  onClick={() => toggleTool(i)}
                  className={`w-10 h-[22px] rounded-full relative transition-colors ${tool.enabled ? "bg-primary" : "bg-border"}`}
                >
                  <div className={`absolute top-[3px] w-4 h-4 bg-card rounded-full transition-all shadow-sm ${tool.enabled ? "right-[3px]" : "left-[3px]"}`} />
                </button>
              </div>
            ))}
          </NexusCard>
        </section>

        <div className="flex justify-end gap-3 pt-2 pb-8">
          <button
            onClick={() => setHasChanges(false)}
            disabled={!hasChanges}
            className="px-4 py-2.5 text-[13px] font-medium text-muted-foreground hover:text-foreground border border-border rounded-lg transition-colors disabled:opacity-30 flex items-center gap-1.5"
          >
            <RotateCcw size={13} /> Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={saving || !hasChanges}
            className="px-5 py-2.5 bg-primary text-primary-foreground rounded-lg text-[13px] font-semibold hover:opacity-90 transition-all shadow-sm flex items-center gap-2 disabled:opacity-40"
          >
            {saving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
            {saving ? "Saving…" : "Save Changes"}
          </button>
        </div>
      </div>
    </div>
  );
}
