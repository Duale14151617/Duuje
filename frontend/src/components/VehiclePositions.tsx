import { useEffect, useRef, useState, type FormEvent } from "react";
import { api } from "../api/client";
import type { Page } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { useFetch } from "../api/useFetch";
import { Chip, ErrorNotice, Field } from "./ui";
import { DataTable, type Column } from "./DataTable";
import { useI18n } from "../i18n";

interface VehicleB { id: string; vehicle_id: string; plate: string; make: string; model: string }
interface Tracker { id: string; vehicle: VehicleB; device_ref: string; active: boolean; last_seen_at: string | null; version: number }
interface Pos {
  id: string; vehicle: VehicleB; latitude: string; longitude: string; accuracy_m: number | null; place: string; source: "manual" | "phone" | "tracker";
  recorded_at: string; age_minutes: number; stale: boolean; note: string; void: boolean; version: number;
}

interface SilentVehicle extends VehicleB { never: boolean; last_seen_at: string | null; age_minutes: number | null }
interface Silent { hours: number; vehicles: SilentVehicle[]; trackers: Tracker[] }
interface TrailData { points: { id: string; latitude: string; longitude: string; recorded_at: string }[]; count: number; truncated: boolean; distance_km: number }

const formatTime = (d: Date, lang: string) => d.toLocaleTimeString(lang === "so" ? "so-SO" : "en-GB", { hour: "2-digit", minute: "2-digit" });
const ago = (m: number) => (m < 60 ? `${m} min` : m < 2880 ? `${Math.floor(m / 60)} h` : `${Math.floor(m / 1440)} d`);
const mapLink = (p: Pos) => `https://www.openstreetmap.org/?mlat=${p.latitude}&mlon=${p.longitude}#map=15/${p.latitude}/${p.longitude}`;
const label = (v: VehicleB) => `${v.vehicle_id}${v.plate ? ` · ${v.plate}` : ""}`;

/** Plain plot of the last known positions: no map service, no tiles. Shows how the vehicles sit relative to each other. */
function Plot({ rows }: { rows: Pos[] }) {
  if (rows.length === 0) return null;
  const pts = rows.map((p) => ({ p, lat: Number(p.latitude), lon: Number(p.longitude) }));
  const lats = pts.map((x) => x.lat), lons = pts.map((x) => x.lon);
  const midLat = (Math.min(...lats) + Math.max(...lats)) / 2;
  const k = Math.cos((midLat * Math.PI) / 180);
  const w = Math.max((Math.max(...lons) - Math.min(...lons)) * k, 0.01), h = Math.max(Math.max(...lats) - Math.min(...lats), 0.01);
  const scale = 280 / Math.max(w, h);
  const x = (lon: number) => 20 + (lon - Math.min(...lons)) * k * scale;
  const y = (lat: number) => 20 + (Math.max(...lats) - lat) * scale;
  return (
    <svg viewBox={`0 0 ${w * scale + 40} ${h * scale + 40}`} role="img" aria-label="positions" style={{ maxWidth: 480, width: "100%", border: "1px solid var(--border, #ccc)", borderRadius: 8 }}>
      <text x="8" y="12" fontSize="9" fill="currentColor">N ↑</text>
      {pts.map(({ p, lat, lon }) => (
        <g key={p.id}><circle cx={x(lon)} cy={y(lat)} r="5" fill={p.stale ? "#999" : "#c9a227"} stroke="#0b1f3a" />
          <text x={x(lon) + 8} y={y(lat) + 3} fontSize="9" fill="currentColor">{p.vehicle.vehicle_id}</text></g>
      ))}
    </svg>
  );
}

