import { describe, expect, it } from "vitest";
import { boundsOf, circleRing, polygonRing } from "./mapShapes";

describe("map shapes", () => {
  it("draws a closed circle of about the right size", () => {
    const ring = circleRing(8.4, 48.4, 1000, 8);
    expect(ring.length).toBe(9);
    expect(ring[0]).toEqual(ring[8]);
    const north = ring[2]; // quarter turn: due north
    expect(Math.abs((north[1] - 8.4) * 111_320 - 1000)).toBeLessThan(5);
  });
  it("closes a polygon ring in longitude, latitude order", () => {
    const ring = polygonRing([[8, 48], [8, 49], [9, 49]]);
    expect(ring).toEqual([[48, 8], [49, 8], [49, 9], [48, 8]]);
    expect(polygonRing([])).toEqual([]);
  });
  it("finds the bounds", () => {
    expect(boundsOf([])).toBeNull();
    expect(boundsOf([[8, 48], [9, 50]])).toEqual([[48, 8], [50, 9]]);
  });
});
