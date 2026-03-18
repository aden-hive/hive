import { useState, useEffect, useCallback } from "react";
import { supabase } from "@/integrations/supabase/client";
import { useAuth } from "@/hooks/useAuth";
import { toast } from "sonner";

export interface ToolSetting {
  name: string;
  desc: string;
  enabled: boolean;
}

export interface UserSettings {
  agent_name: string;
  system_prompt: string;
  response_style: string;
  model: string;
  max_steps: number;
  memory_enabled: boolean;
  tools: ToolSetting[];
}

const DEFAULTS: UserSettings = {
  agent_name: "Research Assistant",
  system_prompt: "You are a precise research assistant. Always cite sources and use markdown for data presentation.",
  response_style: "Concise & Professional",
  model: "google/gemini-3-flash-preview",
  max_steps: 15,
  memory_enabled: true,
  tools: [
    { name: "Web Search", desc: "Allow the agent to browse the live internet.", enabled: true },
    { name: "Code Interpreter", desc: "Execute Python code for data analysis.", enabled: true },
    { name: "Knowledge Base", desc: "Access internal PDF and CSV documents.", enabled: false },
    { name: "API Connector", desc: "Call external REST and GraphQL APIs.", enabled: true },
    { name: "File Manager", desc: "Read, write, and organize files in workspace.", enabled: false },
  ],
};

export function useSettings() {
  const { user } = useAuth();
  const [settings, setSettings] = useState<UserSettings>(DEFAULTS);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!user) return;
    (async () => {
      const { data } = await supabase
        .from("user_settings")
        .select("*")
        .eq("user_id", user.id)
        .maybeSingle();
      if (data) {
        setSettings({
          agent_name: data.agent_name,
          system_prompt: data.system_prompt,
          response_style: data.response_style,
          model: data.model,
          max_steps: data.max_steps,
          memory_enabled: data.memory_enabled,
          tools: (data.tools as unknown as ToolSetting[]) || DEFAULTS.tools,
        });
      }
      setLoading(false);
    })();
  }, [user]);

  const save = useCallback(async (updated: UserSettings) => {
    if (!user) return;
    setSaving(true);
    const payload = {
      user_id: user.id,
      ...updated,
      tools: updated.tools as unknown as Record<string, unknown>[],
    };
    const { data: existing } = await supabase
      .from("user_settings")
      .select("id")
      .eq("user_id", user.id)
      .maybeSingle();

    let error;
    if (existing) {
      ({ error } = await supabase
        .from("user_settings")
        .update({
          agent_name: updated.agent_name,
          system_prompt: updated.system_prompt,
          response_style: updated.response_style,
          model: updated.model,
          max_steps: updated.max_steps,
          memory_enabled: updated.memory_enabled,
          tools: JSON.parse(JSON.stringify(updated.tools)),
        })
        .eq("user_id", user.id));
    } else {
      ({ error } = await supabase
        .from("user_settings")
        .insert({
          user_id: user.id,
          agent_name: updated.agent_name,
          system_prompt: updated.system_prompt,
          response_style: updated.response_style,
          model: updated.model,
          max_steps: updated.max_steps,
          memory_enabled: updated.memory_enabled,
          tools: JSON.parse(JSON.stringify(updated.tools)),
        }));
    }
    setSaving(false);
    if (error) {
      toast.error("Failed to save settings");
    } else {
      setSettings(updated);
      toast.success("Settings saved");
    }
  }, [user]);

  return { settings, setSettings, loading, saving, save };
}
