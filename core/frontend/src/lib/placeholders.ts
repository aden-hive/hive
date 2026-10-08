/**
 * Fill-in placeholders in prompt/template text use double-brace syntax:
 *   Monitor my inbox ({{your email}}) ...
 *
 * Community prompts ship these so a user substitutes their own details. The
 * composer renders each `{{…}}` as an inline, editable pill (see
 * SkillTextEditor) prefilled from a local cache or the user's /me profile, so
 * there's no send-time dialog — the value the user sees is what gets sent.
 *
 * Editor token shapes:
 *   {{label}}          — unfilled (the pill shows the label as a hint)
 *   {{label::value}}   — filled with `value`
 *
 * On send, `resolvePlaceholders` collapses tokens to their values.
 */

import { userStorage } from "@/lib/userStorage";

// label = group 1 (no colon), value = group 2 (optional, after `::`).
const PH_RE = /\{\{\s*([^}:]+?)\s*(?:::\s*([^}]*?))?\s*\}\}/g;

/** Normalized cache/lookup key for a placeholder label. */
export function normLabel(label: string): string {
  return label.trim().toLowerCase();
}

/**
 * Inject a value into every still-empty `{{label}}` from `lookup(label)`.
 * Tokens that already carry a value are left untouched. Used when seeding a
 * prompt into the editor so emails/websites appear pre-filled.
 */
export function prefillPlaceholders(
  text: string,
  lookup: (label: string) => string | undefined | null,
): string {
  return text.replace(PH_RE, (whole, label: string, value?: string) => {
    const l = label.trim();
    if (value != null && value.trim() !== "") return whole; // already filled
    const v = lookup(l);
    return v ? `{{${l}::${v}}}` : `{{${l}}}`;
  });
}

/**
 * Collapse tokens to their values for sending. `{{label::value}}` → `value`;
 * an unfilled placeholder is left as the bare `{{label}}` so the queen still
 * sees the placeholder (rather than an empty gap) and can ask for / infer it.
 */
export function resolvePlaceholders(text: string): string {
  return text.replace(PH_RE, (_whole, label: string, value?: string) => {
    const v = value != null ? value.trim() : "";
    return v !== "" ? v : `{{${label.trim()}}}`;
  });
}

/** Map of normalized label → filled value, for persisting to the cache. */
export function collectPlaceholderValues(text: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const m of text.matchAll(PH_RE)) {
    const value = (m[2] ?? "").trim();
    if (value) out[normLabel(m[1])] = value;
  }
  return out;
}

// --- local cache of previously-entered values ------------------------------

const CACHE_KEY = "promptPlaceholderValues";

export function readPlaceholderCache(): Record<string, string> {
  return userStorage.get<Record<string, string>>(CACHE_KEY, {});
}

/** Merge new values into the cache (keyed by normalized label). */
export function cachePlaceholderValues(values: Record<string, string>): void {
  if (!Object.keys(values).length) return;
  userStorage.set(CACHE_KEY, { ...readPlaceholderCache(), ...values });
}
