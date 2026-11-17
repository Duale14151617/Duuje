import { useState, type FormEvent } from "react";
import { api } from "../api/client";
import type { Page } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { useFetch } from "../api/useFetch";
import { Chip, ErrorNotice, Field, PageHeader } from "../components/ui";
import { DataTable, type Column } from "../components/DataTable";
import { useI18n } from "../i18n";

interface VehicleB { id: string; vehicle_id: string; plate: string; make: string; model: string }
interface PersonB { full_name: string; service_number: string | null }
interface Trip {
  id: string; vehicle: VehicleB; driver: PersonB | null; purpose: string; origin: string; destination: string; authority_ref: string;
  started_at: string; ended_at: string | null; start_odometer: number; end_odometer: number | null; distance_km: number | null;
  state: "open" | "completed" | "void"; version: number;
}
interface Fuel {
  id: string; vehicle: VehicleB; filled_on: string; fuel_type: string; litres: string; odometer: number; full_tank: boolean; station: string;
  receipt_ref: string; void: boolean; version: number; cost?: string | null; currency?: string;
}
interface LogSummary { trips: number; distance_km: number; fuel_entries: number; litres: string; litres_per_100km: number | null; cost?: string }

const label = (v: VehicleB) => `${v.vehicle_id}${v.plate ? ` · ${v.plate}` : ""}`;
const day = (s: string | null) => (s ? s.slice(0, 10) : "—");
const today = () => new Date().toISOString().slice(0, 10);

