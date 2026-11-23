import { describe, expect, it } from "vitest";
import { buildPdf } from "./pdf";

const asText = (b: Uint8Array) => Array.from(b, (c) => String.fromCharCode(c)).join("");
const doc = (rows: string[][]) => ({
  title: "Test (title)", sections: [{ columns: [{ header: "A", width: 1 }, { header: "B", width: 2, align: "right" as const }], rows }],
});

describe("buildPdf", () => {
  it("writes a well-formed file whose xref offset points at the xref table", () => {
    const text = asText(buildPdf(doc([["1", "x"]])));
    expect(text.startsWith("%PDF-1.4")).toBe(true);
    expect(text.trimEnd().endsWith("%%EOF")).toBe(true);
    const offset = Number(/startxref\n(\d+)/.exec(text)?.[1]);
    expect(text.slice(offset, offset + 4)).toBe("xref");
  });

  it("adds pages as rows grow and repeats the footer on each", () => {
    const rows = Array.from({ length: 200 }, (_, i) => [String(i), "row"]);
    const text = asText(buildPdf(doc(rows)));
    const pages = Number(/\/Count (\d+)/.exec(text)?.[1]);
    expect(pages).toBeGreaterThan(2);
    expect(text).toContain(`Page ${pages} of ${pages}`);
  });

  it("escapes parentheses and backslashes and replaces unsupported characters", () => {
    const text = asText(buildPdf(doc([["a (b) \\ c", "中文"]])));
    expect(text).toContain("a \\(b\\) \\\\ c");
    expect(text).toContain("(??)");
  });

  it("breaks tokens wider than the cell instead of overflowing", () => {
    const text = asText(buildPdf(doc([["X".repeat(300), "y"]])));
    expect((text.match(/\(X+\) Tj/g) ?? []).length).toBeGreaterThan(1);
  });
});