/** The route of one vehicle drawn from its recorded positions (oldest to newest). Plain SVG: no map service, no tiles. */
function Trail({ data }: { data: TrailData }) {
  const { t } = useI18n();
  if (data.count < 2) return <p className="muted">{t("trk.trailEmpty")}</p>;
  const pts = data.points.map((p) => ({ id: p.id, lat: Number(p.latitude), lon: Number(p.longitude) }));
  const lats = pts.map((x) => x.lat), lons = pts.map((x) => x.lon);
  const k = Math.cos(((Math.min(...lats) + Math.max(...lats)) / 2 * Math.PI) / 180);
  const w = Math.max((Math.max(...lons) - Math.min(...lons)) * k, 0.005), h = Math.max(Math.max(...lats) - Math.min(...lats), 0.005);
  const scale = 280 / Math.max(w, h);
  const x = (lon: number) => 20 + (lon - Math.min(...lons)) * k * scale;
  const y = (lat: number) => 20 + (Math.max(...lats) - lat) * scale;
  const first = pts[0], last = pts[pts.length - 1];
  return (
    <section className="card">
      <h3>{t("trk.trail")}</h3>
      <p>{t("trk.trailDistance", { km: data.distance_km.toFixed(1), n: data.count })}</p>
      {data.truncated && <p className="muted">{t("trk.trailTruncated", { n: data.count })}</p>}
      <svg viewBox={`0 0 ${w * scale + 40} ${h * scale + 40}`} role="img" aria-label={t("trk.trail")} style={{ maxWidth: 480, width: "100%", border: "1px solid var(--border, #ccc)", borderRadius: 8 }}>
        <text x="8" y="12" fontSize="9" fill="currentColor">N ↑</text>
        <polyline points={pts.map((q) => `${x(q.lon)},${y(q.lat)}`).join(" ")} fill="none" stroke="#c9a227" strokeWidth="2" strokeLinejoin="round" />
        {pts.slice(1, -1).map((q) => <circle key={q.id} cx={x(q.lon)} cy={y(q.lat)} r="2" fill="#0b1f3a" opacity="0.5" />)}
        <circle cx={x(first.lon)} cy={y(first.lat)} r="5" fill="#2e7d32" stroke="#0b1f3a" />
        <text x={x(first.lon) + 8} y={y(first.lat) + 3} fontSize="9" fill="currentColor">{t("trk.trailStart")}</text>
        <circle cx={x(last.lon)} cy={y(last.lat)} r="5" fill="#c9a227" stroke="#0b1f3a" />
        <text x={x(last.lon) + 8} y={y(last.lat) + 3} fontSize="9" fill="currentColor">{t("trk.trailEnd")}</text>
      </svg>
    </section>
  );
}

