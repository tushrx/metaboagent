/**
 * One-time icon generator.
 *
 * Reads public/branding/favicon-source.png and emits:
 *   public/favicon.ico       (32x32, PNG bytes — modern browsers accept this)
 *   public/icon.png          (192x192 for the Next.js app icon convention)
 *   public/apple-icon.png    (180x180 for iOS home-screen)
 *
 * Run:
 *   node scripts/generate-icons.mjs
 *
 * Then commit the three generated files. The script is idempotent.
 */
import { promises as fs } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import sharp from "sharp";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = resolve(__dirname, "..");
const source = resolve(root, "public/branding/favicon-source.png");

async function main() {
  const src = await fs.readFile(source);

  const targets = [
    { out: "public/favicon.ico", size: 32 },
    { out: "public/icon.png", size: 192 },
    { out: "public/apple-icon.png", size: 180 },
  ];

  for (const { out, size } of targets) {
    const outPath = resolve(root, out);
    const buf = await sharp(src)
      .resize(size, size, { fit: "cover" })
      .png()
      .toBuffer();
    await fs.writeFile(outPath, buf);
    console.log(`wrote ${out} (${size}x${size}, ${buf.length} bytes)`);
  }
}

main().catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
