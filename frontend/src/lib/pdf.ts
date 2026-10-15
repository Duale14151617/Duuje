/**
 * Dependency-free PDF writer for tabular exports.
 *
 * Produces a standard PDF 1.4 file with the built-in Helvetica / Helvetica-Bold fonts (WinAnsi), so no font files
 * or third-party packages are needed and nothing leaves the browser. Supports a title block, one or more titled
 * tables, word-wrapped cells, repeating table headers across pages and "Page x of y" footers.
 *
 * Limitation: built-in fonts cover Latin-1 plus common typographic punctuation. Characters outside that set
 * (for example Arabic script) are printed as "?". Somali and English text render correctly.
 */

export interface PdfColumn { header: string; width: number; align?: "left" | "right" }
export interface PdfSection { heading?: string; columns: PdfColumn[]; rows: string[][] }
export interface PdfDoc {
  title: string;
  subtitle?: string;
  footer?: string;
  generatedLabel?: string;
  pageLabel?: (page: number, total: number) => string;
  landscape?: boolean;
  sections: PdfSection[];
}

// Helvetica advance widths for ASCII 32..126 (units per 1000 em).
const W_REG = [278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278, 556, 556, 556, 556, 556, 556, 556, 556, 556, 556,
  278, 278, 584, 584, 584, 556, 1015, 667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833, 722, 778, 667, 778, 722, 667, 611, 722,
  667, 944, 667, 667, 611, 278, 278, 278, 469, 556, 333, 556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833, 556, 556, 556, 556,
  333, 500, 278, 556, 500, 722, 500, 500, 500, 334, 260, 334, 584];
const W_BOLD = [278, 333, 474, 556, 556, 889, 722, 238, 333, 333, 389, 584, 278, 333, 278, 278, 556, 556, 556, 556, 556, 556, 556, 556, 556, 556,
  333, 333, 584, 584, 584, 611, 975, 722, 722, 722, 722, 667, 611, 778, 722, 278, 556, 722, 611, 833, 722, 778, 667, 778, 722, 667, 611, 722,
  667, 944, 667, 667, 611, 333, 278, 333, 584, 556, 333, 556, 611, 556, 611, 556, 333, 611, 611, 278, 278, 556, 278, 889, 611, 611, 611, 611,
  389, 556, 333, 611, 556, 778, 556, 556, 500, 389, 280, 389, 584];

// Unicode punctuation that exists in WinAnsiEncoding, mapped to its single-byte code.
const WIN_ANSI: Record<number, number> = {
  0x20ac: 0x80, 0x2026: 0x85, 0x2018: 0x91, 0x2019: 0x92, 0x201c: 0x93, 0x201d: 0x94, 0x2022: 0x95, 0x2013: 0x96, 0x2014: 0x97,
};

/** Map a JS string to WinAnsi byte codes (as a string whose char codes are the bytes). Unknown characters become "?". */
function encode(text: string): string {
  let out = "";
  for (const ch of text.normalize("NFC")) {
    const c = ch.codePointAt(0)!;
    if (c === 0x09) out += " ";
    else if (c >= 0x20 && c <= 0x7e) out += ch;
    else if (c >= 0xa0 && c <= 0xff) out += ch;
    else if (WIN_ANSI[c] !== undefined) out += String.fromCharCode(WIN_ANSI[c]);
    else if (c === 0x0a || c === 0x0d) out += " ";
    else if (c >= 0x300 && c <= 0x36f) continue; // stray combining marks
    else out += "?";
  }
  return out;
}

function glyphWidth(code: number, bold: boolean): number {
  if (code >= 32 && code <= 126) return (bold ? W_BOLD : W_REG)[code - 32];
  if (code === 0x95) return 350;
  if (code === 0x96) return 556;
  if (code === 0x97 || code === 0x85) return 1000;
  if (code === 0x91 || code === 0x92) return 222;
  if (code === 0x93 || code === 0x94) return 333;
  if (code === 0xb7) return 278;
  return 556;
}

