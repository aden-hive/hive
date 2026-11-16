import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

const own = { provider: "openai", model: "archivist-1", api_base: "https://models.invalid/v1", api_key: "sk-ownkey" };
const getLlm = vi.fn();
const setLlm = vi.fn();
vi.mock("@/api/queens", () => ({ queensApi: { getLlm: (id: string) => getLlm(id), setLlm: (id: string, s: unknown) => setLlm(id, s) } }));
vi.mock("@/api/config", () => ({ configApi: { getProviderLibrary: async () => ({ library: { Archive: own } }) } }));
const overview = {
  slots: { llm: null, worker_llm: null, vision_fallback: null },
  judge: { configured: false, model: null, api_base: null },
  queens: [],
  providers: [],
  endpoints: [{ name: "magpie", api_base: "http://127.0.0.1:3425/v1", builtin: true, has_key: false, running: true }],
  subscriptions: [],
};
const setSlot = vi.fn();
vi.mock("@/api/models", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/models")>()),
  modelsApi: {
    overview: async () => overview,
    endpointModels: async () => ({ models: [{ id: "kimi/k3", max_context_tokens: 262144 }] }),
    setSlot: (slot: string, choice: unknown) => setSlot(slot, choice),
    clearSlot: async () => ({}),
  },
}));

import QueenModelSection from "./QueenModelSection";

describe("QueenModelSection", () => {
  beforeEach(() => {
    getLlm.mockReset();
    setLlm.mockReset();
    setSlot.mockReset();
  });

  it("shows the main model until she has her own, and takes a saved provider", async () => {
    getLlm.mockResolvedValue({ queen_id: "queen_x", section: null, default_model: "anthropic/claude-x" });
    setLlm.mockResolvedValue({ queen_id: "queen_x", section: own, sessions_switched: 1 });
    render(<QueenModelSection queenId="queen_x" />);

    expect(await screen.findByText(/anthropic\/claude-x/)).toBeTruthy();
    fireEvent.click(screen.getByText("Advanced"));
    fireEvent.change(screen.getByLabelText("Use a saved provider"), { target: { value: "Archive" } });

    await waitFor(() => expect(screen.getByText("archivist-1 · https://models.invalid/v1 · key ****nkey")).toBeTruthy());
    expect(setLlm).toHaveBeenCalledWith("queen_x", own);
  });

  it("edits her model as JSON and returns her to the main model", async () => {
    getLlm.mockResolvedValue({ queen_id: "queen_x", section: own, default_model: "anthropic/claude-x" });
    setLlm.mockImplementation(async (_id: string, s: unknown) => ({ queen_id: "queen_x", section: s, sessions_switched: 0 }));
    render(<QueenModelSection queenId="queen_x" />);

    fireEvent.click(await screen.findByText("Advanced"));
    fireEvent.click(screen.getByText("Edit"));
    fireEvent.change(screen.getByLabelText("Her model, as JSON"), { target: { value: "not json" } });
    fireEvent.click(screen.getByText("Save"));
    expect(screen.getByText("Not valid JSON")).toBeTruthy();
    expect(setLlm).not.toHaveBeenCalled();

    fireEvent.click(screen.getByText("Cancel"));
    fireEvent.click(screen.getByRole("button", { name: "Use the main model" }));
    await waitFor(() => expect(screen.getByText(/She uses the main model/)).toBeTruthy());
    expect(setLlm).toHaveBeenCalledWith("queen_x", null);
  });

  it("gives her a model from the same list as every slot, an endpoint's included", async () => {
    getLlm.mockResolvedValue({ queen_id: "queen_x", section: null, default_model: "anthropic/claude-x" });
    setSlot.mockResolvedValue({ slot: "queen:queen_x", summary: null, sessions_switched: 1 });
    render(<QueenModelSection queenId="queen_x" />);

    fireEvent.click(await screen.findByRole("button", { name: "Her model" }));
    fireEvent.click(await screen.findByText("kimi/k3"));

    await waitFor(() => expect(setSlot).toHaveBeenCalledWith("queen:queen_x", { source: "endpoint", endpoint: "magpie", model: "kimi/k3" }));
  });
});
