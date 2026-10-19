import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import ModelErrorCard, { parseModelError } from "./ModelErrorCard";
import { onOpenSettings } from "@/lib/settings-events";

const KEYLESS =
  "[Error: LLM call failed: Stream error: litellm.AuthenticationError: AuthenticationError: OpenAIException - The api_key client option must be set. Please try again.]";

describe("parseModelError", () => {
  it("reads a failed call and tells a key problem from other errors", () => {
    expect(parseModelError(KEYLESS)).toEqual({
      detail: "Stream error: litellm.AuthenticationError: AuthenticationError: OpenAIException - The api_key client option must be set",
      keyProblem: true,
    });
    expect(parseModelError("[Error: LLM call failed: 502 Bad Gateway. Please try again.]")?.keyProblem).toBe(false);
  });

  it("leaves ordinary text alone", () => {
    expect(parseModelError("I hit an [Error: LLM call failed: x] once, it's fine now.")).toBeNull();
  });
});

describe("ModelErrorCard", () => {
  it("links to the model settings and folds the raw error away", () => {
    const opened: string[] = [];
    const stop = onOpenSettings((section) => opened.push(section));
    render(<ModelErrorCard error={parseModelError(KEYLESS)!} />);

    expect(screen.queryByText(/client option must be set/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /details/i }));
    expect(screen.getByText(/client option must be set/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /set up a model/i }));
    expect(opened).toEqual(["byok"]);
    stop();
  });
});
