import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { MemorySettings } from "@/api/config";

const getMemorySettings = vi.fn();
const setMemorySettings = vi.fn();
const getLlmSections = vi.fn();
vi.mock("@/api/config", () => ({
  configApi: {
    getMemorySettings: () => getMemorySettings(),
    setMemorySettings: (m: unknown) => setMemorySettings(m),
    getLlmSections: () => getLlmSections(),
  },
}));

import { MemorySettingsSection } from "./MemorySettingsSection";

function settings(over: Partial<MemorySettings> = {}): MemorySettings {
  return {
    recall_mode: "index",
    recall_modes: ["index", "wait", "background"],
    recall_mode_env: null,
    reflection_model: "worker",
    reflection_models: ["worker", "main"],
    ...over,
  };
}

function group(name: string) {
  return within(screen.getByRole("radiogroup", { name }));
}

beforeEach(() => {
  getMemorySettings.mockResolvedValue({ memory: settings() });
  getLlmSections.mockResolvedValue({ llm: { model: "main-model" }, worker_llm: { model: "worker-model" } });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("MemorySettingsSection", () => {
  it("shows the saved choices and the worker model", async () => {
    render(<MemorySettingsSection onOpenModels={() => {}} />);

    await waitFor(() => expect(group("How notes reach her").getByRole("radio", { name: /Note list/ })).toHaveAttribute("aria-checked", "true"));
    expect(group("How notes reach her").getAllByRole("radio")).toHaveLength(3);
    const worker = group("Model that writes notes").getByRole("radio", { name: /Worker model/ });
    expect(worker).toHaveAttribute("aria-checked", "true");
    expect(worker).toHaveTextContent("Notes are written on worker-model.");
  });

  it("saves a choice and shows what the server saved", async () => {
    setMemorySettings.mockResolvedValue({ memory: settings({ reflection_model: "main" }) });
    render(<MemorySettingsSection onOpenModels={() => {}} />);
    const main = await waitFor(() => group("Model that writes notes").getByRole("radio", { name: /Queen's own model/ }));

    fireEvent.click(main);

    expect(setMemorySettings).toHaveBeenCalledWith({ reflection_model: "main" });
    await waitFor(() => expect(main).toHaveAttribute("aria-checked", "true"));
  });

  it("puts the choice back and says why when saving fails", async () => {
    setMemorySettings.mockRejectedValue(new Error("recall_mode must be one of: index, wait, background"));
    render(<MemorySettingsSection onOpenModels={() => {}} />);
    const wait = await waitFor(() => group("How notes reach her").getByRole("radio", { name: /Pick before answering/ }));

    fireEvent.click(wait);

    await screen.findByText("recall_mode must be one of: index, wait, background");
    expect(wait).toHaveAttribute("aria-checked", "false");
    expect(group("How notes reach her").getByRole("radio", { name: /Note list/ })).toHaveAttribute("aria-checked", "true");
  });

  it("points to the Models page when no worker model is set", async () => {
    getLlmSections.mockResolvedValue({ llm: { model: "main-model" }, worker_llm: null });
    const onOpenModels = vi.fn();
    render(<MemorySettingsSection onOpenModels={onOpenModels} />);

    fireEvent.click(await screen.findByRole("button", { name: "Set one on the Models page → Workers" }));

    expect(onOpenModels).toHaveBeenCalledOnce();
    expect(screen.getByText("No worker model is set, so notes are written on each queen's own model.")).toBeInTheDocument();
  });

  it("says when the server's env var overrides the recall choice", async () => {
    getMemorySettings.mockResolvedValue({ memory: settings({ recall_mode: "wait", recall_mode_env: "wait" }) });
    render(<MemorySettingsSection onOpenModels={() => {}} />);

    expect(
      await screen.findByText(`The server's HIVE_MEMORY_RECALL is set to "wait", which overrides this choice.`),
    ).toBeInTheDocument();
  });
});
