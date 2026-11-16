/**
 * Attachment helpers shared by the chat transcript, the composer strip and
 * the lightbox: URL resolution, type sniffing, sizes, and human labels for
 * file names that were never meant for humans.
 */
import { apiUrl } from "@/api/client";

const MB = 1024 * 1024;

export function formatBytes(n: number): string {
  if (n >= MB) return `${(n / MB).toFixed(1)} MB`;
  if (n >= 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${n} B`;
}

/**
 * Decide whether an image_url URL points at an image (renderable as a
 * thumbnail) vs. a non-image attachment (PDF, CSV, etc).
 */
export function isImageAttachment(url: string): boolean {
  if (url.startsWith("data:image/")) return true;
  if (url.startsWith("data:application/pdf")) return false;
  if (url.startsWith("hive-attachment://")) {
    return /\.(png|jpe?g|webp|gif|svg)$/i.test(url);
  }
  // attachment-served URLs end with the filename — sniff by extension.
  return /\.(png|jpe?g|webp|gif|svg)(\?|$)/i.test(url);
}

/**
 * Turn an attachment URL into something the browser can fetch.
 *
 * Canonical attachment refs come through as `hive-attachment://<rel_path>`
 * (the runtime's scheme for "file on disk under the session dir"). The
 * route at /api/sessions/{sid}/attachment/{basename} serves the bytes;
 * this resolver maps the canonical ref → fetchable URL. Layer F2 made
 * `hive-attachment://` the single canonical form everywhere — submit,
 * replay, persistence — so the route-URL shape lives only here.
 *
 * Pass-through for everything else: data: URIs, already-resolved API
 * URLs (legacy persisted messages), absolute http(s) URLs.
 */
export function resolveAttachmentUrl(url: string, sessionId: string): string {
  if (!url || !url.startsWith("hive-attachment://")) return url;
  const relPath = url.slice("hive-attachment://".length).replace(/^\/+/, "");
  // Route accepts a basename only — its path-traversal guard rejects
  // slashes, and the path-param matcher won't match across slashes
  // anyway. Both `data/attachments/X` (post-D1) and `attachments/X`
  // (legacy) resolve via basename. encodeURIComponent because filenames
  // now preserve the user's original name (e.g. "Calculus Volume 1.pdf"
  // with spaces) instead of being normalized to `{ts}_{idx}.{ext}`.
  const basename = relPath.split("/").pop() ?? relPath;
  return apiUrl(`/sessions/${sessionId}/attachment/${encodeURIComponent(basename)}`);
}

export interface AttachmentLabel {
  /** What to show: the cleaned-up name, or a generic one for machine names. */
  label: string;
  /** Lower-case extension without the dot ("" when there is none). */
  ext: string;
  /** The original basename, for tooltips and downloads. */
  original: string;
}

// Stems no person typed: upload timestamps with an index ("1787046226164_0"),
// UUIDs, long hex hashes, and camera/OS counters ("IMG_20261010_014833").
const EPOCH_STEM = /^\d{10,}(?:[_-](\d+))?$/;
const UUID_STEM = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const HASH_STEM = /^[0-9a-f]{16,}$/i;
const CAMERA_STEM = /^(img|pxl|dsc|dscn|photo|mvimg|wp)[_-]?\d{4,}[\d_-]*$/i;
const PASTED_STEM = /^(image|blob|clipboard|untitled|download)$/i;
// Duplicate markers the OS or the runtime appends: "name (2)", "name copy".
const COPY_SUFFIX = /(?:\s*\(\d+\)|\s+copy(?:\s+\d+)?)$/i;
// An export stamp tacked onto a real name: "export_1787046480958".
const EPOCH_SUFFIX = /[\s_-]+\d{10,}$/;

function genericName(ext: string): string {
  if (/^(png|jpe?g|webp|gif|svg|heic|avif)$/.test(ext)) return "Image";
  if (ext === "pdf") return "PDF document";
  if (ext === "csv") return "Spreadsheet";
  return "File";
}

/** A presentable name for an attachment's file name. */
export function attachmentLabel(fileName: string | undefined): AttachmentLabel {
  let original = (fileName ?? "").split(/[\\/]/).pop() ?? "";
  try {
    original = decodeURIComponent(original);
  } catch {
    // Not URI-encoded after all; keep it as is.
  }
  const dot = original.lastIndexOf(".");
  const hasExt = dot > 0 && original.length - dot <= 6;
  const ext = hasExt ? original.slice(dot + 1).toLowerCase() : "";
  const stem = (hasExt ? original.slice(0, dot) : original).replace(COPY_SUFFIX, "").trim();

  const epoch = EPOCH_STEM.exec(stem);
  if (epoch) {
    // The index is the file's position in its upload batch; count from 1.
    const n = epoch[1] !== undefined ? Number(epoch[1]) + 1 : null;
    return { label: n ? `${genericName(ext)} ${n}` : genericName(ext), ext, original };
  }
  if (CAMERA_STEM.test(stem)) return { label: "Photo", ext, original };
  if (PASTED_STEM.test(stem)) {
    return { label: genericName(ext) === "Image" ? "Pasted image" : genericName(ext), ext, original };
  }
  if (!stem || UUID_STEM.test(stem) || HASH_STEM.test(stem)) {
    return { label: genericName(ext), ext, original };
  }
  // A person's name for the file: drop an export stamp and make the
  // separators readable.
  const words = stem.replace(EPOCH_SUFFIX, "").replace(/_+/g, " ").replace(/\s{2,}/g, " ").trim();
  const label = /^[a-z]/.test(words) && words === words.toLowerCase()
    ? words[0].toUpperCase() + words.slice(1)
    : words;
  return { label, ext, original };
}

export type AttachmentTone = "pdf" | "sheet" | "doc" | "slides" | "archive" | "code" | "media" | "file";

/** The visual family of a file, by extension. */
export function attachmentTone(ext: string): AttachmentTone {
  if (ext === "pdf") return "pdf";
  if (/^(csv|tsv|xlsx?|ods|numbers)$/.test(ext)) return "sheet";
  if (/^(docx?|odt|rtf|txt|md|pages)$/.test(ext)) return "doc";
  if (/^(pptx?|odp|key)$/.test(ext)) return "slides";
  if (/^(zip|tar|gz|tgz|7z|rar)$/.test(ext)) return "archive";
  if (/^(json|ya?ml|toml|xml|html?|css|js|ts|tsx|py|sql|sh|log)$/.test(ext)) return "code";
  if (/^(mp3|wav|m4a|ogg|mp4|mov|webm)$/.test(ext)) return "media";
  return "file";
}
