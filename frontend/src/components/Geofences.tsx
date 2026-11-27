import { useEffect, useState, type FormEvent } from "react";
import { api, downloadCsv } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { useFetch } from "../api/useFetch";
import type { MapDraft } from "./VehicleMap";
import { Chip, ErrorNotice, Field } from "./ui";
import { DataTable, type Column } from "./DataTable";
import { useI18n } from "../i18n";

interface VehicleB { id: string; vehicle_id: string; plate: string; make: string; model: string }
export interface Zone { id: string; name: string; shape: "circle" | "polygon"; points: [number, number][]; latitude: string; longitude: string; radius_m: number; alert_on: "enter" | "exit" | "both"; active: boolean; version: number }
interface ZoneEvent { id: string; kind: "enter" | "exit"; occurred_at: string; geofence: { id: string; name: string }; vehicle: VehicleB }
interface DayRow {
  vehicle: VehicleB; unit: string; positions: number; distance_km: number; first_at: string; last_at: string;
  zones: { geofence_id: string; name: string; minutes_inside: number; entered: number; left: number }[];
}
interface Report {
  date: string; timezone: string;
  summary: { vehicles_in_scope: number; vehicles_reporting: number; vehicles_not_reporting: number; positions: number; distance_km: number; zone_events: number };
  vehicles: DayRow[]; not_reporting: (VehicleB & { unit: string })[];
}

const label = (v: VehicleB) => `${v.vehicle_id}${v.plate ? ` · ${v.plate}` : ""}`;
const hhmm = (iso: string) => iso.slice(11, 16);
const today = () => new Date().toISOString().slice(0, 10);

export interface DrawState { draft: MapDraft; setDraft: (d: MapDraft) => void; picking: boolean; setPicking: (b: boolean) => void }

