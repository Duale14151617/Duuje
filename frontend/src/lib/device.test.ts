import { describe, expect, it } from "vitest";
import { describeDevice } from "./device";

describe("describeDevice", () => {
  it("names common browsers and systems", () => {
    expect(describeDevice("Mozilla/5.0 (Windows NT 10.0; Win64) AppleWebKit Chrome/120.0 Safari/537.36")).toBe("Chrome · Windows");
    expect(describeDevice("Mozilla/5.0 (Linux; Android 13) Chrome/120.0 Mobile Safari/537.36")).toBe("Chrome · Android");
    expect(describeDevice("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0) AppleWebKit Version/17 Safari/604.1")).toBe("Safari · iOS");
    expect(describeDevice("Mozilla/5.0 (Windows NT 10.0) Chrome/120 Edg/120")).toBe("Edge · Windows");
  });
  it("returns an empty string when there is nothing to show", () => {
    expect(describeDevice("")).toBe("");
    expect(describeDevice("curl/8")).toBe("");
  });
});
