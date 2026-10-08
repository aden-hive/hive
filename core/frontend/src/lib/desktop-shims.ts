/**
 * Web replacements for the former Electron native desktop bridge
 * (the `window` `.hive` `.*` IPC surface that no longer exists).
 *
 * The desktop shell used to hand file saves / opens / clipboard work to the
 * main process. In the pure web SPA those become standard browser operations:
 * object-URL downloads, `window.open`, and the async Clipboard API. Every
 * helper returns the same `{ ok, cancelled?, error? }` shape the old bridge
 * used so call sites keep their success/error handling.
 */

import { apiUrl } from "@/api/client";

export interface SaveResult {
  ok: boolean;
  cancelled?: boolean;
  error?: string;
  targetPath?: string;
}

type DownloadData = ArrayBuffer | ArrayBufferView | Blob | string;

function triggerDownload(href: string, filename: string, revoke?: () => void): SaveResult {
  try {
    const a = document.createElement("a");
    a.href = href;
    a.download = filename;
    a.rel = "noopener";
    document.body.appendChild(a);
    a.click();
    a.remove();
    revoke?.();
    return { ok: true };
  } catch (e) {
    revoke?.();
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
  }
}

/**
 * Save in-memory data (bytes, a Blob, or text) to a file via a temporary
 * `<a download>` + object URL.
 */
export function downloadBlob(
  data: DownloadData,
  filename: string,
  mimeType?: string,
): SaveResult {
  const blob = data instanceof Blob ? data : new Blob([data], mimeType ? { type: mimeType } : undefined);
  const url = URL.createObjectURL(blob);
  return triggerDownload(url, filename, () => URL.revokeObjectURL(url));
}

/**
 * Save the resource at `url` (typically an `apiUrl(...)` route the runtime
 * serves) using the browser's native download, with a suggested filename.
 */
export function downloadUrl(url: string, filename: string): SaveResult {
  return triggerDownload(url, filename);
}

/** Save CSV text as a `.csv` file. */
export function saveCsv(csv: string, suggestedName: string): SaveResult {
  const filename = suggestedName.toLowerCase().endsWith(".csv") ? suggestedName : `${suggestedName}.csv`;
  return downloadBlob(csv, filename, "text/csv;charset=utf-8");
}

/**
 * Open a runtime attachment in a new browser tab. `url` is expected to already
 * be a fetchable route (resolved via `apiUrl(...)`) or a `data:`/`http(s)` URL.
 */
export function openAttachment(url: string): SaveResult {
  try {
    window.open(url, "_blank", "noopener");
    return { ok: true };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
  }
}

/** Save an attachment served at `url` under `filename`. */
export function saveAttachmentAs(url: string, filename?: string): SaveResult {
  return downloadUrl(url, filename || "download");
}

/**
 * Copy the image at `url` to the clipboard via the async Clipboard API.
 * Falls back to downloading the image when `ClipboardItem` is unavailable.
 */
export async function copyImageToClipboard(url: string): Promise<SaveResult> {
  try {
    const res = await fetch(url);
    const blob = await res.blob();
    const ClipboardItemCtor = (window as unknown as { ClipboardItem?: typeof ClipboardItem }).ClipboardItem;
    if (ClipboardItemCtor && navigator.clipboard && "write" in navigator.clipboard) {
      await navigator.clipboard.write([new ClipboardItemCtor({ [blob.type]: blob })]);
      return { ok: true };
    }
    // No clipboard-image support: fall back to a download so the action
    // still yields the image the user asked for.
    return downloadBlob(blob, "image", blob.type);
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
  }
}

/**
 * Web equivalent of the old native "print to PDF". Opens the fully-rendered
 * HTML document in a new window and triggers the browser print dialog, where
 * the user can choose "Save as PDF". Returns `cancelled` when the popup is
 * blocked so callers can fall back.
 */
export function printHtmlToPdf(html: string): SaveResult {
  const win = window.open("", "_blank");
  if (!win) return { ok: false, cancelled: true, error: "popup_blocked" };
  win.document.open();
  win.document.write(html);
  win.document.close();
  win.focus();
  // Give the new document a tick to lay out before printing.
  win.setTimeout(() => {
    win.print();
  }, 250);
  return { ok: true };
}

/** Open an external URL in a new tab (former `openExternal`). */
export function openExternal(url: string): void {
  window.open(url, "_blank", "noopener");
}

export { apiUrl };