function textWidth(s: string, size: number, bold: boolean): number {
  let w = 0;
  for (let i = 0; i < s.length; i++) w += glyphWidth(s.charCodeAt(i), bold);
  return (w * size) / 1000;
}

function wrap(raw: string, maxWidth: number, size: number, bold: boolean): string[] {
  const lines: string[] = [];
  const paragraphs = encode(raw).split(/\s*\n\s*/);
  for (const para of paragraphs) {
    let line = "";
    for (const word of para.split(" ").filter(Boolean)) {
      const attempt = line ? `${line} ${word}` : word;
      if (textWidth(attempt, size, bold) <= maxWidth) { line = attempt; continue; }
      if (line) { lines.push(line); line = ""; }
      if (textWidth(word, size, bold) <= maxWidth) { line = word; continue; }
      let chunk = "";  // a single token wider than the cell, such as a long id: break it by character
      for (const ch of word) {
        if (textWidth(chunk + ch, size, bold) > maxWidth && chunk) { lines.push(chunk); chunk = ""; }
        chunk += ch;
      }
      line = chunk;
    }
    lines.push(line);
  }
  return lines.length ? lines : [""];
}

const esc = (s: string) => s.replace(/[\\()]/g, (m) => `\\${m}`);
const num = (n: number) => (Math.round(n * 100) / 100).toString();

interface PageOps { ops: string[] }