export function VehicleLog() {
  const { t } = useI18n();
  const { can } = useAuth();
  const [tab, setTab] = useState<"trips" | "fuel">("trips");
  const [vehicle, setVehicle] = useState("");
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const vehicles = useFetch<Page<VehicleB>>("/vehicles/", { page_size: 100 });
  const list = vehicles.data?.results ?? [];
  const q = vehicle ? { vehicle } : {};
  const trips = useFetch<Page<Trip>>(tab === "trips" ? "/vehicle-log/trips/" : null, { ...q, include_void: "1" });
  const fuel = useFetch<Page<Fuel>>(tab === "fuel" ? "/vehicle-log/fuel/" : null, { ...q, include_void: "1" });
  const summary = useFetch<LogSummary>(vehicle ? "/vehicle-log/summary/" : null, q);
  const canEdit = can("vehicles.edit");
  const reload = () => { trips.reload(); fuel.reload(); summary.reload(); };

  async function act(path: string, body: Record<string, unknown>) {
    setError(null);
    try { await api(path, { method: "POST", body }); reload(); } catch (e) { setError(e); }
  }
  const endTrip = (x: Trip) => { const v = window.prompt(t("vlog.endOdo")); if (v) void act(`/vehicle-log/trips/${x.id}/end/`, { version: x.version, end_odometer: v }); };
  const voidRow = (kind: "trips" | "fuel", x: { id: string; version: number }) => {
    const reason = window.prompt(t("vlog.voidReason")); if (reason) void act(`/vehicle-log/${kind}/${x.id}/void/`, { version: x.version, reason });
  };

  const tripCols: Column<Trip>[] = [
    { id: "date", header: t("vlog.started"), cell: (x) => day(x.started_at), sort: (x) => x.started_at },
    { id: "vehicle", header: t("vlog.vehicle"), cell: (x) => label(x.vehicle), sort: (x) => x.vehicle.vehicle_id },
    { id: "driver", header: t("vlog.driver"), cell: (x) => x.driver?.full_name ?? "—" },
    { id: "purpose", header: t("vlog.purpose"), cell: (x) => x.purpose },
    { id: "route", header: t("vlog.route"), cell: (x) => [x.origin, x.destination].filter(Boolean).join(" → ") || "—" },
    { id: "odo", header: t("vlog.odometer"), align: "right", cell: (x) => `${x.start_odometer} → ${x.end_odometer ?? "…"}` },
    { id: "km", header: t("vlog.km"), align: "right", cell: (x) => x.distance_km ?? "—", sort: (x) => x.distance_km },
    { id: "state", header: t("vlog.state"), cell: (x) => <Chip tone={x.state === "open" ? "draft" : x.state === "void" ? "bad" : "approved"}>{t(`vlog.state.${x.state}` as never)}</Chip> },
    { id: "actions", header: "", cell: (x) => canEdit && x.state !== "void" ? (
      <span>{x.state === "open" && <button type="button" className="secondary" onClick={() => endTrip(x)}>{t("vlog.endTrip")}</button>}{" "}
        <button type="button" className="secondary" onClick={() => voidRow("trips", x)}>{t("vlog.void")}</button></span>) : null },
  ];
  const fuelCols: Column<Fuel>[] = [
    { id: "date", header: t("vlog.date"), cell: (x) => x.filled_on, sort: (x) => x.filled_on },
    { id: "vehicle", header: t("vlog.vehicle"), cell: (x) => label(x.vehicle), sort: (x) => x.vehicle.vehicle_id },
    { id: "type", header: t("vlog.fuelType"), cell: (x) => t(`vlog.fuel.${x.fuel_type}` as never) },
    { id: "litres", header: t("vlog.litres"), align: "right", cell: (x) => x.litres, sort: (x) => Number(x.litres) },
    { id: "odo", header: t("vlog.odometer"), align: "right", cell: (x) => x.odometer, sort: (x) => x.odometer },
    ...(fuel.data?.results.some((x) => x.cost !== undefined) ? [{ id: "cost", header: t("vlog.cost"), align: "right" as const, cell: (x: Fuel) => (x.cost ? `${x.cost} ${x.currency ?? ""}` : "—") }] : []),
    { id: "station", header: t("vlog.station"), cell: (x) => x.station || "—" },
    { id: "state", header: t("vlog.state"), cell: (x) => (x.void ? <Chip tone="bad">{t("vlog.state.void")}</Chip> : null) },
    { id: "actions", header: "", cell: (x) => canEdit && !x.void ? <button type="button" className="secondary" onClick={() => voidRow("fuel", x)}>{t("vlog.void")}</button> : null },
  ];

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = Object.fromEntries(new FormData(e.currentTarget).entries());
    const body: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(f)) if (v !== "") body[k] = v;
    if (tab === "fuel") body.full_tank = f.full_tank === "on";
    setError(null);
    try { await api(tab === "trips" ? "/vehicle-log/trips/start/" : "/vehicle-log/fuel/add/", { method: "POST", body }); setAdding(false); reload(); } catch (err) { setError(err); }
  }

  const s = summary.data;
  return (
    <>
      <PageHeader title={t("vlog.title")} subtitle={t("vlog.subtitle")}
        actions={canEdit ? <button type="button" onClick={() => setAdding(!adding)}>{tab === "trips" ? t("vlog.startTrip") : t("vlog.addFuel")}</button> : undefined} />
      <div className="row">
        <button type="button" className={tab === "trips" ? "" : "secondary"} onClick={() => { setTab("trips"); setAdding(false); }}>{t("vlog.tripLog")}</button>{" "}
        <button type="button" className={tab === "fuel" ? "" : "secondary"} onClick={() => { setTab("fuel"); setAdding(false); }}>{t("vlog.fuelLog")}</button>
        <Field label={t("vlog.vehicle")}>
          <select value={vehicle} onChange={(e) => setVehicle(e.target.value)}>
            <option value="">{t("vlog.allVehicles")}</option>
            {list.map((v) => <option key={v.id} value={v.id}>{label(v)} — {v.make} {v.model}</option>)}
          </select>
        </Field>
      </div>
      {s && <p>{t("vlog.summary", { trips: s.trips, km: s.distance_km, litres: s.litres, rate: s.litres_per_100km ?? "—" })}{s.cost !== undefined ? ` · ${t("vlog.cost")}: ${s.cost}` : ""}</p>}
      {error != null && <ErrorNotice error={error} />}
      {adding && (
        <form onSubmit={(e) => void submit(e)} className="card">
          <Field label={t("vlog.vehicle")}>
            <select name="vehicle" required defaultValue={vehicle}>
              <option value="" disabled>—</option>
              {list.map((v) => <option key={v.id} value={v.id}>{label(v)}</option>)}
            </select>
          </Field>
          {tab === "trips" ? (<>
            <Field label={t("vlog.purpose")}><input name="purpose" required maxLength={200} /></Field>
            <Field label={t("vlog.origin")}><input name="origin" maxLength={150} /></Field>
            <Field label={t("vlog.destination")}><input name="destination" maxLength={150} /></Field>
            <Field label={t("vlog.orderRef")}><input name="authority_ref" maxLength={150} /></Field>
            <Field label={t("vlog.startOdo")}><input name="start_odometer" type="number" min={0} required inputMode="numeric" /></Field>
          </>) : (<>
            <Field label={t("vlog.date")}><input name="filled_on" type="date" required defaultValue={today()} max={today()} /></Field>
            <Field label={t("vlog.fuelType")}>
              <select name="fuel_type" defaultValue="diesel"><option value="diesel">{t("vlog.fuel.diesel")}</option><option value="petrol">{t("vlog.fuel.petrol")}</option><option value="other">{t("vlog.fuel.other")}</option></select>
            </Field>
            <Field label={t("vlog.litres")}><input name="litres" type="number" step="0.01" min="0.01" required inputMode="decimal" /></Field>
            <Field label={t("vlog.odometer")}><input name="odometer" type="number" min={0} required inputMode="numeric" /></Field>
            {can("vehicles.cost") && <><Field label={t("vlog.cost")}><input name="cost" type="number" step="0.01" min={0} inputMode="decimal" /></Field>
              <Field label={t("vlog.currency")}><input name="currency" maxLength={3} /></Field></>}
            <Field label={t("vlog.station")}><input name="station" maxLength={150} /></Field>
            <Field label={t("vlog.receipt")}><input name="receipt_ref" maxLength={150} /></Field>
            <label className="field"><span>{t("vlog.fullTank")}</span><input name="full_tank" type="checkbox" defaultChecked /></label>
          </>)}
          <button type="submit">{t("vlog.save")}</button>
        </form>
      )}
      {tab === "trips"
        ? <DataTable id="vehicle-trips" caption={t("vlog.tripLog")} columns={tripCols} rows={trips.data?.results ?? []} rowKey={(x) => x.id} loading={trips.loading} empty={{ title: t("vlog.empty") }} />
        : <DataTable id="vehicle-fuel" caption={t("vlog.fuelLog")} columns={fuelCols} rows={fuel.data?.results ?? []} rowKey={(x) => x.id} loading={fuel.loading} empty={{ title: t("vlog.empty") }} />}
    </>
  );
}
