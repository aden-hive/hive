import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

const model = { loading: false, hasApiKey: false };
vi.mock("@/context/ModelContext", () => ({ useModelOptional: () => model }));

import NoModelNotice from "./NoModelNotice";
import { onOpenSettings } from "@/lib/settings-events";

describe("NoModelNotice", () => {
  beforeEach(() => {
    model.loading = false;
    model.hasApiKey = false;
  });

  it("links to the AI model settings when no model is set up", () => {
    const opened: string[] = [];
    const stop = onOpenSettings((section) => opened.push(section));
    render(<NoModelNotice />);

    fireEvent.click(screen.getByRole("button", { name: /set up a model/i }));

    expect(screen.getByRole("status").textContent).toContain("No AI model yet.");
    expect(opened).toEqual(["byok"]);
    stop();
  });

  it.each([
    ["a model works", { loading: false, hasApiKey: true }],
    ["the config is still loading", { loading: true, hasApiKey: false }],
  ])("stays out of the way when %s", (_, state) => {
    Object.assign(model, state);
    const { container } = render(<NoModelNotice />);
    expect(container.innerHTML).toBe("");
  });
});
