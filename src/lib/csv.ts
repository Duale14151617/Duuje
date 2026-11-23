/** Small client-side CSV helpers used by the import page (pre-checks, template and error report downloads). */

/** Neutralise spreadsheet formulas and quote a field. */
function cell(value: string): string {
  const v = /^[=+\-@\t\r]/.test(value) ? `'${value}` : value;
  return /[",\n\r]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v;
}

export function toCsv(rows: string[][]): string {
  return rows.map((r) => r.map(cell).join(",")).join("\r\n") + "\r\n";
}

export function downloadText(filename: string, content: string, type = "text/csv;charset=utf-8"): void {
  const url = URL.createObjectURL(new Blob(["\ufeff" + content], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export interface CsvInspection { headers: string[]; rows: number; problem?: "file_type_invalid" | "file_too_large" | "file_encoding_invalid" | "file_empty" | "file_columns_invalid" | "file_too_many_rows" }

/** Count records, honouring quoted fields that contain commas or line breaks. */
function splitRecords(text: string): string[][] {
  const out: string[][] = [];
  let row: string[] = [], field = "", quoted = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (quoted) {
      if (c === '"') { if (text[i + 1] === '"') { field += '"'; i++; } else quoted = false; } else field += c;
    } else if (c === '"') quoted = true;
    else if (c === ",") { row.push(field); field = ""; }
    else if (c === "\n" || c === "\r") {
      if (c === "\r" && text[i + 1] === "\n") i++;
      row.push(field); field = "";
      if (row.some((x) => x.trim() !== "")) out.push(row);
      row = [];
    } else field += c;
  }
  row.push(field);
  if (row.some((x) => x.trim() !== "")) out.push(row);
  return out;
}

/** Mirrors the server's limits so people get instant feedback; the server still re-checks everything. */
export async function inspectCsv(file: File, opts: { columns: string[]; required: string[]; maxBytes: number; maxRows: number }): Promise<CsvInspection> {
  if (!file.name.toLowerCase().endsWith(".csv")) return { headers: [], rows: 0, problem: "file_type_invalid" };
  if (file.size > opts.maxBytes) return { headers: [], rows: 0, problem: "file_too_large" };
  let text: string;
  try { text = new TextDecoder("utf-8", { fatal: true }).decode(await file.arrayBuffer()).replace(/^\ufeff/, ""); }
  catch { return { headers: [], rows: 0, problem: "file_encoding_invalid" }; }
  const recs = splitRecords(text);
  const headers = (recs[0] ?? []).map((h) => h.trim());
  const set = new Set(headers);
  if (!opts.required.every((c) => set.has(c)) || !headers.every((h) => opts.columns.includes(h))) return { headers, rows: 0, problem: "file_columns_invalid" };
  const rows = recs.length - 1;
  if (rows < 1) return { headers, rows, problem: "file_empty" };
  if (rows > opts.maxRows) return { headers, rows, problem: "file_too_many_rows" };
  return { headers, rows };
}
