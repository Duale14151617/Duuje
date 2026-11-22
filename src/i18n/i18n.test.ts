import { describe, expect, it } from "vitest";
import { en } from "./en";
import { so } from "./so";

const placeholders = (s: string) => (s.match(/\{\w+\}/g) ?? []).sort();

describe("translations", () => {
  it("Somali and English have exactly the same keys", () => {
    expect(Object.keys(so).sort()).toEqual(Object.keys(en).sort());
  });
  it("no Somali string is empty", () => {
    for (const [k, v] of Object.entries(so)) expect(v.trim(), k).not.toBe("");
  });
  it("placeholders match between languages", () => {
    for (const k of Object.keys(en) as (keyof typeof en)[]) {
      expect(placeholders(so[k]), k).toEqual(placeholders(en[k]));
    }
  });
});
