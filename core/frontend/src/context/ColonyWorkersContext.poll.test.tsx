/**
 * Circuit-breaker tests for the ColonyWorkersContext workers poll.
 *
 * The context polls GET /sessions/{id}/workers every 2s while a session
 * is attached. A 404 means the runtime's SessionManager no longer holds
 * the session in memory (stopped, or the runtime restarted) — it can
 * only come back via a selectSession that also transitions the page's
 * sessionId. Regression under test: without the breaker, a dead session
 * is polled every 2s forever, printing a main-process log line per miss
 * (the ipc.ts quiet-polling suppression only mutes 2xx responses).
 */
import { useEffect } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render } from "@testing-library/react";
import { ApiError } from "@/api/client";

vi.mock("@/api/colonyWorkers", () => ({
  colonyWorkersApi: { list: vi.fn() },
}));

import { colonyWorkersApi, type WorkerSummary } from "@/api/colonyWorkers";
import {
  ColonyWorkersProvider,
  SESSION_GONE_404_LIMIT,
  useColonyWorkers,
} from "./ColonyWorkersContext";

const listMock = vi.mocked(colonyWorkersApi.list);

const WORKER: WorkerSummary = {
  worker_id: "w1",
  task: "do the thing",
  status: "running",
  started_at: 1,
  result: null,
};

const ok = (workers: WorkerSummary[] = [WORKER]) =>
  Promise.resolve({ workers });
const gone = () =>
  Promise.reject(new ApiError(404, { error: "Session 'x' not found" }));

/** Last workers snapshot observed by a consumer, mirrored out of React. */
let observedWorkers: WorkerSummary[] = [];

function Probe({ sessionId }: { sessionId: string | null }) {
  const ctx = useColonyWorkers();
  observedWorkers = ctx.workers;
  const { setSessionId } = ctx;
  useEffect(() => {
    setSessionId(sessionId);
  }, [sessionId, setSessionId]);
  return null;
}

const mount = (sessionId: string | null) =>
  render(
    <ColonyWorkersProvider>
      <Probe sessionId={sessionId} />
    </ColonyWorkersProvider>,
  );

/** Flush pending effects + microtasks (the immediate first tick). */
const flush = () => act(async () => {});

/** Advance fake time and flush the poll promise it fires. */
const elapse = (ms: number) =>
  act(async () => {
    vi.advanceTimersByTime(ms);
  });

/** Advance n poll ticks one at a time. A single big advanceTimersByTime
 *  fires every interval callback in one synchronous burst, so the
 *  breaker's rejection handler (a microtask) couldn't interleave the
 *  way it does in real time — step per tick instead. */
const elapseTicks = async (n: number) => {
  for (let i = 0; i < n; i++) await elapse(2000);
};

beforeEach(() => {
  vi.useFakeTimers();
  vi.spyOn(console, "warn").mockImplementation(() => {});
  observedWorkers = [];
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.restoreAllMocks();
  listMock.mockReset();
});

describe("workers poll circuit breaker", () => {
  it("polls immediately and then every 2s, publishing workers", async () => {
    listMock.mockImplementation(() => ok());
    mount("s1");
    await flush();
    expect(listMock).toHaveBeenCalledTimes(1);
    expect(observedWorkers).toEqual([WORKER]);
    await elapse(4000);
    expect(listMock).toHaveBeenCalledTimes(3);
  });

  it(`stops polling after ${SESSION_GONE_404_LIMIT} consecutive 404s and clears workers`, async () => {
    listMock.mockImplementationOnce(() => ok());
    listMock.mockImplementation(() => gone());
    mount("s1");
    await flush(); // initial tick — success, workers land
    expect(observedWorkers).toEqual([WORKER]);

    await elapseTicks(SESSION_GONE_404_LIMIT); // consecutive misses
    const callsAtTrip = 1 + SESSION_GONE_404_LIMIT;
    expect(listMock).toHaveBeenCalledTimes(callsAtTrip);
    expect(observedWorkers).toEqual([]);

    await elapseTicks(10); // breaker tripped — no further requests
    expect(listMock).toHaveBeenCalledTimes(callsAtTrip);
  });

  it("does not trip on non-404 failures", async () => {
    listMock.mockImplementation(() =>
      Promise.reject(new ApiError(500, { error: "boom" })),
    );
    mount("s1");
    await flush();
    await elapseTicks(SESSION_GONE_404_LIMIT + 2);
    expect(listMock).toHaveBeenCalledTimes(SESSION_GONE_404_LIMIT + 3);
  });

  it("resets the miss counter on a success between 404s", async () => {
    // limit-1 misses, one success, then more misses: only an unbroken
    // run of `limit` misses may trip the breaker.
    for (let i = 0; i < SESSION_GONE_404_LIMIT - 1; i++) {
      listMock.mockImplementationOnce(() => gone());
    }
    listMock.mockImplementationOnce(() => ok());
    for (let i = 0; i < SESSION_GONE_404_LIMIT - 1; i++) {
      listMock.mockImplementationOnce(() => gone());
    }
    listMock.mockImplementation(() => ok());

    mount("s1");
    await flush();
    await elapseTicks(2 * SESSION_GONE_404_LIMIT);
    // Still polling: every scheduled tick fired.
    expect(listMock).toHaveBeenCalledTimes(2 * SESSION_GONE_404_LIMIT + 1);
  });

  it("restarts polling when the sessionId changes after a trip", async () => {
    listMock.mockImplementation(() => gone());
    const view = mount("s1");
    await flush(); // initial tick — miss 1
    await elapseTicks(SESSION_GONE_404_LIMIT - 1); // misses up to the limit
    const callsAtTrip = SESSION_GONE_404_LIMIT;
    expect(listMock).toHaveBeenCalledTimes(callsAtTrip);
    await elapseTicks(3); // confirm it's tripped
    expect(listMock).toHaveBeenCalledTimes(callsAtTrip);

    listMock.mockImplementation(() => ok());
    view.rerender(
      <ColonyWorkersProvider>
        <Probe sessionId="s2" />
      </ColonyWorkersProvider>,
    );
    await flush();
    expect(listMock).toHaveBeenCalledTimes(callsAtTrip + 1);
    expect(listMock).toHaveBeenLastCalledWith("s2");
    expect(observedWorkers).toEqual([WORKER]);
    await elapse(2000);
    expect(listMock).toHaveBeenCalledTimes(callsAtTrip + 2);
  });
});
