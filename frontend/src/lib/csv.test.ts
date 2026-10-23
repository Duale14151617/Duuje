import { describe, expect, it } from "vitest";
import { inspectCsv, toCsv } from "./csv";

const limits = { columns: ["service_number", "full_name", "unit_code", "rank_code"], required: ["full_name", "unit_code", "rank_code"], maxBytes: 1000, maxRows: 2 };
const file = (name: string, body: string) => new File([body], name, { type: "text/csv" });

describe("inspectCsv", () => {
  it("accepts a valid file and counts records, including quoted line breaks", async () => {
    const r = await inspectCsv(file("a.csv", 'full_name,unit_code,rank_code\n"A\nB",U1,R1\nC,U1,R1\n'), limits);
    expect(r.problem).toBeUndefined();
    expect(r.rows).toBe(2);
  });
  it("rejects wrong type, unknown columns, missing columns, empty and oversized files", async () => {
    expect((await inspectCsv(file("a.txt", "x"), limits)).problem).toBe("file_type_invalid");
    expect((await inspectCsv(file("a.csv", "full_name,unit_code,rank_code,extra\nA,B,C,D\n"), limits)).problem).toBe("file_columns_invalid");
    expect((await inspectCsv(file("a.csv", "full_name,unit_code\nA,B\n"), limits)).problem).toBe("file_columns_invalid");
    expect((await inspectCsv(file("a.csv", "full_name,unit_code,rank_code\n"), limits)).problem).toBe("file_empty");
    expect((await inspectCsv(file("a.csv", "full_name,unit_code,rank_code\nA,B,C\nA,B,C\nA,B,C\n"), limits)).problem).toBe("file_too_many_rows");
    expect((await inspectCsv(file("a.csv", "x".repeat(2000)), limits)).problem).toBe("file_too_large");
  });
});

describe("toCsv", () => {
  it("quotes fields and neutralises spreadsheet formulas", () => {
    expect(toCsv([["=cmd|' /C calc'!A0", 'a,"b"']])).toBe(`'=cmd|' /C calc'!A0,"a,""b"""\r\n`);
  });
});
