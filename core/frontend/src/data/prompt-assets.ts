/**
 * A public content asset attached to a community/featured prompt — a screenshot
 * or a short video. URLs point at the world-readable email-assets bucket;
 * videos carry a `thumbnail` for the card preview. Mirrors the backend's
 * `PromptAsset` (community-prompts.service.ts).
 */
export interface PromptAsset {
  type: "image" | "video";
  url: string;
  thumbnail?: string;
}

/** Best src for a thumbnail-sized preview (cards): prefer the lightweight
 *  `thumbnail` (a downscaled image, or a video's poster), falling back to the
 *  raw image url. Detail/expanded views use `asset.url` directly for full
 *  resolution. Returns "" when there's nothing to show (a video with no
 *  thumbnail). */
export function assetPreviewSrc(asset: PromptAsset): string {
  if (asset.thumbnail) return asset.thumbnail;
  return asset.type === "image" ? asset.url : "";
}
