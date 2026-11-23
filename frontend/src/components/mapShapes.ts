/** Small pure helpers for the vehicle map (no map library in here, so they are easy to test). Points are [latitude, longitude]. */
export type LatLon = [number, number];

/** A circle as a closed GeoJSON ring ([longitude, latitude] pairs). Flat-earth approximation: fine for zones up to a few tens of km. */
export function circleRing(lat: number, lon: number, radiusM: number, steps = 64): [number, number][] {
  const dLat = radiusM / 111_320;
  const dLon = radiusM / (111_320 * Math.max(Math.cos((lat * Math.PI) / 180), 0.01));
  const ring: [number, number][] = [];
  for (let i = 0; i < steps; i++) {
    const a = (2 * Math.PI * i) / steps;
    ring.push([lon + dLon * Math.cos(a), lat + dLat * Math.sin(a)]);
  }
  ring.push(ring[0]);
  return ring;
}

/** Polygon corners as a closed GeoJSON ring. */
export function polygonRing(points: LatLon[]): [number, number][] {
  const ring = points.map(([la, lo]) => [lo, la] as [number, number]);
  if (ring.length) ring.push(ring[0]);
  return ring;
}

/** [[west, south], [east, north]] around the points, or null when there are none. */
export function boundsOf(points: LatLon[]): [[number, number], [number, number]] | null {
  if (points.length === 0) return null;
  let w = 180, e = -180, s = 90, n = -90;
  for (const [la, lo] of points) { w = Math.min(w, lo); e = Math.max(e, lo); s = Math.min(s, la); n = Math.max(n, la); }
  return [[w, s], [e, n]];
}

export const finite = (n: number) => Number.isFinite(n);
