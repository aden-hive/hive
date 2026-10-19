import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";

const get = vi.fn();
vi.mock("@/api/client", () => ({ api: { get: (path: string) => get(path) } }));

import RuntimeLogsDrawer from "./RuntimeLogsDrawer";
import { useShowRuntimeLogs } from "@/hooks/use-show-runtime-logs";

function Toggle() {
  const [, setShow] = useShowRuntimeLogs();
  return <button onClick={() => setShow(true)}>turn on</button>;
}

const line = (seq: number, text: string, stream = "stdout") => ({ seq, stream, text });

describe("RuntimeLogsDrawer", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    get.mockReset();
  });
  afterEach(() => vi.useRealTimers());

  it("shows the server's log and asks only for new lines", async () => {
    get
      .mockResolvedValueOnce({ boot: "b1", entries: [line(1, "onebot: QQ account connected")] })
      .mockResolvedValueOnce({ boot: "b1", entries: [line(2, "stall check: judge unavailable", "stderr")] });
    render(<><Toggle /><RuntimeLogsDrawer /></>);
    expect(get).not.toHaveBeenCalled();

    fireEvent.click(screen.getByText("turn on"));
    await act(async () => {});
    await act(async () => vi.advanceTimersByTime(2_000));
    fireEvent.click(screen.getByRole("button", { name: /runtime logs/i }));

    expect(get.mock.calls.map((c) => c[0])).toEqual([
      "/runtime-logs?after=0&boot=",
      "/runtime-logs?after=1&boot=b1",
    ]);
    expect(screen.getByText("onebot: QQ account connected")).toBeTruthy();
    expect(screen.getByText("stall check: judge unavailable").className).toContain("text-rose-300");
  });
});
