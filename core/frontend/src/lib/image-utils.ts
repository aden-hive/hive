const MAX_IMAGE_SIZE = 512;
const MAX_FILE_BYTES = 2 * 1024 * 1024;

/** Read a File as a data URL (avoids blob: URLs blocked by CSP). */
function fileToDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result as string);
    reader.onerror = () => reject(new Error("Failed to read file"));
    reader.readAsDataURL(file);
  });
}

/** Compress an image file using canvas. Returns a JPEG Blob under target size. */
export async function compressImage(file: File): Promise<Blob> {
  // Small JPEGs can be used directly. WebP is deliberately NOT passed
  // through: the runtime and cloud-sync backend only accept JPEG/PNG
  // (they sniff magic bytes), so a passed-through WebP uploads as HTTP 400
  // and the avatar silently fails to save. Fall through to the canvas path
  // below, which re-encodes any other type to JPEG.
  if (file.size <= MAX_FILE_BYTES && file.type === "image/jpeg") {
    return file;
  }

  const dataUrl = await fileToDataUrl(file);

  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => {
      const canvas = document.createElement("canvas");
      let { width, height } = img;

      if (width > MAX_IMAGE_SIZE || height > MAX_IMAGE_SIZE) {
        const scale = MAX_IMAGE_SIZE / Math.max(width, height);
        width = Math.round(width * scale);
        height = Math.round(height * scale);
      }

      canvas.width = width;
      canvas.height = height;
      const ctx = canvas.getContext("2d")!;
      ctx.drawImage(img, 0, 0, width, height);

      canvas.toBlob(
        (blob) => {
          if (blob) resolve(blob);
          else reject(new Error("Failed to encode image"));
        },
        "image/jpeg",
        0.85,
      );
    };
    img.onerror = () => reject(new Error("Failed to load image"));
    img.src = dataUrl;
  });
}