export function buildPdf(doc: PdfDoc): Uint8Array {
  const [PW, PH] = doc.landscape ? [841.89, 595.28] : [595.28, 841.89];
  const M = 40, FOOT = 28;
  const usable = PW - 2 * M;
  const pages: PageOps[] = [];
  let page: PageOps;
  let y = 0;

  const newPage = () => { page = { ops: [] }; pages.push(page); y = PH - M; };
  const text = (s: string, x: number, yy: number, size: number, bold = false, gray = 0) =>
    page.ops.push(`BT ${gray} g /${bold ? "F2" : "F1"} ${size} Tf ${num(x)} ${num(yy)} Td (${esc(s)}) Tj ET`);
  const rect = (x: number, yy: number, w: number, h: number, gray: number) =>
    page.ops.push(`${gray} g ${num(x)} ${num(yy)} ${num(w)} ${num(h)} re f`);
  const rule = (yy: number, gray = 0.8) =>
    page.ops.push(`${gray} G 0.5 w ${num(M)} ${num(yy)} m ${num(PW - M)} ${num(yy)} l S`);
  const ensure = (h: number) => { if (y - h < M + FOOT) newPage(); };

  newPage();
  for (const line of wrap(doc.title, usable, 18, true)) { y -= 20; text(line, M, y, 18, true); }
  if (doc.subtitle) for (const line of wrap(doc.subtitle, usable, 10, false)) { y -= 13; text(line, M, y, 10, false, 0.35); }
  const stamp = `${doc.generatedLabel ?? "Generated"}: ${new Date().toISOString().slice(0, 16).replace("T", " ")} UTC`;
  y -= 13; text(encode(stamp), M, y, 8, false, 0.45);
  y -= 8; rule(y, 0.5); y -= 6;

  const SIZE = 9, LEAD = 11.5, PADX = 4, PADY = 3.5;
  for (const sec of doc.sections) {
    const totalW = sec.columns.reduce((a, c) => a + c.width, 0) || 1;
    const widths = sec.columns.map((c) => (c.width / totalW) * usable);
    const hasHeader = sec.columns.some((c) => c.header);
    if (sec.heading) { ensure(40); y -= 20; text(encode(sec.heading), M, y, 12, true); y -= 4; }

    const drawHeader = () => {
      if (!hasHeader) return;
      const lines = sec.columns.map((c, i) => wrap(c.header, widths[i] - 2 * PADX, SIZE, true));
      const h = Math.max(...lines.map((l) => l.length)) * LEAD + 2 * PADY;
      ensure(h + LEAD * 2);
      rect(M, y - h, usable, h, 0.9);
      let x = M;
      lines.forEach((ls, i) => {
        ls.forEach((l, k) => {
          const w = textWidth(l, SIZE, true);
          const tx = sec.columns[i].align === "right" ? x + widths[i] - PADX - w : x + PADX;
          text(l, tx, y - PADY - SIZE - k * LEAD + 2, SIZE, true);
        });
        x += widths[i];
      });
      y -= h;
    };

    drawHeader();
    for (const row of sec.rows) {
      const cells = sec.columns.map((_, i) => wrap(row[i] ?? "", widths[i] - 2 * PADX, SIZE, false));
      const h = Math.max(...cells.map((l) => l.length)) * LEAD + 2 * PADY;
      if (y - h < M + FOOT) { newPage(); drawHeader(); }
      let x = M;
      cells.forEach((ls, i) => {
        ls.forEach((l, k) => {
          const w = textWidth(l, SIZE, false);
          const tx = sec.columns[i].align === "right" ? x + widths[i] - PADX - w : x + PADX;
          text(l, tx, y - PADY - SIZE - k * LEAD + 2, SIZE);
        });
        x += widths[i];
      });
      y -= h;
      rule(y);
    }
    y -= 10;
  }

  // footers (second pass, once the page count is known)
  const total = pages.length;
  const footer = doc.footer ? encode(doc.footer) : "";
  pages.forEach((p, idx) => {
    page = p;
    const label = encode(doc.pageLabel ? doc.pageLabel(idx + 1, total) : `Page ${idx + 1} of ${total}`);
    text(label, PW - M - textWidth(label, 8, false), M - 6, 8, false, 0.45);
    if (footer) text(footer, M, M - 6, 8, false, 0.45);
  });

  // assemble the file
  const objs: string[] = [];
  const kids: number[] = [];
  objs[1] = "<< /Type /Catalog /Pages 2 0 R >>";
  objs[3] = "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>";
  objs[4] = "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>";
  objs[5] = `<< /Title (${esc(encode(doc.title))}) /Producer (ARMY HQ) >>`;
  let next = 6;
  for (const p of pages) {
    const content = p.ops.join("\n");
    const cid = next++, pid = next++;
    objs[cid] = `<< /Length ${content.length} >>\nstream\n${content}\nendstream`;
    objs[pid] = `<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${num(PW)} ${num(PH)}] /Contents ${cid} 0 R ` +
      `/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> >>`;
    kids.push(pid);
  }
  objs[2] = `<< /Type /Pages /Count ${kids.length} /Kids [${kids.map((k) => `${k} 0 R`).join(" ")}] >>`;

  let out = "%PDF-1.4\n%\xe2\xe3\xcf\xd3\n";
  const offsets: number[] = [];
  for (let i = 1; i < objs.length; i++) {
    offsets[i] = out.length;
    out += `${i} 0 obj\n${objs[i]}\nendobj\n`;
  }
  const xref = out.length;
  out += `xref\n0 ${objs.length}\n0000000000 65535 f \n`;
  for (let i = 1; i < objs.length; i++) out += `${String(offsets[i]).padStart(10, "0")} 00000 n \n`;
  out += `trailer\n<< /Size ${objs.length} /Root 1 0 R /Info 5 0 R >>\nstartxref\n${xref}\n%%EOF\n`;

  const bytes = new Uint8Array(out.length);  // every character is <= 0xFF, so one char == one byte
  for (let i = 0; i < out.length; i++) bytes[i] = out.charCodeAt(i) & 0xff;
  return bytes;
}

export function downloadPdf(doc: PdfDoc, filename: string): void {
  const url = URL.createObjectURL(new Blob([buildPdf(doc).buffer as ArrayBuffer], { type: "application/pdf" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
