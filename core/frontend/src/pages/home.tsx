import { useState, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { Loader2, Send } from "lucide-react";
import { messagesApi } from "@/api/messages";
import { useColony } from "@/context/ColonyContext";

const promptHints = [
  "Check my inbox for urgent emails",
  "Find senior engineer roles that match my profile",
  "Run a security scan on my domain",
  "Summarize today's agent activity",
];

export default function Home() {
  const navigate = useNavigate();
  const { userProfile, refresh } = useColony();
  const [inputValue, setInputValue] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [activePrompt, setActivePrompt] = useState<string | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const displayName = userProfile.displayName || "there";

  const startQueenSession = async (text: string) => {
    if (!text.trim() || submitting) return;
    setSubmitting(true);
    setActivePrompt(text.trim());
    try {
      const result = await messagesApi.newMessage(text.trim());
      refresh();
      navigate(`/queen/${result.queen_id}?session=${encodeURIComponent(result.session_id)}`);
    } catch {
      // Keep the user on home if bootstrap fails.
    } finally {
      setSubmitting(false);
      setActivePrompt(null);
    }
  };

  const handlePromptHint = (text: string) => {
    void startQueenSession(text);
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!inputValue.trim()) return;
    void startQueenSession(inputValue);
  };

  return (
    <div className="flex-1 flex flex-col items-center justify-center p-6">
      <div className="w-full max-w-2xl">
        {/* Personalized greeting */}
        <div className="text-center mb-8">
          <h1 className="text-2xl font-bold text-foreground mb-2">
            Hey {displayName}, what can I help you with?
          </h1>
          <p className="text-sm text-muted-foreground">
            Describe a task and I'll deploy an agent to handle it
          </p>
        </div>

        {/* Chat input */}
        <form onSubmit={handleSubmit} className="mb-6">
          <div className="relative border border-border/60 rounded-xl bg-card/50 hover:border-primary/30 focus-within:border-primary/40 transition-colors shadow-sm">
            <textarea
              ref={textareaRef}
              rows={1}
              value={inputValue}
              onChange={(e) => {
                setInputValue(e.target.value);
                const ta = e.target;
                ta.style.height = "auto";
                ta.style.height = `${Math.min(ta.scrollHeight, 160)}px`;
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  handleSubmit(e);
                }
              }}
              placeholder="Describe a task for the hive..."
              className="w-full bg-transparent px-5 py-4 pr-12 text-sm text-foreground placeholder:text-muted-foreground/60 focus:outline-none rounded-xl resize-none overflow-y-auto"
            />
            <div className="absolute right-3 bottom-2.5">
              <button
                type="submit"
                disabled={!inputValue.trim() || submitting}
                className="w-8 h-8 rounded-lg bg-primary/90 hover:bg-primary text-primary-foreground flex items-center justify-center transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
              >
                {submitting && !activePrompt ? (
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                ) : (
                  <Send className="w-3.5 h-3.5" />
                )}
              </button>
            </div>
          </div>
        </form>

        {/* Prompt hint pills */}
        <div className="flex flex-wrap justify-center gap-2">
          {promptHints.map((hint) => (
            <button
              key={hint}
              onClick={() => handlePromptHint(hint)}
              disabled={submitting}
              className="text-xs text-muted-foreground hover:text-foreground border border-border/50 hover:border-primary/30 rounded-full px-3.5 py-1.5 transition-all hover:bg-primary/[0.03] disabled:opacity-60 disabled:cursor-not-allowed"
            >
              <span className="inline-flex items-center gap-1.5">
                {submitting && activePrompt === hint ? (
                  <>
                    <Loader2 className="w-3 h-3 animate-spin" />
                    Connecting...
                  </>
                ) : (
                  hint
                )}
              </span>
            </button>
          ))}
        </div>
        {submitting && activePrompt && (
          <p className="mt-4 text-center text-xs text-muted-foreground">
            The queens are debating who should take this on...
          </p>
        )}
      </div>
    </div>
  );
}
