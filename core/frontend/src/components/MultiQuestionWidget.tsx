import { useState, useRef, useEffect, useCallback } from "react";
import { Send, MessageCircleQuestion, X } from "lucide-react";

export interface QuestionItem {
  id: string;
  prompt: string;
  options?: string[];
}

export interface MultiQuestionWidgetProps {
  questions: QuestionItem[];
  onSubmit: (answers: Record<string, string>) => void;
  onDismiss?: () => void;
  /**
   * When true, skip the global Enter-to-submit listener. Use this when rendering
   * the widget inline alongside other inputs (e.g. the chat textarea) so Enter
   * isn't hijacked from the surrounding UI.
   */
  inline?: boolean;
}

export default function MultiQuestionWidget({ questions, onSubmit, onDismiss, inline = false }: MultiQuestionWidgetProps) {
  // Per-question state: selected index (null = nothing, options.length = "Other")
  const [selections, setSelections] = useState<(number | null)[]>(
    () => questions.map(() => null),
  );
  const [customTexts, setCustomTexts] = useState<string[]>(
    () => questions.map(() => ""),
  );
  const [submitted, setSubmitted] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  // Scroll the first unanswered question into view when it changes
  useEffect(() => {
    containerRef.current?.scrollTo({ top: 0, behavior: "smooth" });
  }, []);

  const canSubmit = questions.every((q, i) => {
    const sel = selections[i];
    if (sel === null) return false;
    const isOther = q.options ? sel === q.options.length : true;
    if (isOther && !customTexts[i].trim()) return false;
    return true;
  });

  const handleSubmit = useCallback(() => {
    if (!canSubmit || submitted) return;
    setSubmitted(true);
    const answers: Record<string, string> = {};
    for (let i = 0; i < questions.length; i++) {
      const q = questions[i];
      const sel = selections[i]!;
      const isOther = q.options ? sel === q.options.length : true;
      answers[q.id] = isOther ? customTexts[i].trim() : q.options![sel];
    }
    onSubmit(answers);
  }, [canSubmit, submitted, questions, selections, customTexts, onSubmit]);

  // Enter to submit (only when not focused on a text input).
  // Skipped in inline mode so the widget doesn't hijack keys from surrounding inputs.
  useEffect(() => {
    if (inline) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (submitted) return;
      const target = e.target as HTMLElement;
      const inInput = target.tagName === "INPUT" || target.tagName === "TEXTAREA";
      if (e.key === "Enter" && !e.shiftKey && !inInput) {
        e.preventDefault();
        handleSubmit();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [handleSubmit, submitted, inline]);

  if (submitted) return null;

  const answeredCount = selections.filter((s) => s !== null).length;

  return (
    <div className="p-4">
      <div className="bg-card border border-border rounded-xl shadow-sm overflow-hidden">
        {/* Header */}
        <div className="px-5 pt-4 pb-2 flex items-center gap-3">
          <div className="w-7 h-7 rounded-lg bg-primary/10 border border-primary/20 flex items-center justify-center flex-shrink-0">
            <MessageCircleQuestion className="w-3.5 h-3.5 text-primary" />
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium text-foreground">
              {questions.length} questions
            </p>
            <p className="text-[11px] text-muted-foreground">
              {answeredCount}/{questions.length} answered
            </p>
          </div>
          {onDismiss && (
            <button
              onClick={onDismiss}
              className="p-1 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/60 transition-colors flex-shrink-0"
            >
              <X className="w-4 h-4" />
            </button>
          )}
        </div>

        {/* Questions */}
        <div
          ref={containerRef}
          className="px-5 pb-3 space-y-4 max-h-[400px] overflow-y-auto"
        >
          {questions.map((q, qi) => {
            const sel = selections[qi];
            const hasOptions = q.options && q.options.length >= 2;
            const otherIndex = hasOptions ? q.options!.length : 0;
            const isOtherSelected = sel === otherIndex;

            return (
              <div key={q.id} className="space-y-1.5">
                <p className="text-sm font-medium text-foreground">
                  <span className="text-xs text-muted-foreground mr-1.5">
                    {qi + 1}.
                  </span>
                  {q.prompt}
                </p>

                {hasOptions ? (
                  <>
                    {q.options!.map((opt, oi) => (
                      <button
                        key={oi}
                        onClick={() => {
                          setSelections((prev) => {
                            const next = [...prev];
                            next[qi] = oi;
                            return next;
                          });
                        }}
                        className={`w-full text-left px-4 py-2 rounded-lg border text-sm transition-colors ${
                          sel === oi
                            ? "border-primary bg-primary/10 text-foreground"
                            : "border-border/60 bg-muted/20 text-foreground hover:border-primary/40 hover:bg-muted/40"
                        }`}
                      >
                        {opt}
                      </button>
                    ))}
                    <input
                      type="text"
                      value={customTexts[qi]}
                      onFocus={() => {
                        setSelections((prev) => {
                          const next = [...prev];
                          next[qi] = otherIndex;
                          return next;
                        });
                      }}
                      onChange={(e) => {
                        setSelections((prev) => {
                          const next = [...prev];
                          next[qi] = otherIndex;
                          return next;
                        });
                        setCustomTexts((prev) => {
                          const next = [...prev];
                          next[qi] = e.target.value;
                          return next;
                        });
                      }}
                      placeholder="Type a custom response..."
                      className={`w-full px-4 py-2 rounded-lg border border-dashed text-sm transition-colors bg-transparent placeholder:text-muted-foreground focus:outline-none ${
                        isOtherSelected
                          ? "border-primary bg-primary/10 text-foreground"
                          : "border-border text-muted-foreground hover:border-primary/40"
                      }`}
                    />
                  </>
                ) : (
                  <input
                    type="text"
                    value={customTexts[qi]}
                    onFocus={() => {
                      setSelections((prev) => {
                        const next = [...prev];
                        next[qi] = 0;
                        return next;
                      });
                    }}
                    onChange={(e) => {
                      setSelections((prev) => {
                        const next = [...prev];
                        next[qi] = 0;
                        return next;
                      });
                      setCustomTexts((prev) => {
                        const next = [...prev];
                        next[qi] = e.target.value;
                        return next;
                      });
                    }}
                    placeholder="Type your answer..."
                    className="w-full px-4 py-2 rounded-lg border text-sm transition-colors bg-transparent placeholder:text-muted-foreground focus:outline-none border-border text-foreground hover:border-primary/40 focus:border-primary"
                  />
                )}
              </div>
            );
          })}
        </div>

        {/* Submit */}
        <div className="px-5 pb-4">
          <button
            onClick={handleSubmit}
            disabled={!canSubmit}
            className="w-full flex items-center justify-center gap-2 py-2.5 rounded-lg text-sm font-medium bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
          >
            <Send className="w-3.5 h-3.5" />
            Submit All
          </button>
        </div>
      </div>
    </div>
  );
}
