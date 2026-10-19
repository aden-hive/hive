import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, act } from "@testing-library/react";
import { MemoryRouter, Outlet, useNavigate, useParams } from "react-router-dom";
import { useEffect, useRef } from "react";

// Only the routing contract is under test, so the shell and the sibling pages
// are stubbed down to nothing.
vi.mock("./layouts/AppLayout", () => ({ default: () => <Outlet /> }));
vi.mock("./pages/home", () => ({ default: () => null }));
vi.mock("./hooks/use-crm-access", () => ({ useCrmConfigured: () => ({ configured: false, loading: false }) }));

const mounts: string[] = [];

// Stands in for ColonyChat. The ref captures the colony this instance first
// bound to and — like the real page's messages/agentState.sessionId/SSE
// subscription — survives a re-render but not a remount. If React reuses the
// instance across a colony switch, `boundColony` still reads the OLD colony
// while the URL says the new one: precisely the reported leak, where a colony's
// transcript and session stayed bound under another colony's URL.
vi.mock("./pages/colony-chat", () => ({
  default: () => {
    const { colonyId } = useParams<{ colonyId: string }>();
    const boundColony = useRef(colonyId);
    useEffect(() => {
      mounts.push(boundColony.current!);
    }, []);
    return <div data-testid="bound-colony">{boundColony.current}</div>;
  },
}));

import App from "./App";

// Exposes the router's navigate() to the test body — the switch has to happen
// inside the live tree, not by remounting a fresh MemoryRouter.
function Navigator() {
  const navigate = useNavigate();
  useEffect(() => {
    (window as unknown as { __go: (p: string) => void }).__go = (p) => navigate(p);
  }, [navigate]);
  return null;
}

describe("colony routing — colony identity is component identity", () => {
  beforeEach(() => {
    mounts.length = 0;
  });

  it("remounts ColonyChat on a colony switch so no per-colony state carries over", async () => {
    render(
      <MemoryRouter initialEntries={["/colony/alpha"]}>
        <Navigator />
        <App />
      </MemoryRouter>,
    );

    expect(await screen.findByTestId("bound-colony")).toHaveTextContent("alpha");
    expect(mounts).toEqual(["alpha"]);

    // Switch colonies inside the SAME tree — the case where React reuses the
    // element unless it is keyed on the route param.
    await act(async () => {
      (window as unknown as { __go: (p: string) => void }).__go("/colony/beta");
    });

    // Without key={colonyId} this still reads "alpha": the instance survives and
    // keeps colony alpha's state bound under colony beta's URL.
    expect(screen.getByTestId("bound-colony")).toHaveTextContent("beta");
    expect(mounts).toEqual(["alpha", "beta"]);
  });
});
