import { useState, useEffect, useCallback } from "react";
import { supabase } from "@/integrations/supabase/client";
import { useAuth } from "@/hooks/useAuth";

export interface SessionItem {
  id: string;
  title: string;
  status: string;
  created_at: string;
  updated_at: string;
}

export function useSessions() {
  const { user } = useAuth();
  const [sessions, setSessions] = useState<SessionItem[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchSessions = useCallback(async () => {
    if (!user) return;
    const { data } = await supabase
      .from("chat_sessions")
      .select("id, title, status, created_at, updated_at")
      .order("updated_at", { ascending: false })
      .limit(20);
    if (data) setSessions(data);
    setLoading(false);
  }, [user]);

  useEffect(() => {
    fetchSessions();
  }, [fetchSessions]);

  const createSession = useCallback(async (title = "New Session") => {
    if (!user) return null;
    const { data, error } = await supabase
      .from("chat_sessions")
      .insert({ user_id: user.id, title })
      .select("id")
      .single();
    if (error || !data) return null;
    await fetchSessions();
    setActiveSessionId(data.id);
    return data.id;
  }, [user, fetchSessions]);

  const updateSessionTitle = useCallback(async (sessionId: string, title: string) => {
    await supabase.from("chat_sessions").update({ title }).eq("id", sessionId);
    setSessions((prev) => prev.map((s) => (s.id === sessionId ? { ...s, title } : s)));
  }, []);

  return {
    sessions,
    activeSessionId,
    setActiveSessionId,
    createSession,
    updateSessionTitle,
    loading,
    refetch: fetchSessions,
  };
}
