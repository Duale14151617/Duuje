import { useEffect, useRef, useState } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { Protocol } from "pmtiles";
import { boundsOf, circleRing, finite, polygonRing, type LatLon } from "./mapShapes";

/**
 * The self-hosted map: one Puntland PMTiles file served by this server (/api/v1/map/puntland.pmtiles), drawn in the browser with
 * MapLibre. Nothing is requested from any other site. Shows the latest vehicle positions, a route trail, circle and polygon zones,
 * and (while `picking`) lets the user click to place a zone's centre or corners. Loaded on demand (React.lazy) so the rest of the
 * app does not carry the map library.
 */
export interface MapConfig { url: string; bounds: [number, number, number, number]; attribution: string; centre: [number, number]; zoom: number; max_zoom: number }
export interface MapVehicle { id: string; label: string; lat: number; lon: number; stale: boolean; detail: string }
export interface MapZone { id: string; name: string; active: boolean; shape: "circle" | "polygon"; lat: number; lon: number; radius_m: number; points: LatLon[] }
export interface MapDraft { shape: "circle" | "polygon"; points: LatLon[]; radius: number }
export interface MapProps {
  config: MapConfig;
  vehicles: MapVehicle[];
  zones: MapZone[];
  trail: LatLon[];
  draft: MapDraft | null;
  picking: boolean;
  onPick: (lat: number, lon: number) => void;
  onMoveCorner: (index: number, lat: number, lon: number) => void;
  fitKey: string;
  lang: string;
  ariaLabel: string;
  hint: string;
  failedText: string;
}

type MLMap = InstanceType<typeof maplibregl.Map>;
type MLMarker = InstanceType<typeof maplibregl.Marker>;

let protocolReady = false;
function setSrc(map: MLMap | null, id: string, data: Fc) {
  const s = map?.getSource(id) as unknown as { setData?: (d: unknown) => void } | undefined;
  s?.setData?.(data);
}

function ensureProtocol() {
  if (protocolReady) return;
  const protocol = new Protocol();
  maplibregl.addProtocol("pmtiles", protocol.tile as never);
  protocolReady = true;
}

type Fc = { type: "FeatureCollection"; features: unknown[] };
const empty: Fc = { type: "FeatureCollection", features: [] };
const roads = (names: string[]) => ["match", ["get", "class"], names, true, false];

/** Basic OpenMapTiles-schema style. No text layers (a self-hosted font server is not needed): place names are drawn as HTML labels. */
function buildStyle(config: MapConfig) {
  const src = "osm";
  const zoomW = (a: number, b: number, c: number) => ["interpolate", ["exponential", 1.5], ["zoom"], 6, a, 12, b, 16, c];
  return {
    version: 8,
    sources: { [src]: { type: "vector", url: `pmtiles://${window.location.origin}${config.url}`, attribution: config.attribution, maxzoom: config.max_zoom } },
    layers: [
      { id: "bg", type: "background", paint: { "background-color": "#EEF0EA" } },
      { id: "landcover", type: "fill", source: src, "source-layer": "landcover", paint: { "fill-color": ["match", ["get", "class"], ["wood", "forest"], "#D5E2C6", ["grass", "farmland"], "#E2EAD0", ["sand"], "#EFE6C8", "#E6EBDC"], "fill-opacity": 0.8 } },
      { id: "landuse", type: "fill", source: src, "source-layer": "landuse", paint: { "fill-color": ["match", ["get", "class"], ["residential", "suburb", "neighbourhood"], "#E7E2D8", ["industrial", "commercial", "retail"], "#E0DCD2", ["cemetery"], "#D8E0D0", ["military"], "#E6DCD2", "#E8E6DE"], "fill-opacity": 0.7 } },
      { id: "park", type: "fill", source: src, "source-layer": "park", paint: { "fill-color": "#D3E3C3", "fill-opacity": 0.6 } },
      { id: "water", type: "fill", source: src, "source-layer": "water", paint: { "fill-color": "#A9C8E4" } },
      { id: "waterway", type: "line", source: src, "source-layer": "waterway", paint: { "line-color": "#A9C8E4", "line-width": zoomW(0.4, 1, 2) } },
      { id: "aeroway", type: "fill", source: src, "source-layer": "aeroway", paint: { "fill-color": "#DAD6CC" } },
      { id: "building", type: "fill", source: src, "source-layer": "building", minzoom: 13, paint: { "fill-color": "#D5CFC4", "fill-opacity": 0.9 } },
      { id: "road-minor-casing", type: "line", source: src, "source-layer": "transportation", minzoom: 11, filter: roads(["minor", "service", "track", "path"]), layout: { "line-cap": "round" }, paint: { "line-color": "#C9C2B4", "line-width": zoomW(0.5, 2.4, 6) } },
      { id: "road-minor", type: "line", source: src, "source-layer": "transportation", minzoom: 11, filter: roads(["minor", "service", "track", "path"]), layout: { "line-cap": "round" }, paint: { "line-color": "#FFFFFF", "line-width": zoomW(0.3, 1.4, 4.5) } },
      { id: "road-major-casing", type: "line", source: src, "source-layer": "transportation", filter: roads(["motorway", "trunk", "primary", "secondary", "tertiary"]), layout: { "line-cap": "round", "line-join": "round" }, paint: { "line-color": "#B4A98F", "line-width": zoomW(1.2, 4.5, 11) } },
      { id: "road-major", type: "line", source: src, "source-layer": "transportation", filter: roads(["motorway", "trunk", "primary", "secondary", "tertiary"]), layout: { "line-cap": "round", "line-join": "round" }, paint: { "line-color": ["match", ["get", "class"], ["motorway", "trunk", "primary"], "#F2D58A", "#FFFFFF"], "line-width": zoomW(0.8, 3.2, 8.5) } },
      { id: "boundary", type: "line", source: src, "source-layer": "boundary", filter: ["<=", ["get", "admin_level"], 4], paint: { "line-color": "#8A7F9A", "line-width": 1, "line-dasharray": [3, 2] } },
    ],
  };
}

