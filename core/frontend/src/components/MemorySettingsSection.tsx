import { useEffect, useState } from "react";
import { Check, Loader2 } from "lucide-react";
import { configApi, type MemorySettings } from "@/api/config";

/** What each choice the server offers means; a choice not listed here shows under its own name. */
const RECALL_LABELS: Record<string, { title: string; description: string }> = {
  index: {
    title: "Note list",
    description: "She sees each note's name and one-line description, and opens the ones she needs. No extra model calls.",
  },
  wait: {
    title: "Pick before answering",
    description: "A model picks the notes for each message before she answers, adding a couple of seconds to each reply.",
  },
  background: {
    title: "Pick while answering",
    description: "The same pick, made while she answers, so the notes often arrive a message late.",
  },
};

const REFLECTION_LABELS: Record<string, { title: string; description: (workerModel: string | null) => string }> = {
  worker: {
    title: "Worker model",
    description: (workerModel) =>
      workerModel
        ? `Notes are written on ${workerModel}.`
        : "No worker model is set, so notes are written on each queen's own model.",
  },
  main: {
    title: "Queen's own model",
    description: () => "Notes are written on the model each queen chats with.",
  },
};

type Field = "recall_mode" | "reflection_model";

interface Props {
  /** Leave Settings for the Models page, where the worker model is set. */
  onOpenModels: () => void;
}

export function MemorySettingsSection({ onOpenModels }: Props) {
  const [settings, setSettings] = useState<MemorySettings | null>(null);
  // undefined while loading; null when no worker model is set.
  const [workerModel, setWorkerModel] = useState<string | null | undefined>(undefined);
  const [loadError, setLoadError] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    configApi
      .getMemorySettings()
      .then((r) => live && setSettings(r.memory))
      .catch(() => live && setLoadError(true));
    configApi
      .getLlmSections()
      .then((s) => live && setWorkerModel(s.worker_llm?.model || null))
      .catch(() => live && setWorkerModel(null));
    return () => {
      live = false;
    };
  }, []);

  const choose = (field: Field, value: string) => {
    if (!settings || settings[field] === value) return;
    const before = settings;
    setSettings({ ...settings, [field]: value });
    setSaveError(null);
    configApi
      .setMemorySettings({ [field]: value })
      .then((r) => setSettings(r.memory))
      .catch((e: unknown) => {
        setSettings(before);
        setSaveError(e instanceof Error ? e.message : "Couldn't save the change.");
      });
  };

  return (
    <>
      <div>
        <h3 className="text-base font-semibold text-foreground">Memory</h3>
        <p className="text-xs text-muted-foreground mt-1 leading-relaxed">
          How a queen's memory notes reach her, and which model writes them. Running sessions follow from
          their next message.
        </p>
      </div>

      {loadError && <p className="text-xs text-red-500">Couldn't load the memory settings.</p>}
      {!settings && !loadError && <Loader2 className="w-4 h-4 animate-spin text-muted-foreground" />}

      {settings && (
        <>
          <ChoiceGroup
            label="How notes reach her"
            choices={settings.recall_modes.map((mode) => ({
              value: mode,
              title: RECALL_LABELS[mode]?.title ?? mode,
              description: RECALL_LABELS[mode]?.description ?? "",
            }))}
            selected={settings.recall_mode}
            onChoose={(v) => choose("recall_mode", v)}
            note={
              settings.recall_mode_env
                ? `The server's HIVE_MEMORY_RECALL is set to "${settings.recall_mode_env}", which overrides this choice.`
                : null
            }
          />

          <ChoiceGroup
            label="Model that writes notes"
            choices={settings.reflection_models.map((model) => ({
              value: model,
              title: REFLECTION_LABELS[model]?.title ?? model,
              description: REFLECTION_LABELS[model]?.description(workerModel ?? null) ?? "",
              action:
                model === "worker" && workerModel === null
                  ? { label: "Set one on the Models page → Workers", onClick: onOpenModels }
                  : undefined,
            }))}
            selected={settings.reflection_model}
            onChoose={(v) => choose("reflection_model", v)}
          />

          {saveError && <p className="text-xs text-red-500">{saveError}</p>}
        </>
      )}
    </>
  );
}

interface Choice {
  value: string;
  title: string;
  description: string;
  action?: { label: string; onClick: () => void };
}

function ChoiceGroup({
  label,
  choices,
  selected,
  onChoose,
  note,
}: {
  label: string;
  choices: Choice[];
  selected: string;
  onChoose: (value: string) => void;
  note?: string | null;
}) {
  return (
    <div>
      <p className="text-[11px] font-medium text-muted-foreground/80 uppercase tracking-wider mb-1.5">{label}</p>
      <div role="radiogroup" aria-label={label} className="flex flex-col gap-1.5">
        {choices.map((c) => {
          const on = c.value === selected;
          return (
            <div
              key={c.value}
              className={`rounded-md border px-3 py-2 transition-colors ${on ? "border-primary/50 bg-primary/10" : "border-border/50 bg-muted/10 hover:bg-muted/20"}`}
            >
              <button
                type="button"
                role="radio"
                aria-checked={on}
                onClick={() => onChoose(c.value)}
                className="w-full text-left flex items-start gap-2"
              >
                <span
                  className={`mt-0.5 w-3.5 h-3.5 flex-shrink-0 rounded-full border flex items-center justify-center ${on ? "border-primary bg-primary text-primary-foreground" : "border-border"}`}
                >
                  {on && <Check className="w-2.5 h-2.5" />}
                </span>
                <span className="min-w-0">
                  <span className="block text-[12px] font-medium text-foreground">{c.title}</span>
                  {c.description && (
                    <span className="block text-[11px] text-muted-foreground leading-snug">{c.description}</span>
                  )}
                </span>
              </button>
              {c.action && (
                <button
                  type="button"
                  onClick={c.action.onClick}
                  className="ml-[1.375rem] mt-1 text-[11px] font-medium text-primary underline-offset-2 hover:underline"
                >
                  {c.action.label}
                </button>
              )}
            </div>
          );
        })}
      </div>
      {note && <p className="text-[11px] text-amber-600 dark:text-amber-400 mt-1.5">{note}</p>}
    </div>
  );
}
