/**
 * Report a problem with a session.
 *
 * Local-mode flow (no cloud upload):
 *   1. local runtime packages the session → credential-scrubbed tar.gz on disk
 *      (full screenshots kept) + drops a user_report.json marker (training
 *      "bad" signal). Returns the on-disk path + metadata.
 *   2. optionally save a local copy via a browser download.
 */

import { api, apiUrl } from "./client";
import { downloadUrl } from "@/lib/desktop-shims";

export type Severity = "low" | "medium" | "high" | "critical";

interface PackagedBundle {
  ok: boolean;
  filename: string;
  bundle_path: string;
  size: number;
  sha256: string;
  content_type: string;
}

export interface SubmitResult {
  savedTo?: string;
  bytes: number;
}

/** Step 1: local runtime builds the scrubbed bundle + writes the marker. */
async function packageBundle(
  sessionId: string,
  description: string,
  severity: Severity,
): Promise<PackagedBundle> {
  return api.post<PackagedBundle>(
    `/sessions/${encodeURIComponent(sessionId)}/report-bundle`,
    { description, severity },
  );
}

/**
 * Submit: package the scrubbed bundle on the runtime, then (optionally) offer
 * it to the user as a browser download served from the runtime.
 */
export async function submitSessionReport(opts: {
  sessionId: string;
  description: string;
  severity: Severity;
  saveLocal: boolean;
}): Promise<SubmitResult> {
  const bundle = await packageBundle(opts.sessionId, opts.description, opts.severity);

  let savedTo: string | undefined;
  if (opts.saveLocal) {
    downloadUrl(apiUrl(bundle.bundle_path), bundle.filename);
    savedTo = bundle.filename;
  }

  return { savedTo, bytes: bundle.size };
}
