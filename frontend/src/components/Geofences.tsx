import { useState, type FormEvent } from "react";
import { api, downloadCsv } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { useFetch } from "../api/useFetch";
import { Chip, ErrorNotice, Field } from "./ui";
import { DataTable, type Column } from "./DataTable";
import { useI18n } from "../i18n";

interface VehicleB { id: string; vehicle_id: string; plate: string; make: string; model: string }
interface Zone { id: string; name: string; latitude: string; longitude: string; radius_m: number; alert_on: "enter" | "exit" | "both"; active: boolean; version: number }
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

/** Zones (circles) that record when a vehicle enters or leaves, the recent crossings, and the daily movement report. */
export function Geofences() {
  const { t } = useI18n();
  const { can } = useAuth();
  const canEdit = can("vehicles.edit");
  const zones = useFetch<{ results: Zone[] }>("/vehicle-tracking/geofences/");
  const events = useFetch<{ results: ZoneEvent[] }>("/vehicle-tracking/geofence-events/", { limit: "50" });
  const [day, setDay] = useState(today());
  const [shown, setShown] = useState<string | null>(null);
  const report = useFetch<Report>(shown ? "/vehicle-tracking/daily-report/" : null, { date: shown ?? "" });
  const [error, setError] = useState<unknown>(null);
  const [lat, setLat] = useState("");
  const [lon, setLon] = useState("");
  const [msg, setMsg] = useState("");

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
    setError(null);
    try {
      await api("/vehicle-tracking/geofences/add/", { method: "POST", body: { name: f.name, latitude: lat, longitude: lon, radius_m: f.radius_m, alert_on: f.alert_on } });
      zones.reload(); form.reset(); setLat(""); setLon("");
    } catch (err) { setError(err); }
  }
  async function toggle(z: Zone) {
    setError(null);
    try { await api(`/vehicle-tracking/${z.id}/geofences/update/`, { method: "POST", body: { version: z.version, active: !z.active } }); zones.reload(); events.reload(); } catch (err) { setError(err); }
  }
  async function download() {
    setError(null);
    try { await downloadCsv("/vehicle-tracking/daily-report/export/", { date: day }, `daily-movement-${day}.csv`); } catch (err) { setError(err); }
  }

  const zoneCols: Column<Zone>[] = [
    { id: "name", header: t("geo.name"), cell: (z) => <>{z.name} {!z.active && <Chip tone="warn">{t("geo.off")}</Chip>}</>, sort: (z) => z.name },
    { id: "centre", header: `${t("trk.lat")} / ${t("trk.lon")}`, cell: (z) => `${z.latitude}, ${z.longitude}` },
    { id: "radius", header: t("geo.radius"), cell: (z) => `${z.radius_m} m`, sort: (z) => z.radius_m, align: "right" },
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
      <DataTable id="geofences" caption={t("geo.zones")} columns={zoneCols} rows={zones.data?.results ?? []} rowKey={(z) => z.id} loading={zones.loading} empty={{ title: t("geo.none") }} />
      {canEdit && (
        <form onSubmit={(e) => void addZone(e)} className="card">
          <Field label={t("geo.name")}><input name="name" required maxLength={100} /></Field>
          <Field label={t("trk.lat")}><input value={lat} onChange={(e) => setLat(e.target.value)} required inputMode="decimal" placeholder="8.405500" /></Field>
          <Field label={t("trk.lon")}><input value={lon} onChange={(e) => setLon(e.target.value)} required inputMode="decimal" placeholder="48.483700" /></Field>
          <Field label={t("geo.radius")}><input name="radius_m" required inputMode="numeric" defaultValue="500" /></Field>
          <Field label={t("geo.alertOn")}>
            <select name="alert_on" defaultValue="both">
              <option value="both">{t("geo.alert.both")}</option>
              <option value="enter">{t("geo.alert.enter")}</option>
              <option value="exit">{t("geo.alert.exit")}</option>
            </select>
          </Field>
          <button type="button" className="secondary" onClick={fillMyLocation}>{t("geo.fillMyLocation")}</button>
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
