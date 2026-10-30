import { describe, expect, it } from "vitest";
import { matches, normalize, rankHits, searchableModules } from "./search";

describe("matches", () => {
  it("needs every typed word somewhere, in any order, ignoring case and accents", () => {
    expect(matches(["Abdi Jamá", "Sergeant"], "jama abdi")).toBe(true);
    expect(matches(["Abdi Jama"], "abdi hersi")).toBe(false);
    expect(matches([null, undefined, "VEH-001"], "veh-0")).toBe(true);
    expect(matches(["x"], "   ")).toBe(false);
  });
  it("normalizes", () => { expect(normalize("  Éa   B ")).toBe("ea b"); });
});

describe("rankHits", () => {
  it("puts exact, then prefix, then word-prefix, then substring first and keeps server order within a rank", () => {
    const hits = [{ title: "Old Abdi" }, { title: "Xabdix" }, { title: "Abdi Jama" }, { title: "abdi" }, { title: "Abdirahman" }];
    expect(rankHits(hits, "abdi").map((h) => h.title)).toEqual(["abdi", "Abdi Jama", "Abdirahman", "Old Abdi", "Xabdix"]);
  });
});

describe("searchableModules", () => {
  const can = (...p: string[]) => (x: string) => p.includes(x);
  it("offers only the modules the permissions allow", () => {
    expect(searchableModules(can())).toEqual([]);
    expect(searchableModules(can("personnel.view_team", "vehicles.view"))).toEqual(["personnel", "vehicles"]);
    expect(searchableModules(can("search.cross_service", "org.view", "reports.view", "training.view", "logistics.view")))
      .toEqual(["personnel", "units", "reports", "training", "logistics"].filter((m) => m !== "vehicles"));
  });
});