/** Zones (circles or polygons drawn on the map) that record when a vehicle enters or leaves, the recent crossings, and the daily movement report. */
export function Geofences({ zones, reloadZones, mapOn, draw }: { zones: Zone[]; reloadZones: () => void; mapOn: boolean; draw: DrawState }) {
  const { t } = useI18n();
  const { can } = useAuth();
  const canEdit = can("vehicles.edit");
  const events = useFetch<{ results: ZoneEvent[] }>("/vehicle-tracking/geofence-events/", { limit: "50" });
  const [day, setDay] = useState(today());
  const [shown, setShown] = useState<string | null>(null);
  const report = useFetch<Report>(shown ? "/vehicle-tracking/daily-report/" : null, { date: shown ?? "" });
  const [error, setError] = useState<unknown>(null);
  const [lat, setLat] = useState("");
  const [lon, setLon] = useState("");
  const [msg, setMsg] = useState("");
  const { draft, setDraft, picking, setPicking } = draw;
  const polygon = draft.shape === "polygon";

  // typed centre -> preview on the map
  useEffect(() => {
    if (polygon) return;
    const la = Number(lat), lo = Number(lon);
    if (lat.trim() === "" || lon.trim() === "" || !Number.isFinite(la) || !Number.isFinite(lo) || Math.abs(la) > 90 || Math.abs(lo) > 180) return;
    const cur = draft.points[0];
    if (cur && Math.abs(cur[0] - la) < 1e-7 && Math.abs(cur[1] - lo) < 1e-7) return;
    setDraft({ ...draft, points: [[la, lo]] });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lat, lon, polygon]);
  // a click or a drag on the map -> the centre fields
  useEffect(() => {
    if (polygon) return;
    const c = draft.points[0];
    if (!c) return;
    if (Math.abs(Number(lat) - c[0]) < 1e-7 && Math.abs(Number(lon) - c[1]) < 1e-7) return;
    setLat(c[0].toFixed(6)); setLon(c[1].toFixed(6));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draft.points, polygon]);
  const setShape = (shape: "circle" | "polygon") => { setDraft({ shape, points: [], radius: draft.radius }); setLat(""); setLon(""); setPicking(shape === "polygon"); };

  function fillMyLocation() {
    setMsg("");
    if (!("geolocation" in navigator)) { setMsg(t("trk.noGeo")); return; }
    navigator.geolocation.getCurrentPosition(
      (g) => { setLat(g.coords.latitude.toFixed(6)); setLon(g.coords.longitude.toFixed(6)); },
      () => setMsg(t("trk.geoDenied")),
      { enableHighAccuracy: true, timeout: 20000, maximumAge: 0 },
    );
  }
  async function addZone(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const f = Object.fromEntries(new FormData(form).entries());
    setError(null); setMsg("");
    try {
      if (polygon) {
        if (draft.points.length < 3) { setMsg(t("geo.needCorners")); return; }
        await api("/vehicle-tracking/geofences/add/", { method: "POST", body: { name: f.name, shape: "polygon", points: draft.points, alert_on: f.alert_on } });
      } else {
        await api("/vehicle-tracking/geofences/add/", { method: "POST", body: { name: f.name, latitude: lat, longitude: lon, radius_m: f.radius_m, alert_on: f.alert_on } });
      }
      reloadZones(); form.reset(); setLat(""); setLon(""); setDraft({ shape: draft.shape, points: [], radius: 500 }); setPicking(false);
    } catch (err) { setError(err); }
  }
  async function toggle(z: Zone) {
    setError(null);
    try { await api(`/vehicle-tracking/${z.id}/geofences/update/`, { method: "POST", body: { version: z.version, active: !z.active } }); reloadZones(); events.reload(); } catch (err) { setError(err); }
  }
  async function download() {
    setError(null);
    try { await downloadCsv("/vehicle-tracking/daily-report/export/", { date: day }, `daily-movement-${day}.csv`); } catch (err) { setError(err); }
  }

  const zoneCols: Column<Zone>[] = [
    { id: "name", header: t("geo.name"), cell: (z) => <>{z.name} {!z.active && <Chip tone="warn">{t("geo.off")}</Chip>}</>, sort: (z) => z.name },
    { id: "shape", header: t("geo.shape"), cell: (z) => (z.shape === "polygon" ? t("geo.corners", { n: z.points.length }) : t("geo.shape.circle")) },
    { id: "centre", header: `${t("trk.lat")} / ${t("trk.lon")}`, cell: (z) => `${z.latitude}, ${z.longitude}` },
    { id: "radius", header: t("geo.radius"), cell: (z) => (z.shape === "polygon" ? "—" : `${z.radius_m} m`), sort: (z) => z.radius_m, align: "right" },
    { id: "alert", header: t("geo.alertOn"), cell: (z) => t(`geo.alert.${z.alert_on}`) },
    ...(canEdit ? [{ id: "act", header: "", cell: (z: Zone) => <button type="button" className="secondary" onClick={() => void toggle(z)}>{z.active ? t("geo.switchOff") : t("geo.switchOn")}</button> }] : []),
  ];
  const eventCols: Column<ZoneEvent>[] = [
    { id: "when", header: t("geo.when"), cell: (x) => x.occurred_at.slice(0, 16).replace("T", " "), sort: (x) => x.occurred_at },
    { id: "veh", header: t("trk.vehicle"), cell: (x) => label(x.vehicle) },
    { id: "zone", header: t("geo.zone"), cell: (x) => x.geofence.name },
    { id: "kind", header: "", cell: (x) => <Chip tone={x.kind === "enter" ? "ok" : "warn"}>{x.kind === "enter" ? t("geo.entered") : t("geo.left")}</Chip> },
  ];
  const dayCols: Column<DayRow>[] = [
    { id: "veh", header: t("trk.vehicle"), cell: (x) => label(x.vehicle), sort: (x) => x.vehicle.vehicle_id },
    { id: "n", header: t("geo.positions"), cell: (x) => x.positions, sort: (x) => x.positions, align: "right" },
    { id: "km", header: t("geo.km"), cell: (x) => x.distance_km.toFixed(1), sort: (x) => x.distance_km, align: "right" },
    { id: "fl", header: t("geo.firstLast"), cell: (x) => `${hhmm(x.first_at)} / ${hhmm(x.last_at)}` },
    { id: "z", header: t("geo.zonesCol"), cell: (x) => x.zones.map((z) => t("geo.zoneLine", { name: z.name, minutes: z.minutes_inside, in: z.entered, out: z.left })).join("; ") },
  ];
  const r = report.data;

  return (
    <section aria-labelledby="geo-title">
      <h2 id="geo-title">{t("geo.title")}</h2>
      {error != null && <ErrorNotice error={error} />}

      <h3>{t("geo.zones")}</h3>
      <p className="muted">{t("geo.zonesHelp")}</p>
      <DataTable id="geofences" caption={t("geo.zones")} columns={zoneCols} rows={zones} rowKey={(z) => z.id} empty={{ title: t("geo.none") }} />
      {canEdit && (
        <form onSubmit={(e) => void addZone(e)} className="card">
          <Field label={t("geo.name")}><input name="name" required maxLength={100} /></Field>
          {mapOn && (
            <Field label={t("geo.shape")}>
              <select value={draft.shape} onChange={(e) => setShape(e.target.value as "circle" | "polygon")}>
                <option value="circle">{t("geo.shape.circle")}</option>
                <option value="polygon">{t("geo.shape.polygon")}</option>
              </select>
            </Field>
          )}
          {!polygon && <>
            <Field label={t("trk.lat")}><input value={lat} onChange={(e) => setLat(e.target.value)} required inputMode="decimal" placeholder="8.405500" /></Field>
            <Field label={t("trk.lon")}><input value={lon} onChange={(e) => setLon(e.target.value)} required inputMode="decimal" placeholder="48.483700" /></Field>
            <Field label={t("geo.radius")}>
              <input name="radius_m" required inputMode="numeric" value={String(draft.radius)} onChange={(e) => setDraft({ ...draft, radius: Number(e.target.value.replace(/\D/g, "")) || 0 })} />
            </Field>
          </>}
          {polygon && <p>{t("geo.corners", { n: draft.points.length })}{draft.points.length < 3 ? ` — ${t("geo.needCorners")}` : ""}</p>}
          {mapOn && (
            <p>
              <button type="button" className={picking ? "" : "secondary"} onClick={() => setPicking(!picking)}>{picking ? t("geo.pickStop") : t("geo.pick")}</button>{" "}
              {polygon && <button type="button" className="secondary" disabled={draft.points.length === 0} onClick={() => setDraft({ ...draft, points: draft.points.slice(0, -1) })}>{t("geo.undoCorner")}</button>}{" "}
              {draft.points.length > 0 && <button type="button" className="secondary" onClick={() => { setDraft({ ...draft, points: [] }); setLat(""); setLon(""); }}>{t("geo.clearCorners")}</button>}
            </p>
          )}
          <Field label={t("geo.alertOn")}>
            <select name="alert_on" defaultValue="both">
              <option value="both">{t("geo.alert.both")}</option>
              <option value="enter">{t("geo.alert.enter")}</option>
              <option value="exit">{t("geo.alert.exit")}</option>
            </select>
          </Field>
          {!polygon && <button type="button" className="secondary" onClick={fillMyLocation}>{t("geo.fillMyLocation")}</button>}
          {msg && <p role="status">{msg}</p>}
          <button type="submit">{t("geo.add")}</button>
        </form>
      )}

      <h3>{t("geo.events")}</h3>
      <DataTable id="geofence-events" caption={t("geo.events")} columns={eventCols} rows={events.data?.results ?? []} rowKey={(x) => x.id} loading={events.loading} empty={{ title: t("geo.eventsEmpty") }} />

      <h3>{t("geo.report")}</h3>
      <p className="muted">{t("geo.reportHelp", { tz: r?.timezone ?? "UTC" })}</p>
      <div className="card">
        <Field label={t("geo.date")}><input type="date" value={day} max={today()} onChange={(e) => setDay(e.target.value)} /></Field>
        <button type="button" onClick={() => setShown(day)} disabled={!day}>{t("geo.show")}</button>{" "}
        <button type="button" className="secondary" onClick={() => void download()} disabled={!day}>{t("geo.downloadCsv")}</button>
      </div>
      {report.error && <ErrorNotice error={report.error} />}
      {r && (
        <>
          <p role="status">{t("geo.summary", { reporting: r.summary.vehicles_reporting, total: r.summary.vehicles_in_scope, km: r.summary.distance_km.toFixed(1), events: r.summary.zone_events })}</p>
          <DataTable id="daily-report" caption={t("geo.report")} columns={dayCols} rows={r.vehicles} rowKey={(x) => x.vehicle.id} loading={report.loading} empty={{ title: t("trk.empty") }} />
          {r.not_reporting.length > 0 && (
            <details>
              <summary>{t("geo.notReporting", { n: r.not_reporting.length })}</summary>
              <ul>{r.not_reporting.map((v) => <li key={v.id}>{label(v)}</li>)}</ul>
            </details>
          )}
        </>
      )}
    </section>
  );
}
