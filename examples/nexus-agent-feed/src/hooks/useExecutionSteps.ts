import { useState, useCallback } from "react";

export type StepStatus = "success" | "running" | "pending" | "failed";

export interface ExecutionStep {
  id: string;
  label: string;
  status: StepStatus;
  time: string;
  tool?: string;
  details?: string;
  duration?: string;
}

export function useExecutionSteps() {
  const [steps, setSteps] = useState<ExecutionStep[]>([]);
  const [tokenUsage, setTokenUsage] = useState(0);

  const now = () => new Date().toLocaleTimeString("en-US", { hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" });

  const startExecution = useCallback(() => {
    const t = now();
    setTokenUsage(0);
    setSteps([
      { id: "s1", label: "Parsing user intent", status: "running", time: t },
      { id: "s2", label: "Building context window", status: "pending", time: "--:--:--" },
      { id: "s3", label: "Calling AI model", status: "pending", time: "--:--:--" },
      { id: "s4", label: "Streaming response", status: "pending", time: "--:--:--" },
      { id: "s5", label: "Saving to database", status: "pending", time: "--:--:--" },
    ]);

    // Simulate step progression
    setTimeout(() => {
      setSteps((prev) => prev.map((s) =>
        s.id === "s1" ? { ...s, status: "success" as StepStatus, duration: "85ms", details: "Intent parsed successfully" } :
        s.id === "s2" ? { ...s, status: "running" as StepStatus, time: now() } : s
      ));
    }, 300);

    setTimeout(() => {
      setSteps((prev) => prev.map((s) =>
        s.id === "s2" ? { ...s, status: "success" as StepStatus, duration: "120ms", details: "Context window built with conversation history" } :
        s.id === "s3" ? { ...s, status: "running" as StepStatus, time: now(), tool: "AI_Gateway" } : s
      ));
    }, 600);
  }, []);

  const onStreamStart = useCallback(() => {
    const t = now();
    setSteps((prev) => prev.map((s) =>
      s.id === "s3" ? { ...s, status: "success" as StepStatus, duration: "1.2s", details: "Connected to AI gateway, stream opened" } :
      s.id === "s4" ? { ...s, status: "running" as StepStatus, time: t, tool: "SSE_Stream" } : s
    ));
  }, []);

  const onStreamDelta = useCallback((chunkLen: number) => {
    setTokenUsage((prev) => prev + Math.ceil(chunkLen / 4));
  }, []);

  const onStreamDone = useCallback(() => {
    const t = now();
    setSteps((prev) => prev.map((s) =>
      s.id === "s4" ? { ...s, status: "success" as StepStatus, duration: "streaming complete" } :
      s.id === "s5" ? { ...s, status: "running" as StepStatus, time: t } : s
    ));

    setTimeout(() => {
      setSteps((prev) => prev.map((s) =>
        s.id === "s5" ? { ...s, status: "success" as StepStatus, duration: "45ms", details: "Message persisted to database" } : s
      ));
    }, 200);
  }, []);

  const onStreamError = useCallback(() => {
    setSteps((prev) => prev.map((s) =>
      s.status === "running" ? { ...s, status: "failed" as StepStatus, details: "Stream error occurred" } :
      s.status === "pending" ? { ...s, status: "failed" as StepStatus } : s
    ));
  }, []);

  const reset = useCallback(() => {
    setSteps([]);
    setTokenUsage(0);
  }, []);

  return { steps, tokenUsage, startExecution, onStreamStart, onStreamDelta, onStreamDone, onStreamError, reset };
}
