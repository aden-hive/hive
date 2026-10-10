import { useState, type ReactNode } from "react";
import { ExternalLink, FileText, ImageOff } from "lucide-react";
import type { ImageContent } from "@/components/ChatPanel";
import {
  attachmentLabel,
  attachmentTone,
  formatBytes,
  isImageAttachment,
  resolveAttachmentUrl,
} from "@/lib/attachments";
import { openAttachment as openAttachmentInBrowser } from "@/lib/desktop-shims";

/** Most tiles a multi-image gallery shows; the last one carries "+N". */
const MAX_TILES = 6;

/** Mosaics on a six-column grid: each count fills a full rectangle (five is
 *  three across over two wide), with the row height that keeps tiles near
 *  square. */
const MOSAICS: Record<number, { spans: number[]; rowPx: number }> = {
  2: { spans: [3, 3], rowPx: 158 },
  3: { spans: [2, 2, 2], rowPx: 104 },
  4: { spans: [3, 3, 3, 3], rowPx: 118 },
  5: { spans: [2, 2, 2, 3, 3], rowPx: 104 },
  6: { spans: [2, 2, 2, 2, 2, 2], rowPx: 104 },
};

interface Entry {
  img: ImageContent;
  /** Position in the message's `images`, which the lightbox indexes by. */
  index: number;
}

/**
 * The attachments of a sent message: images as a gallery, documents as file
 * cards, generated images through `renderGenerated`. Names are presented via
 * `attachmentLabel`, so upload timestamps and hashes read as "Image 2".
 */
export default function MessageAttachments({
  images,
  sessionId,
  onOpenImage,
  renderGenerated,
}: {
  images: ImageContent[];
  sessionId?: string;
  onOpenImage?: (index: number) => void;
  renderGenerated: (img: ImageContent, index: number) => ReactNode;
}) {
  const entries = images.map((img, index) => ({ img, index }));
  const generated = entries.filter((e) => e.img._generated);
  const pictures = entries.filter((e) => !e.img._generated && isImageAttachment(e.img.image_url.url));
  const files = entries.filter((e) => !e.img._generated && !isImageAttachment(e.img.image_url.url));

  return (
    <div className="flex flex-col gap-2 mb-2">
      {generated.length > 0 && (
        <div className="flex flex-wrap gap-2">{generated.map((e) => renderGenerated(e.img, e.index))}</div>
      )}
      {pictures.length > 0 && <ImageGallery entries={pictures} sessionId={sessionId} onOpen={onOpenImage} />}
      {files.map((e) => (
        <FileCard key={e.index} img={e.img} sessionId={sessionId} />
      ))}
    </div>
  );
}

function ImageGallery({
  entries,
  sessionId,
  onOpen,
}: {
  entries: Entry[];
  sessionId?: string;
  onOpen?: (index: number) => void;
}) {
  const shown = entries.slice(0, MAX_TILES);
  const hidden = entries.length - shown.length;
  const single = shown.length === 1;
  const mosaic = MOSAICS[shown.length];
  return (
    <div
      className="hive-att-gallery"
      data-layout={single ? "single" : "mosaic"}
      style={mosaic ? { gridAutoRows: `${mosaic.rowPx}px` } : undefined}
    >
      {shown.map((e, i) => (
        <ImageTile
          key={e.index}
          img={e.img}
          sessionId={sessionId}
          // A lone image keeps its whole frame (letterboxed over a blurred
          // copy); tiles in a set crop to fill their cells.
          fit={single ? "contain" : "cover"}
          span={mosaic?.spans[i]}
          more={i === shown.length - 1 ? hidden : 0}
          onOpen={onOpen ? () => onOpen(e.index) : undefined}
        />
      ))}
    </div>
  );
}

function ImageTile({
  img,
  sessionId,
  fit,
  span,
  more,
  onOpen,
}: {
  img: ImageContent;
  sessionId?: string;
  fit: "contain" | "cover";
  /** Columns this tile spans in a mosaic (of six). */
  span?: number;
  more: number;
  onOpen?: () => void;
}) {
  const url = img.image_url.url;
  const src = sessionId ? resolveAttachmentUrl(url, sessionId) : url;
  // An unresolved `hive-attachment://` ref can't load until the session id
  // arrives (mid-reload); keep showing the loading state until then.
  const resolvable = !src.startsWith("hive-attachment://");
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const name = attachmentLabel(img._fileName);
  const size = img._byteSize !== undefined ? formatBytes(img._byteSize) : null;

  return (
    <button
      type="button"
      className="hive-att-tile"
      data-state={state}
      style={span ? { gridColumn: `span ${span}` } : undefined}
      onClick={onOpen}
      disabled={!onOpen}
      title={name.original || name.label}
      aria-label={more > 0 ? `${name.label}, and ${more} more` : name.label}
    >
      {state === "error" ? (
        <span className="hive-att-missing">
          <ImageOff className="w-4 h-4" />
          <span>Unavailable</span>
        </span>
      ) : (
        resolvable && (
          <>
            {fit === "contain" && (
              <img src={src} alt="" aria-hidden className="hive-att-backdrop" loading="lazy" decoding="async" />
            )}
            <img
              src={src}
              alt={name.label}
              className={fit === "contain" ? "hive-att-img hive-att-img--contain" : "hive-att-img"}
              loading="lazy"
              decoding="async"
              onLoad={() => setState("ready")}
              onError={() => setState("error")}
            />
          </>
        )
      )}
      {state !== "error" && (
        <span className="hive-att-caption">
          <span className="truncate">{name.label}</span>
          {size && <span className="hive-att-caption-meta">{size}</span>}
        </span>
      )}
      {more > 0 && <span className="hive-att-more">+{more}</span>}
    </button>
  );
}

function FileCard({ img, sessionId }: { img: ImageContent; sessionId?: string }) {
  const [error, setError] = useState<string | null>(null);
  const url = img.image_url.url;
  const href = sessionId ? resolveAttachmentUrl(url, sessionId) : url;
  const name = attachmentLabel(img._fileName);
  const ext = name.ext || "file";
  const openable = !!href && !href.startsWith("file-") && !href.startsWith("hive-attachment://");

  const open = () => {
    if (!openable) {
      setError("Still loading — try again in a moment");
      return;
    }
    setError(null);
    const res = openAttachmentInBrowser(href);
    if (res.ok === false) setError(res.error || "Couldn't open file");
  };

  const meta = [ext.toUpperCase(), img._byteSize !== undefined ? formatBytes(img._byteSize) : null]
    .filter(Boolean)
    .join(" · ");

  return (
    <button
      type="button"
      className="hive-att-file group"
      onClick={open}
      title={name.original || name.label}
    >
      <span className="hive-att-file-icon" data-tone={attachmentTone(name.ext)}>
        <FileText className="w-4 h-4" />
        <span className="hive-att-file-ext">{ext.slice(0, 4)}</span>
      </span>
      <span className="flex flex-col min-w-0 flex-1 text-left">
        <span className="hive-att-file-name">{name.label}</span>
        <span className={error ? "hive-att-file-meta text-destructive" : "hive-att-file-meta"}>
          {error ?? meta}
        </span>
      </span>
      <ExternalLink className="hive-att-file-open" />
    </button>
  );
}
