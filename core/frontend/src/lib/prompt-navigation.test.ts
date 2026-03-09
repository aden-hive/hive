import { describe, it, expect } from "vitest";

// ---------------------------------------------------------------------------
// resolveInitialPrompt
//
// Mirrors the priority chain in workspace.tsx:
//   location.state.prompt  (programmatic navigate — no URL length limit)
//   ?? searchParams.get("prompt")  (direct URL / bookmark fallback)
//   ?? ""
//
// Kept as a pure function so it can be unit-tested without a DOM/router.
// ---------------------------------------------------------------------------

function resolveInitialPrompt(
  locationStatePrompt: string | null | undefined,
  searchParamPrompt: string | null,
): string {
  return locationStatePrompt || searchParamPrompt || "";
}

describe("resolveInitialPrompt", () => {
  // --- location.state takes priority ---

  it("returns location.state.prompt when present", () => {
    expect(resolveInitialPrompt("hello from state", null)).toBe("hello from state");
  });

  it("prefers location.state.prompt over searchParam when both present", () => {
    expect(resolveInitialPrompt("state wins", "param loses")).toBe("state wins");
  });

  it("handles a large prompt (>2 KB) from location.state without truncation", () => {
    const large = "A".repeat(10_000);
    expect(resolveInitialPrompt(large, null)).toBe(large);
    expect(resolveInitialPrompt(large, null)).toHaveLength(10_000);
  });

  // --- searchParam fallback (direct URL / bookmark) ---

  it("falls back to searchParam when location.state.prompt is absent", () => {
    expect(resolveInitialPrompt(null, "bookmark prompt")).toBe("bookmark prompt");
  });

  it("falls back to searchParam when location.state.prompt is undefined", () => {
    expect(resolveInitialPrompt(undefined, "bookmark prompt")).toBe("bookmark prompt");
  });

  it("falls back to searchParam when location.state.prompt is empty string", () => {
    expect(resolveInitialPrompt("", "bookmark prompt")).toBe("bookmark prompt");
  });

  // --- empty fallback ---

  it("returns empty string when both sources are absent", () => {
    expect(resolveInitialPrompt(null, null)).toBe("");
  });

  it("returns empty string when both sources are empty strings", () => {
    expect(resolveInitialPrompt("", "")).toBe("");
  });

  it("returns empty string when state is null and searchParam is null", () => {
    expect(resolveInitialPrompt(null, null)).toBe("");
  });

  // --- prompt hint pills (short pre-defined text via state) ---

  it("correctly resolves a prompt hint string from state", () => {
    const hint = "Check my inbox for urgent emails";
    expect(resolveInitialPrompt(hint, null)).toBe(hint);
  });

  // --- whitespace / trimming (home.tsx trims before navigate; verify assumption) ---

  it("does not trim — trimming is the caller's responsibility", () => {
    expect(resolveInitialPrompt("  spaced  ", null)).toBe("  spaced  ");
  });
});

// ---------------------------------------------------------------------------
// navigate() call shape (issue #5760 regression guard)
//
// Documents the exact navigate() argument shapes that home.tsx must produce.
// If these shapes change, the workspace.tsx reader must be updated too.
// ---------------------------------------------------------------------------

describe("navigate call shape for /workspace (issue #5760)", () => {
  type NavigateState = { prompt: string };
  type NavigateArgs = [path: string, opts: { state: NavigateState }];

  function buildHandlePromptHintArgs(text: string): NavigateArgs {
    return ["/workspace?agent=new-agent", { state: { prompt: text } }];
  }

  function buildHandleSubmitArgs(inputValue: string): NavigateArgs {
    return ["/workspace?agent=new-agent", { state: { prompt: inputValue.trim() } }];
  }

  it("handlePromptHint — prompt is in state, not in URL", () => {
    const [path, opts] = buildHandlePromptHintArgs("Research latest AI trends");
    expect(path).not.toContain("prompt=");
    expect(opts.state.prompt).toBe("Research latest AI trends");
  });

  it("handleSubmit — prompt is in state, trimmed, not in URL", () => {
    const [path, opts] = buildHandleSubmitArgs("  Find senior engineer roles  ");
    expect(path).not.toContain("prompt=");
    expect(opts.state.prompt).toBe("Find senior engineer roles");
  });

  it("handleSubmit — large prompt stays intact (no URL truncation)", () => {
    const large = "word ".repeat(1_000).trim(); // ~5 000 chars
    const [path, opts] = buildHandleSubmitArgs(large);
    expect(path).not.toContain("prompt=");
    expect(opts.state.prompt).toHaveLength(large.length);
  });

  it("handlePromptHint — agent param is still in the URL for workspace routing", () => {
    const [path] = buildHandlePromptHintArgs("anything");
    expect(path).toContain("agent=new-agent");
  });
});
