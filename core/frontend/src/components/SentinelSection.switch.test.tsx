/**
 * Colony-switch race: a colony-scoped fetch that resolves AFTER the user
 * switched colonies must not apply its result to the new colony.
 *
 * This is the same class of bug the user hit on the Data tab ("colony A
 * loads colony B's table → table doesn't exist"): the panel isn't remounted
 * on a switch, only its `colonyName` prop changes, so an in-flight request
 * from the colony we just left can land late and clobber the current view.
 *
 * SentinelSection is the cleanest instance to pin: switch from colony A to B
 * while `getConfig(A)` is still pending, then let A resolve LAST. The card
 * must keep showing B's destination, never A's. Without the stale-response
 * guard in SentinelSection.load(), A's late response overwrites B → red.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import type { SentinelConfig } from "@/api/sentinel";

// SentinelSection subscribes to the global SSE bus; stub it to a no-op so the
// test drives the fetch race directly, not the event path.
vi.mock("@/hooks/use-sse", () => ({ useGlobalEvents: () => undefined }));

// Controllable getConfig: hand back a deferred promise per colony so the test
// decides the resolution ORDER (the whole point of the race).
const deferred = new Map<string, { resolve: (c: SentinelConfig) => void }>();
const getConfig = vi.fn((colonyName: string) => {
  return new Promise<SentinelConfig>((resolve) => {
    deferred.set(colonyName, { resolve });
  });
});
vi.mock("@/api/sentinel", () => ({ sentinelApi: { getConfig: (n: string) => getConfig(n) } }));

import { SentinelSection } from "./SentinelSection";

function cfg(chatId: string): SentinelConfig {
  // Only the fields SentinelSection's card reads. Telegram destination so the
  // rendered label embeds `chatId`, which we assert on.
  return {
    sentinel_enabled: true,
    channel: "telegram",
    target: { chat_id: chatId },
  } as unknown as SentinelConfig;
}

afterEach(() => {
  cleanup();
  deferred.clear();
  getConfig.mockClear();
});

describe("SentinelSection — colony switch", () => {
  it("drops a getConfig response from the colony we just left", async () => {
    const { rerender } = render(<SentinelSection colonyName="colony-a" />);
    expect(getConfig).toHaveBeenCalledWith("colony-a");

    // Switch to colony B before A's config resolves (panel is NOT remounted —
    // same instance, new prop, exactly like the real ColonyPanel).
    rerender(<SentinelSection colonyName="colony-b" />);
    expect(getConfig).toHaveBeenCalledWith("colony-b");

    // B resolves first and paints its destination.
    deferred.get("colony-b")!.resolve(cfg("B-CHAT"));
    await waitFor(() => expect(screen.getByText(/B-CHAT/)).toBeTruthy());

    // Now the STALE colony-A request resolves last. The guard must drop it.
    deferred.get("colony-a")!.resolve(cfg("A-CHAT"));

    // Give any (incorrectly) unguarded setState a chance to flush, then assert
    // B still owns the card and A never leaked in.
    await Promise.resolve();
    await waitFor(() => expect(screen.getByText(/B-CHAT/)).toBeTruthy());
    expect(screen.queryByText(/A-CHAT/)).toBeNull();
  });
});
