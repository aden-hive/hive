/**
 * Open the settings dialog at a section from anywhere in the app. AppHeader
 * owns the dialog and listens; a component that wants it (the chat's
 * "no model" notice, say) just calls openSettings("byok").
 */
export type SettingsSection = "profile" | "byok" | "mcp" | "cloud";

const EVENT = "hive:open-settings";

export function openSettings(section: SettingsSection = "profile"): void {
  window.dispatchEvent(new CustomEvent<SettingsSection>(EVENT, { detail: section }));
}

/** Call `handler` whenever something asks for the settings dialog. Returns the unsubscribe. */
export function onOpenSettings(handler: (section: SettingsSection) => void): () => void {
  const listener = (event: Event) => handler((event as CustomEvent<SettingsSection>).detail);
  window.addEventListener(EVENT, listener);
  return () => window.removeEventListener(EVENT, listener);
}
