import { useState, type ComponentType } from "react";
import { AlertCircle, Check, Compass, Drama, EyeOff, Loader2, Pencil, Plus, X, Zap } from "lucide-react";
import { ApiError } from "@/api/client";
import type { QueenPersona } from "@/api/queens";

/**
 * What lies under her persona text: the profile.yaml pillars her identity prompt is built from
 * besides it. Each map offers the fields the prompt reads (any others it holds are kept and shown
 * too); the triggers are a list of "when this happens, she does that".
 */

type MapKey = "hidden_background" | "psychological_profile" | "world_lore";
type PillarKey = MapKey | "behavior_triggers";
type Trigger = { trigger: string; reaction: string };

type Pillar = { key: PillarKey; title: string; note: string; icon: ComponentType<{ className?: string }>; sealed?: boolean; fields?: string[] };

const PILLARS: Pillar[] = [
  {
    key: "hidden_background",
    title: "Hidden background",
    note: "Moves her, and is never shown to anyone",
    icon: EyeOff,
    sealed: true,
    fields: ["past_wound", "deep_motive", "behavioral_mapping"],
  },
  {
    key: "psychological_profile",
    title: "Psychological profile",
    note: "The masks she wears, and what she is not",
    icon: Drama,
    fields: ["social_masks", "anti_stereotype"],
  },
  { key: "behavior_triggers", title: "Triggers", note: "What sets her off, and how she answers", icon: Zap },
  { key: "world_lore", title: "World lore", note: "Where she lives, and the words she uses", icon: Compass, fields: ["habitat", "lexicon"] },
];

