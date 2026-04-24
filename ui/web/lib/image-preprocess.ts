/**
 * Client-side image preprocessing for chat attachments.
 *
 * Pipeline: validate(file) → decode → validateDims → resize to 1280px
 * longest edge → encode (PNG if source was PNG, else JPEG q=0.85) →
 * base64. A 128px thumbnail is produced from the same bitmap at q=0.70.
 *
 * The pure decision functions (chooseOutputMime, computeResizeDims,
 * validateFile, validateDimensions) are exported separately so they
 * can be unit-tested in node without a canvas implementation; the
 * `preprocessImage` driver is browser-only (createImageBitmap +
 * HTMLCanvasElement + FileReader).
 */
import { ATTACHMENT_ALLOWED_MIME, type AttachmentMime } from "./api";

export const MAX_FILE_BYTES = 5 * 1024 * 1024;
export const MIN_IMAGE_DIM = 64;
export const MAX_IMAGE_DIM = 4096;
export const RESIZE_MAX_EDGE = 1280;
export const THUMBNAIL_MAX_EDGE = 128;
export const FULL_QUALITY = 0.85;
export const THUMB_QUALITY = 0.7;

export type ValidationResult = { ok: true } | { ok: false; reason: string };

export function validateFile(file: File): ValidationResult {
  if (!(ATTACHMENT_ALLOWED_MIME as readonly string[]).includes(file.type)) {
    return {
      ok: false,
      reason: `unsupported format (${file.type || "unknown"}); use PNG, JPEG, or WebP`,
    };
  }
  if (file.size > MAX_FILE_BYTES) {
    const mb = (file.size / 1024 / 1024).toFixed(1);
    return { ok: false, reason: `${file.name}: ${mb} MB exceeds the 5 MB limit` };
  }
  return { ok: true };
}

export function validateDimensions(w: number, h: number): ValidationResult {
  if (w < MIN_IMAGE_DIM || h < MIN_IMAGE_DIM) {
    return {
      ok: false,
      reason: `image too small (${w}×${h}px); minimum ${MIN_IMAGE_DIM}px per side`,
    };
  }
  if (w > MAX_IMAGE_DIM || h > MAX_IMAGE_DIM) {
    return {
      ok: false,
      reason: `image too large (${w}×${h}px); maximum ${MAX_IMAGE_DIM}px per side`,
    };
  }
  return { ok: true };
}

/**
 * PNG in → PNG out (preserves transparency). Everything else encodes
 * as JPEG — WebP downgrades to JPEG because the backend doesn't need
 * three formats and JPEG is a safer common denominator.
 */
export function chooseOutputMime(
  source: AttachmentMime,
): "image/png" | "image/jpeg" {
  return source === "image/png" ? "image/png" : "image/jpeg";
}

/**
 * Scale (w, h) so the longest edge is at most `maxEdge`, preserving
 * aspect ratio. Never upscales — small images pass through untouched.
 */
export function computeResizeDims(
  w: number,
  h: number,
  maxEdge: number,
): { w: number; h: number } {
  if (w <= 0 || h <= 0) return { w: 0, h: 0 };
  const longest = Math.max(w, h);
  if (longest <= maxEdge) return { w, h };
  const scale = maxEdge / longest;
  return { w: Math.round(w * scale), h: Math.round(h * scale) };
}

export interface PreprocessedImage {
  mime_type: "image/png" | "image/jpeg";
  filename: string;
  data_base64: string;
  thumbnail_base64: string;
  width: number;
  height: number;
}

export type PreprocessOutcome =
  | { ok: true; image: PreprocessedImage }
  | { ok: false; reason: string };

export async function preprocessImage(file: File): Promise<PreprocessOutcome> {
  const fileCheck = validateFile(file);
  if (!fileCheck.ok) return fileCheck;

  let bitmap: ImageBitmap;
  try {
    bitmap = await createImageBitmap(file);
  } catch {
    return { ok: false, reason: `${file.name}: could not decode image` };
  }

  const dimCheck = validateDimensions(bitmap.width, bitmap.height);
  if (!dimCheck.ok) {
    bitmap.close?.();
    return dimCheck;
  }

  const outMime = chooseOutputMime(file.type as AttachmentMime);
  const full = computeResizeDims(bitmap.width, bitmap.height, RESIZE_MAX_EDGE);
  const thumb = computeResizeDims(bitmap.width, bitmap.height, THUMBNAIL_MAX_EDGE);

  try {
    const data_base64 = await renderToBase64(
      bitmap,
      full.w,
      full.h,
      outMime,
      FULL_QUALITY,
    );
    const thumbnail_base64 = await renderToBase64(
      bitmap,
      thumb.w,
      thumb.h,
      outMime,
      THUMB_QUALITY,
    );
    return {
      ok: true,
      image: {
        mime_type: outMime,
        filename: file.name,
        data_base64,
        thumbnail_base64,
        width: full.w,
        height: full.h,
      },
    };
  } catch (err) {
    return {
      ok: false,
      reason: `${file.name}: encode failed (${(err as Error)?.message ?? "unknown"})`,
    };
  } finally {
    bitmap.close?.();
  }
}

async function renderToBase64(
  bitmap: ImageBitmap,
  w: number,
  h: number,
  mime: "image/png" | "image/jpeg",
  quality: number,
): Promise<string> {
  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("canvas 2d context unavailable");
  ctx.drawImage(bitmap, 0, 0, w, h);

  const blob = await new Promise<Blob | null>((resolve) =>
    canvas.toBlob(resolve, mime, quality),
  );
  if (!blob) throw new Error("canvas.toBlob returned null");
  return blobToBase64(blob);
}

function blobToBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const fr = new FileReader();
    fr.onload = () => {
      const r = fr.result;
      if (typeof r !== "string") {
        reject(new Error("FileReader did not return a string"));
        return;
      }
      const comma = r.indexOf(",");
      resolve(comma >= 0 ? r.slice(comma + 1) : r);
    };
    fr.onerror = () => reject(fr.error ?? new Error("FileReader error"));
    fr.readAsDataURL(blob);
  });
}