const pointsFc = (pts: LatLon[]): Fc => ({ type: "FeatureCollection", features: pts.map(([la, lo]) => ({ type: "Feature", properties: {}, geometry: { type: "Point", coordinates: [lo, la] } })) });

export default function VehicleMap(props: MapProps) {
  const box = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MLMap | null>(null);
  const [ready, setReady] = useState(false);
  const [failed, setFailed] = useState(false);
  const live = useRef(props);
  live.current = props;
  const vehicleMarkers = useRef<MLMarker[]>([]);
  const cornerMarkers = useRef<MLMarker[]>([]);
  const placeMarkers = useRef<MLMarker[]>([]);
  const placeKey = useRef("");
  const lastFit = useRef("");

  // ---- create the map once --------------------------------------------------------------------------------------------------
  useEffect(() => {
    if (!box.current) return;
    let map: MLMap;
    try {
      ensureProtocol();
      const [w, s, e, n] = props.config.bounds;
      map = new maplibregl.Map({
        container: box.current,
        style: buildStyle(props.config) as never,
        center: [props.config.centre[0], props.config.centre[1]],
        zoom: props.config.zoom,
        minZoom: 5,
        maxZoom: props.config.max_zoom + 3,
        maxBounds: [[w - 0.5, s - 0.5], [e + 0.5, n + 0.5]],
        dragRotate: false,
        pitchWithRotate: false,
      });
    } catch {
      setFailed(true);
      return;
    }
    mapRef.current = map;
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    map.addControl(new maplibregl.ScaleControl({ maxWidth: 120, unit: "metric" }), "bottom-left");
    map.touchZoomRotate.disableRotation();

    const layer = (l: Record<string, unknown>) => map.addLayer(l as never);
    map.on("error", () => { if (!map.isStyleLoaded()) setFailed(true); });
    map.on("load", () => {
      map.addSource("zones", { type: "geojson", data: empty as never });
      map.addSource("trail", { type: "geojson", data: empty as never });
      map.addSource("draft", { type: "geojson", data: empty as never });
      layer({ id: "zones-fill", type: "fill", source: "zones", filter: ["==", ["get", "active"], true], paint: { "fill-color": "#C6A15B", "fill-opacity": 0.2 } });
      layer({ id: "zones-line", type: "line", source: "zones", filter: ["==", ["get", "active"], true], paint: { "line-color": "#8A6A1F", "line-width": 2 } });
      layer({ id: "zones-off-fill", type: "fill", source: "zones", filter: ["==", ["get", "active"], false], paint: { "fill-color": "#7A8794", "fill-opacity": 0.1 } });
      layer({ id: "zones-off-line", type: "line", source: "zones", filter: ["==", ["get", "active"], false], paint: { "line-color": "#5F6B77", "line-width": 1.5, "line-dasharray": [3, 2] } });
      layer({ id: "trail-line", type: "line", source: "trail", filter: ["==", ["geometry-type"], "LineString"], layout: { "line-cap": "round", "line-join": "round" }, paint: { "line-color": "#14263D", "line-width": 3.5, "line-opacity": 0.85 } });
      layer({ id: "trail-line-inner", type: "line", source: "trail", filter: ["==", ["geometry-type"], "LineString"], layout: { "line-cap": "round", "line-join": "round" }, paint: { "line-color": "#C6A15B", "line-width": 1.6 } });
      layer({ id: "trail-ends", type: "circle", source: "trail", filter: ["==", ["geometry-type"], "Point"], paint: { "circle-radius": 6, "circle-color": ["match", ["get", "kind"], "start", "#2E7D32", "#C6A15B"], "circle-stroke-color": "#14263D", "circle-stroke-width": 2 } });
      layer({ id: "draft-fill", type: "fill", source: "draft", filter: ["==", ["geometry-type"], "Polygon"], paint: { "fill-color": "#2B6CB0", "fill-opacity": 0.2 } });
      layer({ id: "draft-line", type: "line", source: "draft", filter: ["in", ["geometry-type"], ["literal", ["Polygon", "LineString"]]], paint: { "line-color": "#2B6CB0", "line-width": 2.5, "line-dasharray": [2, 1] } });
      setReady(true);
    });

    map.on("click", ((e: { lngLat: { lat: number; lng: number } }) => {
      if (live.current.picking) live.current.onPick(e.lngLat.lat, e.lngLat.lng);
    }) as never);
    map.on("click", "zones-fill", ((e: { lngLat: { lat: number; lng: number }; features?: { properties?: Record<string, unknown> | null }[] }) => {
      if (live.current.picking) return;
      const name = String(e.features?.[0]?.properties?.name ?? "");
      if (name) new maplibregl.Popup({ offset: 6 }).setLngLat([e.lngLat.lng, e.lngLat.lat]).setText(name).addTo(map);
    }) as never);

    // place names: drawn from the tile data as plain HTML labels (no font files needed)
    const refreshPlaces = () => {
      try {
        const z = map.getZoom();
        const b = map.getBounds();
        const seen = new Map<string, { lon: number; lat: number; rank: number }>();
        const rankOf: Record<string, number> = { city: 0, town: 1, village: 2, hamlet: 3 };
        const minZoom: Record<string, number> = { city: 5, town: 7, village: 10, hamlet: 12 };
        for (const f of map.querySourceFeatures("osm", { sourceLayer: "place" })) {
          const p = (f.properties ?? {}) as Record<string, unknown>;
          const cls = String(p.class ?? "");
          const name = String(p.name ?? "");
          if (!name || !(cls in rankOf) || z < minZoom[cls] || f.geometry.type !== "Point") continue;
          const [lon, lat] = f.geometry.coordinates as [number, number];
          if (!b.contains([lon, lat]) || seen.has(name)) continue;
          seen.set(name, { lon, lat, rank: rankOf[cls] });
        }
        const list = [...seen.entries()].sort((a, c) => a[1].rank - c[1].rank).slice(0, 50);
        const key = list.map(([n]) => n).join("|");
        if (key === placeKey.current) return;
        placeKey.current = key;
        placeMarkers.current.forEach((m) => m.remove());
        placeMarkers.current = list.map(([name, v]) => {
          const el = document.createElement("div");
          el.className = `map-place map-place-${v.rank}`;
          el.textContent = name;
          el.setAttribute("aria-hidden", "true");
          return new maplibregl.Marker({ element: el, anchor: "center" }).setLngLat([v.lon, v.lat]).addTo(map);
        });
      } catch { /* the source may not be loaded yet: the next idle event tries again */ }
    };
    map.on("idle", refreshPlaces);
    map.on("moveend", refreshPlaces);

    return () => {
      vehicleMarkers.current.forEach((m) => m.remove());
      cornerMarkers.current.forEach((m) => m.remove());
      placeMarkers.current.forEach((m) => m.remove());
      vehicleMarkers.current = []; cornerMarkers.current = []; placeMarkers.current = []; placeKey.current = "";
      map.remove();
      mapRef.current = null;
      setReady(false);
    };
    // the map is created once for this config; everything else flows in through the effects below
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [props.config.url]);

  // ---- zones ----------------------------------------------------------------------------------------------------------------
  useEffect(() => {
    if (!ready) return;
    setSrc(mapRef.current, "zones", {
      type: "FeatureCollection",
      features: props.zones.filter((z) => finite(z.lat) && finite(z.lon)).map((z) => ({
        type: "Feature", properties: { name: z.name, active: z.active },
        geometry: { type: "Polygon", coordinates: [z.shape === "polygon" && z.points.length >= 3 ? polygonRing(z.points) : circleRing(z.lat, z.lon, z.radius_m)] },
      })),
    });
  }, [ready, props.zones]);

  // ---- route trail ----------------------------------------------------------------------------------------------------------
  useEffect(() => {
    if (!ready) return;
    const pts = props.trail.filter(([la, lo]) => finite(la) && finite(lo));
    if (pts.length < 2) { setSrc(mapRef.current, "trail", empty); return; }
    const first = pts[0], last = pts[pts.length - 1];
    setSrc(mapRef.current, "trail", {
      type: "FeatureCollection",
      features: [
        { type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: pts.map(([la, lo]) => [lo, la]) } },
        { type: "Feature", properties: { kind: "start" }, geometry: { type: "Point", coordinates: [first[1], first[0]] } },
        { type: "Feature", properties: { kind: "end" }, geometry: { type: "Point", coordinates: [last[1], last[0]] } },
      ],
    });
  }, [ready, props.trail]);

  // ---- vehicles (HTML buttons: keyboard reachable, with a text label) -------------------------------------------------------
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    vehicleMarkers.current.forEach((m) => m.remove());
    vehicleMarkers.current = props.vehicles.filter((v) => finite(v.lat) && finite(v.lon)).slice(0, 500).map((v) => {
      const el = document.createElement("button");
      el.type = "button";
      el.className = `map-veh${v.stale ? " map-veh-stale" : ""}`;
      el.setAttribute("aria-label", `${v.label}. ${v.detail}`);
      const dot = document.createElement("span");
      dot.className = "map-veh-dot";
      const txt = document.createElement("span");
      txt.className = "map-veh-label";
      txt.textContent = v.label;
      el.append(dot, txt);
      const popup = new maplibregl.Popup({ offset: 14, closeButton: true }).setText(`${v.label} · ${v.detail}`);
      return new maplibregl.Marker({ element: el, anchor: "center" }).setLngLat([v.lon, v.lat]).setPopup(popup).addTo(map);
    });
  }, [ready, props.vehicles]);

  // ---- the zone being drawn -------------------------------------------------------------------------------------------------
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    const d = props.draft;
    const features: unknown[] = [];
    if (d && d.points.length > 0) {
      if (d.shape === "circle" && d.radius > 0) {
        features.push({ type: "Feature", properties: {}, geometry: { type: "Polygon", coordinates: [circleRing(d.points[0][0], d.points[0][1], d.radius)] } });
      } else if (d.shape === "polygon") {
        if (d.points.length >= 3) features.push({ type: "Feature", properties: {}, geometry: { type: "Polygon", coordinates: [polygonRing(d.points)] } });
        else if (d.points.length === 2) features.push({ type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: d.points.map(([la, lo]) => [lo, la]) } });
      }
    }
    setSrc(mapRef.current, "draft", { type: "FeatureCollection", features });
    cornerMarkers.current.forEach((m) => m.remove());
    cornerMarkers.current = (d?.points ?? []).map(([la, lo], i) => {
      const el = document.createElement("div");
      el.className = "map-corner";
      el.textContent = d?.shape === "polygon" ? String(i + 1) : "+";
      const m = new maplibregl.Marker({ element: el, draggable: true }).setLngLat([lo, la]).addTo(map);
      m.on("dragend", () => { const p = m.getLngLat(); live.current.onMoveCorner(i, p.lat, p.lng); });
      return m;
    });
  }, [ready, props.draft]);

  // ---- picking cursor ---------------------------------------------------------------------------------------------------------
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    map.getCanvas().style.cursor = props.picking ? "crosshair" : "";
  }, [ready, props.picking]);

  // ---- fit the view once per vehicle / fleet, when there is something to show -----------------------------------------------
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    const pts: LatLon[] = props.trail.length >= 2 ? props.trail : props.vehicles.map((v) => [v.lat, v.lon] as LatLon);
    const clean = pts.filter(([la, lo]) => finite(la) && finite(lo));
    if (clean.length === 0) return;
    const key = `${props.fitKey}:${props.trail.length >= 2 ? "trail" : "fleet"}`;
    if (lastFit.current === key) return;
    lastFit.current = key;
    const b = boundsOf(clean);
    if (b) map.fitBounds(b as never, { padding: 50, maxZoom: 15, duration: 0 });
  }, [ready, props.trail, props.vehicles, props.fitKey]);

  if (failed) return <p role="alert" className="muted">{props.failedText}</p>;
  return (
    <div className="map-wrap">
      <div ref={box} className="map-box" role="region" aria-label={props.ariaLabel} />
      {props.picking && <p className="map-hint" role="status">{props.hint}</p>}
    </div>
  );
}
