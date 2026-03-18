import { useState, useCallback, useRef } from "react";
import { supabase } from "@/integrations/supabase/client";
import { streamChat } from "@/lib/stream-chat";
import { useAuth } from "@/hooks/useAuth";
import { toast } from "sonner";

export interface ChatMsg {
  id: string;
  role: "user" | "assistant";
  content: string;
  created_at: string;
}

interface ExecutionCallbacks {
  startExecution: () => void;
  onStreamStart: () => void;
  onStreamDelta: (chunkLen: number) => void;
  onStreamDone: () => void;
  onStreamError: () => void;
}

export function useChatMessages(sessionId: string | null, execution?: ExecutionCallbacks) {
  const { user } = useAuth();
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [streamedText, setStreamedText] = useState("");
  const [phase, setPhase] = useState<"idle" | "thinking" | "streaming">("idle");
  const abortRef = useRef(false);

  const loadMessages = useCallback(async (sid: string) => {
    const { data } = await supabase
      .from("chat_messages")
      .select("id, role, content, created_at")
      .eq("session_id", sid)
      .order("created_at", { ascending: true });
    if (data) setMessages(data as ChatMsg[]);
  }, []);

  const sendMessage = useCallback(
    async (text: string, onSessionTitle?: (title: string) => void) => {
      if (!user || !sessionId || phase !== "idle") return;

      execution?.startExecution();

      const { data: userMsg } = await supabase
        .from("chat_messages")
        .insert({ session_id: sessionId, user_id: user.id, role: "user", content: text })
        .select("id, role, content, created_at")
        .single();

      if (!userMsg) return;
      setMessages((prev) => [...prev, userMsg as ChatMsg]);
      setPhase("thinking");

      if (messages.length === 0 && onSessionTitle) {
        const title = text.length > 50 ? text.slice(0, 47) + "..." : text;
        onSessionTitle(title);
      }

      const history = [...messages, userMsg].map((m) => ({
        role: m.role as "user" | "assistant",
        content: m.content,
      }));

      let assistantContent = "";
      abortRef.current = false;

      setTimeout(async () => {
        setPhase("streaming");
        setStreamedText("");
        execution?.onStreamStart();

        try {
          await streamChat({
            messages: history,
            onDelta: (chunk) => {
              if (abortRef.current) return;
              assistantContent += chunk;
              setStreamedText(assistantContent);
              execution?.onStreamDelta(chunk.length);
            },
            onDone: async () => {
              if (!assistantContent.trim()) {
                setPhase("idle");
                return;
              }
              const { data: asstMsg } = await supabase
                .from("chat_messages")
                .insert({ session_id: sessionId, user_id: user.id, role: "assistant", content: assistantContent })
                .select("id, role, content, created_at")
                .single();

              if (asstMsg) setMessages((prev) => [...prev, asstMsg as ChatMsg]);
              setStreamedText("");
              setPhase("idle");
              execution?.onStreamDone();

              // Update session stats
              const msgCount = messages.length + 2; // user + assistant
              const tokenEst = Math.ceil(assistantContent.length / 4);
              await supabase
                .from("chat_sessions")
                .update({ message_count: msgCount, token_estimate: tokenEst, status: "completed" })
                .eq("id", sessionId);
            },
            onError: (err) => {
              toast.error(err);
              setPhase("idle");
              execution?.onStreamError();
            },
          });
        } catch {
          toast.error("Failed to get AI response");
          setPhase("idle");
          execution?.onStreamError();
        }
      }, 800);
    },
    [user, sessionId, phase, messages, execution]
  );

  return { messages, streamedText, phase, loadMessages, sendMessage, setMessages };
}
