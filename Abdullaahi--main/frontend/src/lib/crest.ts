import type { PdfBrand } from "./pdf";

const cache = new Map<string, PdfBrand["crest"] | null>();

/** Fetch an emblem and re-encode it as a small baseline JPEG that PDF readers always accept (the originals may be progressive
 *  or large). Returns undefined on any failure: the PDF is then produced without the crest, never blocked. */
export async function loadCrest(src: string, maxPx = 160): Promise<PdfBrand["crest"] | undefined> {
  if (cache.has(src)) return cache.get(src) ?? undefined;
  try {
    const res = await fetch(src);
    if (!res.ok) throw new Error("crest not found");
    const bmp = await createImageBitmap(await res.blob());
    const k = Math.min(1, maxPx / Math.max(bmp.width, bmp.height));
    const width = Math.max(1, Math.round(bmp.width * k)), height = Math.max(1, Math.round(bmp.height * k));
    const canvas = document.createElement("canvas");
    canvas.width = width; canvas.height = height;
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error("no canvas");
    ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, width, height);  // JPEG has no transparency
    ctx.drawImage(bmp, 0, 0, width, height);
    const blob = await new Promise<Blob | null>((r) => canvas.toBlob(r, "image/jpeg", 0.9));
    if (!blob) throw new Error("encode failed");
    const crest = { jpeg: new Uint8Array(await blob.arrayBuffer()), width, height };
    cache.set(src, crest);
    return crest;
  } catch {
    cache.set(src, null);
    return undefined;
  }
}
