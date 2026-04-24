import { describe, it, expect } from "vitest";
import {
  chooseOutputMime,
  computeResizeDims,
  validateDimensions,
  validateFile,
  MAX_FILE_BYTES,
  RESIZE_MAX_EDGE,
} from "@/lib/image-preprocess";

/**
 * Node-env tests. The pure decision functions cover the three spec
 * cases without needing a canvas rasterizer — `preprocessImage` itself
 * is browser-only and exercised manually in 5.6 verification.
 */

function fakeFile(type: string, size: number, name = "img"): File {
  // vitest's node env has no File/Blob constructor we can call directly;
  // validateFile only reads `type`, `size`, and `name`, so a plain object
  // cast is enough.
  return { type, size, name } as unknown as File;
}

describe("chooseOutputMime — PNG stays PNG so transparency survives", () => {
  it("keeps PNG output for PNG input", () => {
    expect(chooseOutputMime("image/png")).toBe("image/png");
  });
  it("keeps JPEG as JPEG", () => {
    expect(chooseOutputMime("image/jpeg")).toBe("image/jpeg");
  });
  it("downgrades WebP to JPEG", () => {
    expect(chooseOutputMime("image/webp")).toBe("image/jpeg");
  });
});

describe("computeResizeDims — large images downscale to 1280px on the long edge", () => {
  it("downscales a 2000×1000 landscape to 1280×640", () => {
    expect(computeResizeDims(2000, 1000, RESIZE_MAX_EDGE)).toEqual({
      w: 1280,
      h: 640,
    });
  });
  it("downscales a 1000×2000 portrait to 640×1280", () => {
    expect(computeResizeDims(1000, 2000, RESIZE_MAX_EDGE)).toEqual({
      w: 640,
      h: 1280,
    });
  });
  it("never upscales — small images pass through", () => {
    expect(computeResizeDims(400, 300, RESIZE_MAX_EDGE)).toEqual({
      w: 400,
      h: 300,
    });
  });
});

describe("validateFile — rejects oversized / wrong mime", () => {
  it("accepts a valid PNG under the 5 MB cap", () => {
    expect(validateFile(fakeFile("image/png", 1_000_000, "ok.png"))).toEqual({
      ok: true,
    });
  });
  it("rejects GIF (not in the allowlist)", () => {
    const r = validateFile(fakeFile("image/gif", 1000, "a.gif"));
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toMatch(/unsupported|png|jpeg|webp/i);
  });
  it("rejects a 6 MB PNG — exceeds the raw-byte limit", () => {
    const r = validateFile(fakeFile("image/png", MAX_FILE_BYTES + 1, "big.png"));
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toMatch(/5\s*mb|limit/i);
  });
});

describe("validateDimensions", () => {
  it("accepts a 256×256 image", () => {
    expect(validateDimensions(256, 256)).toEqual({ ok: true });
  });
  it("rejects 32×32 (below 64px minimum)", () => {
    expect(validateDimensions(32, 32).ok).toBe(false);
  });
  it("rejects 5000×5000 (above 4096px maximum)", () => {
    expect(validateDimensions(5000, 5000).ok).toBe(false);
  });
});
