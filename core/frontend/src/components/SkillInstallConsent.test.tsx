import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import type { SkillInstallRequest } from "@/api/skills";

const listInstallRequests = vi.fn();
const decideInstallRequest = vi.fn();
vi.mock("@/api/skills", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/skills")>()),
  skillsApi: {
    listInstallRequests: (sessionId: string) => listInstallRequests(sessionId),
    decideInstallRequest: (sessionId: string, requestId: string, decision: string) =>
      decideInstallRequest(sessionId, requestId, decision),
  },
}));

import SkillInstallConsent from "./SkillInstallConsent";

const REQUEST: SkillInstallRequest = {
  id: "req_1",
  name: "house-style",
  description: "How Ava formats her reports.",
  body: "# House style\n\nLead with the answer.\n",
  files: [{ path: "scripts/check.py", content: "print('ok')\n" }],
  requested_at: "2026-10-31T08:00:00+00:00",
  replaces: false,
};

describe("SkillInstallConsent", () => {
  beforeEach(() => {
    listInstallRequests.mockReset();
    decideInstallRequest.mockReset().mockResolvedValue({ name: "house-style", decision: "approve", queen_told: true });
  });

  it("shows the skill as it would be installed, files included", async () => {
    listInstallRequests.mockResolvedValue({ requests: [REQUEST] });
    render(<SkillInstallConsent sessionId="session_ava_1" refreshKey={0} />);

    expect(await screen.findByText("Add a skill to the shared library?")).toBeTruthy();
    expect(screen.getByText("house-style")).toBeTruthy();
    expect(screen.getByText("How Ava formats her reports.")).toBeTruthy();
    expect(screen.getByText("SKILL.md")).toBeTruthy();
    expect(screen.getByText("scripts/check.py")).toBeTruthy();
    expect(screen.queryByText(/Installing\s+replaces it/)).toBeNull();
    expect(listInstallRequests).toHaveBeenCalledWith("session_ava_1");
  });

  it("warns when installing replaces a shared skill", async () => {
    listInstallRequests.mockResolvedValue({ requests: [{ ...REQUEST, replaces: true }] });
    render(<SkillInstallConsent sessionId="session_ava_1" refreshKey={0} />);

    expect(await screen.findByText(/Installing\s+replaces it/)).toBeTruthy();
  });

  it.each([
    ["Install for everyone", "approve"],
    ["Decline", "deny"],
  ])("%s sends %s and closes the prompt", async (button, decision) => {
    listInstallRequests.mockResolvedValue({ requests: [REQUEST] });
    render(<SkillInstallConsent sessionId="session_ava_1" refreshKey={0} />);

    fireEvent.click(await screen.findByText(button));

    await waitFor(() => expect(screen.queryByText("Add a skill to the shared library?")).toBeNull());
    expect(decideInstallRequest).toHaveBeenCalledWith("session_ava_1", "req_1", decision);
  });

  it("closing decides nothing", async () => {
    listInstallRequests.mockResolvedValue({ requests: [REQUEST] });
    render(<SkillInstallConsent sessionId="session_ava_1" refreshKey={0} />);

    fireEvent.click(await screen.findByLabelText("Close"));

    expect(screen.queryByText("Add a skill to the shared library?")).toBeNull();
    expect(decideInstallRequest).not.toHaveBeenCalled();
  });

  it("keeps the prompt open and says why when the decision fails", async () => {
    listInstallRequests.mockResolvedValue({ requests: [REQUEST] });
    decideInstallRequest.mockRejectedValue(new Error("skill install request req_1 was already denied"));
    render(<SkillInstallConsent sessionId="session_ava_1" refreshKey={0} />);

    fireEvent.click(await screen.findByText("Install for everyone"));

    expect(await screen.findByText("skill install request req_1 was already denied")).toBeTruthy();
    expect(screen.getByText("Add a skill to the shared library?")).toBeTruthy();
  });

  it("shows nothing when no request is waiting", async () => {
    listInstallRequests.mockResolvedValue({ requests: [] });
    const { container } = render(<SkillInstallConsent sessionId="session_ava_1" refreshKey={0} />);

    await waitFor(() => expect(listInstallRequests).toHaveBeenCalled());
    expect(container.innerHTML).toBe("");
  });
});
