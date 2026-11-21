import { describe, expect, it } from "vitest";
import { formatDateTime, formatDay, formatLongDate, formatMoney, formatMoneyList, formatNumber, toDate } from "./format";

describe("numbers and money", () => {
  it("groups thousands the same way in every language", () => {
    expect(formatNumber(1234567)).toBe("1,234,567");
    expect(formatNumber("1234.5", 2)).toBe("1,234.50");
    expect(formatNumber(null)).toBe("-");
    expect(formatNumber("abc")).toBe("-");
  });
  it("writes money as amount then currency with two decimals", () => {
    expect(formatMoney("1234.5", "USD")).toBe("1,234.50 USD");
    expect(formatMoney(0)).toBe("0.00");
    expect(formatMoney(undefined, "USD")).toBe("-");
  });
  it("joins several currencies and handles none", () => {
    expect(formatMoneyList([{ total: "10", currency: "USD" }, { total: "5000", currency: "SOS" }])).toBe("10.00 USD + 5,000.00 SOS");
    expect(formatMoneyList([])).toBe("0");
  });
});

describe("dates", () => {
  it("reads a bare date as that calendar day", () => {
    const d = toDate("2026-11-20")!;
    expect([d.getFullYear(), d.getMonth(), d.getDate()]).toEqual([2026, 10, 20]);
    expect(toDate("nope")).toBeNull();
  });
  it("uses one shape in both languages", () => {
    expect(formatDay("2026-11-20", "en")).toBe("20 Nov 2026");
    expect(formatDateTime(new Date(2026, 10, 20, 9, 5), "en")).toBe("20 Nov 2026, 09:05");
    expect(formatLongDate("2026-11-20", "en")).toBe("Friday 20 November 2026");
    expect(formatDay("2026-11-20", "so")).toMatch(/^20 \S+ 2026$/);
    expect(formatDay("garbage", "en")).toBe("");
  });
});
