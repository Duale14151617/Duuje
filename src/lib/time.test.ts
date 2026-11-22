import { describe, expect, it } from "vitest";
import { greetingKey, timeAgo, yearsSince } from "./time";

describe("time helpers", () => {
  it("picks the greeting by hour", () => {
    expect(greetingKey(new Date(2026, 0, 1, 8))).toBe("dash.greet.morning");
    expect(greetingKey(new Date(2026, 0, 1, 14))).toBe("dash.greet.afternoon");
    expect(greetingKey(new Date(2026, 0, 1, 20))).toBe("dash.greet.evening");
  });
  it("counts whole years of service and rejects bad dates", () => {
    const now = new Date(2026, 5, 15);
    expect(yearsSince("2016-06-16", now)).toBe(9);
    expect(yearsSince("2016-06-15", now)).toBe(10);
    expect(yearsSince(null, now)).toBeNull();
    expect(yearsSince("nope", now)).toBeNull();
    expect(yearsSince("2030-01-01", now)).toBeNull();
  });
  it("formats relative time and tolerates bad input", () => {
    const now = Date.parse("2026-06-15T12:00:00Z");
    expect(timeAgo("2026-06-15T10:00:00Z", "en", now)).toMatch(/2 hours ago/);
    expect(timeAgo("garbage", "en", now)).toBe("");
  });
});
