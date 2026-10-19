export interface UpdateAvailable {
  /** Latest published version, e.g. "0.2.14". */
  latest: string;
  /** Best download URL for the current OS. */
  downloadUrl: string;
}

export interface UpdateRequired {
  /** Latest published version to upgrade to, e.g. "0.2.30". */
  latest: string;
  /** Oldest still-supported version reported by the site, e.g. "0.2.28". */
  minVersion: string;
  /** Best download URL for the current OS. */
  downloadUrl: string;
}

/**
 * Desktop-only update check. The web SPA is served fresh on every load and
 * has no installer to update, so this always reports "up to date" (null).
 */
export function useLatestVersion(): UpdateAvailable | null {
  return null;
}

/**
 * Desktop-only "update required" gate. Never fires in web mode.
 */
export function useUpdateRequired(): UpdateRequired | null {
  return null;
}