/** Where military vehicles are. Lives inside the Vehicles page (fleet-wide) and the vehicle detail (one vehicle); it has no page or menu item of its own. */
export function VehiclePositions({ vehicleId }: { vehicleId?: string }) {
  const { t, lang } = useI18n();
  const { can } = useAuth();
  const canReport = can("vehicles.position");
  const [picked, setVehicle] = useState("");
  const vehicle = vehicleId ?? picked;
  const [q, setQ] = useState("");
  const [lat, setLat] = useState("");
  const [lon, setLon] = useState("");
  const [acc, setAcc] = useState("");
  const [source, setSource] = useState<"manual" | "phone">("manual");
  const [locating, setLocating] = useState(false);
  const [msg, setMsg] = useState("");
  const [error, setError] = useState<unknown>(null);
  const vehicles = useFetch<Page<VehicleB>>(vehicleId ? null : "/vehicles/", { page_size: 100 });
  const latest = useFetch<{ results: Pos[] }>(vehicleId ? null : "/vehicle-tracking/latest/", { q: q.trim() || undefined });
  const history = useFetch<Page<Pos>>(vehicle ? "/vehicle-tracking/history/" : null, { vehicle, page_size: 50 });
  const trail = useFetch<TrailData>(vehicle ? "/vehicle-tracking/trail/" : null, { vehicle });
  const silent = useFetch<Silent>(vehicleId ? null : "/vehicle-tracking/silent/");
  const list = vehicles.data?.results ?? [];
  const canEdit = can("vehicles.edit");
  const trackers = useFetch<{ results: Tracker[] }>("/vehicle-tracking/trackers/");
  const [newKey, setNewKey] = useState<{ key: string; device_ref: string } | null>(null);
  const [live, setLive] = useState(false);
  const [liveInfo, setLiveInfo] = useState("");
  const watch = useRef<number | null>(null);
  const lastSent = useRef(0);
  const wake = useRef<{ release: () => Promise<void> } | null>(null);

  // Live sharing: while this page stays open the phone sends its position about once a minute (nothing is sent in the background).
  useEffect(() => {
    if (!live) return;
    if (!vehicle || !("geolocation" in navigator)) { setLive(false); setLiveInfo(t("trk.noGeo")); return; }
    type WL = { request: (k: "screen") => Promise<{ release: () => Promise<void> }> };
    const wl = (navigator as unknown as { wakeLock?: WL }).wakeLock;
    void wl?.request("screen").then((l) => { wake.current = l; }).catch(() => undefined);
    watch.current = navigator.geolocation.watchPosition(
      (g) => {
        const now = Date.now();
        if (now - lastSent.current < 60_000) return;
        lastSent.current = now;
        api("/vehicle-tracking/report/", { method: "POST", body: { vehicle, latitude: g.coords.latitude.toFixed(6), longitude: g.coords.longitude.toFixed(6), accuracy_m: Math.round(g.coords.accuracy), source: "phone" } })
          .then(() => { setLiveInfo(t("trk.liveSent", { time: formatTime(new Date(), lang) })); latest.reload(); })
          .catch(() => setLiveInfo(t("trk.liveFailed")));
      },
      () => { setLive(false); setLiveInfo(t("trk.geoDenied")); },
      { enableHighAccuracy: true, maximumAge: 15000, timeout: 30000 },
    );
    return () => {
      if (watch.current !== null) navigator.geolocation.clearWatch(watch.current);
      watch.current = null;
      void wake.current?.release().catch(() => undefined);
      wake.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [live, vehicle]);

  async function linkTracker(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = Object.fromEntries(new FormData(e.currentTarget).entries());
    setError(null);
    try {
      const r = await api<{ key: string; device_ref: string }>("/vehicle-tracking/trackers/link/", { method: "POST", body: { vehicle: f.vehicle, device_ref: f.device_ref } });
      setNewKey(r); trackers.reload(); e.currentTarget.reset();
    } catch (err) { setError(err); }
  }
  async function switchOff(x: Tracker) {
    if (!window.confirm(t("trk.confirmOff"))) return;
    setError(null);
    try { await api(`/vehicle-tracking/${x.id}/trackers/off/`, { method: "POST", body: { version: x.version } }); trackers.reload(); } catch (err) { setError(err); }
  }

  async function rotateKey(x: Tracker) {
    if (!window.confirm(t("trk.confirmRotate"))) return;
    setError(null);
    try {
      const r = await api<{ key: string; device_ref: string }>(`/vehicle-tracking/${x.id}/trackers/rotate/`, { method: "POST", body: { version: x.version } });
      setNewKey(r); trackers.reload();
    } catch (err) { setError(err); }
  }

  function locateMe() {
    setMsg("");
    if (!("geolocation" in navigator)) { setMsg(t("trk.noGeo")); return; }
    setLocating(true);
    navigator.geolocation.getCurrentPosition(
      (g) => { setLat(g.coords.latitude.toFixed(6)); setLon(g.coords.longitude.toFixed(6)); setAcc(String(Math.round(g.coords.accuracy))); setSource("phone"); setLocating(false); },
      () => { setMsg(t("trk.geoDenied")); setLocating(false); },
      { enableHighAccuracy: true, timeout: 20000, maximumAge: 0 },
    );
  }
  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = Object.fromEntries(new FormData(e.currentTarget).entries());
    const body: Record<string, unknown> = { vehicle, latitude: lat, longitude: lon, source };
    if (acc && source === "phone") body.accuracy_m = acc;
    for (const k of ["place", "note"]) if (f[k]) body[k] = f[k];
    setError(null);
    try {
      await api("/vehicle-tracking/report/", { method: "POST", body });
      setLat(""); setLon(""); setAcc(""); setMsg(t("trk.saved")); latest.reload(); history.reload(); trail.reload(); silent.reload();
    } catch (err) { setError(err); }
  }
  async function voidRow(x: Pos) {
    const reason = window.prompt(t("trk.voidReason"));
    if (!reason) return;
    setError(null);
    try { await api(`/vehicle-tracking/${x.id}/void/`, { method: "POST", body: { version: x.version, reason } }); latest.reload(); history.reload(); trail.reload(); silent.reload(); } catch (err) { setError(err); }
  }

  const cols = (withVoid: boolean): Column<Pos>[] => [
    { id: "vehicle", header: t("trk.vehicle"), cell: (x) => label(x.vehicle), sort: (x) => x.vehicle.vehicle_id },
    { id: "pos", header: t("trk.position"), cell: (x) => <a href={mapLink(x)} target="_blank" rel="noopener noreferrer">{x.latitude}, {x.longitude}</a> },
    { id: "place", header: t("trk.place"), cell: (x) => x.place || "—" },
    { id: "when", header: t("trk.when"), cell: (x) => x.recorded_at.slice(0, 16).replace("T", " "), sort: (x) => x.recorded_at },
    { id: "age", header: t("trk.age"), align: "right", cell: (x) => <>{ago(x.age_minutes)} {x.stale && <Chip tone="bad">{t("trk.stale")}</Chip>}</>, sort: (x) => x.age_minutes },
    { id: "src", header: t("trk.source"), cell: (x) => t(`trk.source.${x.source}` as never) + (x.accuracy_m != null ? ` ±${x.accuracy_m} m` : "") },
    ...(withVoid ? [{ id: "act", header: "", cell: (x: Pos) => canReport && !x.void ? <button type="button" className="secondary" onClick={() => void voidRow(x)}>{t("trk.void")}</button> : null }] : []),
  ];

  const rows = latest.data?.results ?? [];
  const feedUrl = `${window.location.origin}/api/v1/tracker/feed/`;
  return (
    <>
      <h2>{t("trk.title")}</h2>
      <p className="muted">{t("trk.subtitle")}</p>
      {error != null && <ErrorNotice error={error} />}
      {!vehicleId && silent.data && (
        <section className="card" role="status" aria-live="polite">
          <h3>{t("trk.silentTitle")}</h3>
          <p className="muted">{t("trk.silentHelp", { hours: silent.data.hours })}</p>
          {silent.data.vehicles.length === 0 && silent.data.trackers.length === 0 && <p>{t("trk.silentNone")}</p>}
          {silent.data.vehicles.length > 0 && (
            <ul>{silent.data.vehicles.map((v) => (
              <li key={v.id}>{label(v)} · {v.never || v.age_minutes === null ? <Chip tone="bad">{t("trk.silentNever")}</Chip> : t("trk.silentLast", { age: ago(v.age_minutes) })}</li>
            ))}</ul>
          )}
          {silent.data.trackers.length > 0 && (
            <>
              <p><strong>{t("trk.silentTrackers")}</strong></p>
              <ul>{silent.data.trackers.map((x) => <li key={x.id}>{label(x.vehicle)} · {x.device_ref} · {x.last_seen_at ? `${t("trk.lastSeen")} ${x.last_seen_at.slice(0, 16).replace("T", " ")}` : t("trk.neverSeen")}</li>)}</ul>
            </>
          )}
        </section>
      )}
      {canReport && (
        <form onSubmit={(e) => void submit(e)} className="card">
          {!vehicleId && <Field label={t("trk.vehicle")}>
            <select value={vehicle} required onChange={(e) => setVehicle(e.target.value)}>
              <option value="" disabled>—</option>{list.map((v) => <option key={v.id} value={v.id}>{label(v)} — {v.make} {v.model}</option>)}
            </select>
          </Field>}
          <button type="button" className="secondary" onClick={locateMe} disabled={locating}>{locating ? t("trk.locating") : t("trk.locateMe")}</button>
          <Field label={t("trk.lat")}><input value={lat} onChange={(e) => { setLat(e.target.value); setSource("manual"); }} required inputMode="decimal" placeholder="8.405500" /></Field>
          <Field label={t("trk.lon")}><input value={lon} onChange={(e) => { setLon(e.target.value); setSource("manual"); }} required inputMode="decimal" placeholder="48.483700" /></Field>
          <Field label={t("trk.place")}><input name="place" maxLength={150} /></Field>
          <Field label={t("trk.note")}><input name="note" maxLength={200} /></Field>
          <button type="submit">{t("trk.report")}</button>{" "}
          <button type="button" className={live ? "" : "secondary"} onClick={() => { setLiveInfo(""); setLive(!live); }} disabled={!vehicle}>{live ? t("trk.liveStop") : t("trk.liveStart")}</button>
          <p className="muted">{t("trk.privacy")}</p>
          {live && <p role="status">{t("trk.liveOn")}</p>}
          {liveInfo && <p role="status">{liveInfo}</p>}
          {msg && <p role="status">{msg}</p>}
        </form>
      )}
      {!vehicleId && <Field label={t("common.search")}><input type="search" value={q} onChange={(e) => setQ(e.target.value)} maxLength={40} /></Field>}
      {!vehicleId && <Plot rows={rows} />}
      {!vehicleId && <DataTable id="vehicle-latest" caption={t("trk.latest")} columns={cols(true)} rows={rows} rowKey={(x) => x.id} loading={latest.loading} empty={{ title: t("trk.empty") }} />}
      {!vehicleId && <Field label={t("trk.historyOf")}>
        <select value={vehicle} onChange={(e) => setVehicle(e.target.value)}>
          <option value="">—</option>{list.map((v) => <option key={v.id} value={v.id}>{label(v)}</option>)}
        </select>
      </Field>}
      {vehicle && <DataTable id="vehicle-history" caption={t("trk.history")} columns={cols(true)} rows={history.data?.results ?? []} rowKey={(x) => x.id} loading={history.loading} empty={{ title: t("trk.empty") }} />}
      {vehicle && trail.data && <Trail data={trail.data} />}
      {(canEdit || (trackers.data?.results?.length ?? 0) > 0) && (
        <section className="card">
          <h2>{t("trk.trackers")}</h2>
          <p className="muted">{t("trk.trackersHelp")}</p>
          {newKey && (
            <div role="status" className="card">
              <p><strong>{t("trk.keyOnce")}</strong></p>
              <p><code>{feedUrl}?key={newKey.key}&amp;id={newKey.device_ref}&amp;lat={"{latitude}"}&amp;lon={"{longitude}"}&amp;timestamp={"{time}"}&amp;accuracy={"{accuracy}"}</code></p>
              <button type="button" className="secondary" onClick={() => setNewKey(null)}>{t("trk.keySaved")}</button>
            </div>
          )}
          {canEdit && (
            <form onSubmit={(e) => void linkTracker(e)}>
              {vehicleId ? <input type="hidden" name="vehicle" value={vehicleId} /> : <Field label={t("trk.vehicle")}><select name="vehicle" required defaultValue=""><option value="" disabled>—</option>{list.map((v) => <option key={v.id} value={v.id}>{label(v)}</option>)}</select></Field>}
              <Field label={t("trk.deviceRef")}><input name="device_ref" required maxLength={60} /></Field>
              <button type="submit">{t("trk.link")}</button>
            </form>
          )}
          <ul>
            {(trackers.data?.results ?? []).filter((x) => !vehicleId || x.vehicle.id === vehicleId).map((x) => (
              <li key={x.id}>{label(x.vehicle)} · {x.device_ref} · {x.active ? (x.last_seen_at ? `${t("trk.lastSeen")} ${x.last_seen_at.slice(0, 16).replace("T", " ")}` : t("trk.neverSeen")) : t("trk.off")}{" "}
                {canEdit && x.active && <button type="button" className="secondary" onClick={() => void rotateKey(x)}>{t("trk.rotate")}</button>}{" "}
                {canEdit && x.active && <button type="button" className="secondary" onClick={() => void switchOff(x)}>{t("trk.switchOff")}</button>}</li>
            ))}
          </ul>
        </section>
      )}
    </>
  );
}
