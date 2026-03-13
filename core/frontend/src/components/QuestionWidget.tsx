import { useState, useRef, useEffect, useCallback } from "react";
import { Send, MessageCircleQuestion, X } from "lucide-react";

export interface QuestionWidgetProps {
  /** The question text shown to the user */
  question: string;
  /** 1-3 predefined options. The UI appends an "Other" free-text option. */
  options: string[];
  /** Called with the selected option label or custom text, and whether "Other" was chosen */
  onSubmit: (answer: string, isOther: boolean) => void;
  /** Called when user dismisses the question without answering */
  onDismiss?: () => void;
  /** Where this question originated — affects accent color */
  source?: "queen" | "worker" | null;
  /** When true, skip outer padding (used when rendered inline in the chat area) */
  inline?: boolean;
}

const WORKER_ACCENT = "hsl(220,60%,55%)";

export default function QuestionWidget({ question, options, onSubmit, onDismiss, source, inline }: QuestionWidgetProps) {
  const [selected, setSelected] = useState<number | null>(null);
  const [customText, setCustomText] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  // "Other" is always the last option index
  const otherIndex = options.length;
  const isOtherSelected = selected === otherIndex;

  // Focus the text input when "Other" is selected
  useEffect(() => {
    if (isOtherSelected) {
      inputRef.current?.focus();
    }
  }, [isOtherSelected]);

  const canSubmit = selected !== null && (!isOtherSelected || customText.trim().length > 0);

  const handleSubmit = useCallback(() => {
    if (!canSubmit || submitted) return;
    setSubmitted(true);
    if (isOtherSelected) {
      onSubmit(customText.trim(), true);
    } else {
      onSubmit(options[selected!], false);
    }
  }, [canSubmit, submitted, isOtherSelected, customText, options, selected, onSubmit]);

  // Keyboard: Enter to submit, number keys to select (only when text input is not focused)
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (submitted) return;
      const inTextInput = e.target === inputRef.current;

      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSubmit();
        return;
      }

      // Number keys 1-4 select options — skip when typing in the "Other" field
      if (!inTextInput) {
        const num = parseInt(e.key, 10);
        if (num >= 1 && num <= options.length + 1) {
          e.preventDefault();
          setSelected(num - 1);
        }
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [handleSubmit, submitted, options.length]);

  if (submitted) return null;

  const isWorker = source === "worker";
  // Worker questions use a blue accent; queen questions use the default primary color
  const accentBg = isWorker ? `${WORKER_ACCENT}15` : undefined;
  const accentSelectedBg = isWorker ? `${WORKER_ACCENT}18` : undefined;
  const accentSelectedBorder = isWorker ? WORKER_ACCENT : undefined;

  return (
    <div ref={containerRef} className={inline ? "py-1" : "p-4"}>
      <div
        className="bg-card rounded-xl shadow-sm overflow-hidden"
        style={{
          border: isWorker ? `1px solid ${WORKER_ACCENT}30` : "1px solid hsl(var(--border))",
          backgroundColor: accentBg,
        }}
      >
        {/* Header / Question */}
        <div className="px-5 pt-4 pb-3 flex items-start gap-3">
          <div
            className={`w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0 mt-0.5 ${
              isWorker ? "" : "bg-primary/10 border border-primary/20"
            }`}
            style={isWorker ? { backgroundColor: `${WORKER_ACCENT}15`, border: `1px solid ${WORKER_ACCENT}30` } : undefined}
          >
            <MessageCircleQuestion
              className={`w-3.5 h-3.5 ${isWorker ? "" : "text-primary"}`}
              style={isWorker ? { color: WORKER_ACCENT } : undefined}
            />
          </div>
          <p className="text-sm font-medium text-foreground leading-relaxed flex-1">{question}</p>
          {onDismiss && (
            <button
              onClick={onDismiss}
              className="p-1 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/60 transition-colors flex-shrink-0"
            >
              <X className="w-4 h-4" />
            </button>
          )}
        </div>

        {/* Options */}
        <div className="px-5 pb-3 space-y-1.5">
          {options.map((option, idx) => (
            <button
              key={idx}
              onClick={() => setSelected(idx)}
              className={`w-full text-left px-4 py-2.5 rounded-lg border text-sm transition-colors ${
                selected === idx
                  ? isWorker
                    ? "text-foreground"
                    : "border-primary bg-primary/10 text-foreground"
                  : isWorker
                    ? "text-foreground hover:bg-muted/40"
                    : "border-border/60 bg-muted/20 text-foreground hover:border-primary/40 hover:bg-muted/40"
              }`}
              style={
                selected === idx && isWorker
                  ? { borderColor: accentSelectedBorder, backgroundColor: accentSelectedBg }
                  : isWorker
                    ? { borderColor: `${WORKER_ACCENT}25`, backgroundColor: `${WORKER_ACCENT}08` }
                    : undefined
              }
            >
              <span className="text-xs text-muted-foreground mr-2">{idx + 1}.</span>
              {option}
            </button>
          ))}

          {/* "Other" — inline text input that auto-selects on focus */}
          <input
            ref={inputRef}
            type="text"
            value={customText}
            onFocus={() => setSelected(otherIndex)}
            onChange={(e) => {
              setSelected(otherIndex);
              setCustomText(e.target.value);
            }}
            placeholder="Type a custom response..."
            className={`w-full px-4 py-2.5 rounded-lg border border-dashed text-sm transition-colors bg-transparent placeholder:text-muted-foreground focus:outline-none ${
              isOtherSelected
                ? isWorker
                  ? "text-foreground"
                  : "border-primary bg-primary/10 text-foreground"
                : isWorker
                  ? "text-muted-foreground"
                  : "border-border text-muted-foreground hover:border-primary/40"
            }`}
            style={
              isOtherSelected && isWorker
                ? { borderColor: accentSelectedBorder, backgroundColor: accentSelectedBg }
                : isWorker
                  ? { borderColor: `${WORKER_ACCENT}30` }
                  : undefined
            }
          />
        </div>

        {/* Submit */}
        <div className="px-5 pb-4">
          <button
            onClick={handleSubmit}
            disabled={!canSubmit}
            className={`w-full flex items-center justify-center gap-2 py-2.5 rounded-lg text-sm font-medium disabled:opacity-30 disabled:cursor-not-allowed transition-colors ${
              isWorker
                ? "text-white hover:opacity-90"
                : "bg-primary text-primary-foreground hover:bg-primary/90"
            }`}
            style={isWorker ? { backgroundColor: WORKER_ACCENT } : undefined}
          >
            <Send className="w-3.5 h-3.5" />
            Submit
          </button>
        </div>
      </div>
    </div>
  );
}