function label(key: string): string {
  const words = key.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

function rowsFor(text: string): number {
  return Math.min(10, Math.max(2, text.split("\n").length, Math.ceil(text.length / 80)));
}

export default function PersonaPillars({
  persona,
  onSave,
}: {
  persona: QueenPersona;
  onSave: (fields: Partial<Record<keyof QueenPersona, unknown>>) => Promise<void>;
}) {
  const [editing, setEditing] = useState<PillarKey | null>(null);
  const [fields, setFields] = useState<[string, string][]>([]);
  const [triggers, setTriggers] = useState<Trigger[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const has = (key: PillarKey) =>
    key === "behavior_triggers" ? (persona.behavior_triggers?.length ?? 0) > 0 : Object.keys(persona[key] ?? {}).length > 0;

  const open = (pillar: Pillar) => {
    setError(null);
    if (pillar.key === "behavior_triggers") {
      const current = persona.behavior_triggers ?? [];
      setTriggers(current.length ? current.map((t) => ({ ...t })) : [{ trigger: "", reaction: "" }]);
    } else {
      const current = persona[pillar.key] ?? {};
      const known = pillar.fields ?? [];
      setFields([...known, ...Object.keys(current).filter((k) => !known.includes(k))].map((k) => [k, current[k] ?? ""]));
    }
    setEditing(pillar.key);
  };

  const save = async () => {
    if (!editing) return;
    let value: unknown;
    if (editing === "behavior_triggers") {
      const kept = triggers.map((t) => ({ trigger: t.trigger.trim(), reaction: t.reaction.trim() })).filter((t) => t.trigger && t.reaction);
      value = kept.length ? kept : null;
    } else {
      const kept = fields.map(([k, v]) => [k, v.trim()] as const).filter(([, v]) => v);
      // Emptied out, the pillar goes rather than stay as a husk.
      value = kept.length ? Object.fromEntries(kept) : null;
    }
    setSaving(true);
    try {
      await onSave({ [editing]: value });
      setEditing(null);
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't save");
    } finally {
      setSaving(false);
    }
  };

  const shown = PILLARS.filter((p) => has(p.key) || editing === p.key);
  const missing = PILLARS.filter((p) => !has(p.key) && editing !== p.key);

  const editor = (pillar: Pillar) => (
    <>
      {pillar.key === "behavior_triggers" ? (
        <div className="qp-triggers">
          <div className="qp-trigger-edit qp-field-label" aria-hidden>
            <span>When</span>
            <span>She</span>
          </div>
          {triggers.map((t, i) => (
            <div key={i} className="qp-trigger-edit">
              <input
                className="qp-input"
                aria-label={`Trigger ${i + 1}`}
                value={t.trigger}
                onChange={(e) => setTriggers(triggers.map((x, j) => (j === i ? { ...x, trigger: e.target.value } : x)))}
              />
              <textarea
                className="qp-input"
                aria-label={`Her reaction ${i + 1}`}
                rows={rowsFor(t.reaction)}
                value={t.reaction}
                onChange={(e) => setTriggers(triggers.map((x, j) => (j === i ? { ...x, reaction: e.target.value } : x)))}
              />
              <button className="qp-icon-btn" aria-label={`Remove trigger ${i + 1}`} onClick={() => setTriggers(triggers.filter((_, j) => j !== i))}>
                <X className="w-3.5 h-3.5" />
              </button>
            </div>
          ))}
          <div>
            <button className="qp-add" onClick={() => setTriggers([...triggers, { trigger: "", reaction: "" }])}>
              <Plus className="w-3.5 h-3.5" /> Add a trigger
            </button>
          </div>
        </div>
      ) : (
        <div className="qp-fields">
          {fields.map(([key, value], i) => (
            <label key={key} className="block">
              <span className="qp-field-label">{label(key)}</span>
              <textarea
                className="qp-input"
                aria-label={`${pillar.title}: ${label(key)}`}
                rows={rowsFor(value)}
                value={value}
                onChange={(e) => setFields(fields.map((f, j) => (j === i ? [f[0], e.target.value] : f)))}
              />
            </label>
          ))}
        </div>
      )}
      <div className="qp-edit-foot">
        <span className="qp-hint">Empty fields are left out</span>
        <div>
          <button className="qp-btn" data-tone="quiet" data-size="sm" onClick={() => setEditing(null)} disabled={saving}>
            Cancel
          </button>
          <button className="qp-btn" data-tone="primary" data-size="sm" onClick={() => void save()} disabled={saving}>
            {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Check className="w-3.5 h-3.5" />}
            Save
          </button>
        </div>
      </div>
      {error && (
        <p className="qp-error mt-2">
          <AlertCircle className="w-3.5 h-3.5" /> {error}
        </p>
      )}
    </>
  );

  const view = (pillar: Pillar) =>
    pillar.key === "behavior_triggers" ? (
      <ul className="qp-triggers">
        {(persona.behavior_triggers ?? []).map((t, i) => (
          <li key={i} className="qp-trigger">
            <span>{t.trigger}</span>
            <span className="qp-trigger-arrow" aria-hidden>
              →
            </span>
            <span>{t.reaction}</span>
          </li>
        ))}
      </ul>
    ) : (
      <dl className="qp-fields">
        {Object.entries(persona[pillar.key] ?? {}).map(([key, value]) => (
          <div key={key}>
            <dt className="qp-field-label">{label(key)}</dt>
            <dd className="qp-field-text">{value}</dd>
          </div>
        ))}
      </dl>
    );

  return (
    <>
      {shown.length > 0 && (
        <div className="qp-pillars">
          {shown.map((pillar) => {
            const Icon = pillar.icon;
            const isEditing = editing === pillar.key;
            return (
              <article key={pillar.key} className="qp-card qp-pillar" data-sealed={pillar.sealed ? "" : undefined} data-editing={isEditing ? "" : undefined}>
                <header className="qp-pillar-head">
                  <span className="qp-pillar-icon">
                    <Icon className="w-4 h-4" />
                  </span>
                  <div className="min-w-0">
                    <h4 className="qp-pillar-title">{pillar.title}</h4>
                    <p className="qp-pillar-note">{pillar.note}</p>
                  </div>
                </header>
                {isEditing ? editor(pillar) : view(pillar)}
                {!isEditing && (
                  <div className="qp-chapter-tools">
                    <button className="qp-icon-btn" onClick={() => open(pillar)} title={`Edit ${pillar.title.toLowerCase()}`} aria-label={`Edit ${pillar.title.toLowerCase()}`}>
                      <Pencil className="w-3.5 h-3.5" />
                    </button>
                  </div>
                )}
              </article>
            );
          })}
        </div>
      )}
      {missing.length > 0 && (
        <div className="qp-add-row">
          {missing.map((pillar) => (
            <button key={pillar.key} className="qp-add" onClick={() => open(pillar)}>
              <Plus className="w-3.5 h-3.5" /> {pillar.title}
            </button>
          ))}
        </div>
      )}
    </>
  );
}
