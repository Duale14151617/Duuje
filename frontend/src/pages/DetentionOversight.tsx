import { useState } from "react";
import { useAuth } from "../auth/AuthContext";
import { useFetch } from "../api/useFetch";
import { Chip, PageHeader } from "../components/ui";
import { DataTable, type Column } from "../components/DataTable";
import { UnitPicker } from "../components/UnitPicker";
import { useI18n } from "../i18n";

interface UnitB { id: string; code: string; name_en: string; name_so: string }
interface Totals {
  stations: number; operational: number; unverified: number; out_of_use: number; no_facility: number; in_custody: number; overdue_reviews: number;
  capacity: number; available: number; stations_with_known_capacity: number; over_capacity_stations: number; held_without_verified_facility: number;
  incoming: number; admitted: number; received: number; released: number; transferred_out: number;
}
interface Group extends Totals { unit: UnitB | null }
interface Station {
  unit: UnitB; region: UnitB | null; district: UnitB | null; facility_state: "operational" | "unverified" | "out_of_use" | "no_facility";
  in_custody: number; capacity: number | null; available: number | null; over_capacity: boolean; overdue_reviews: number;
  held_without_verified_facility: number; incoming: number; admitted: number; received: number; released: number; transferred_out: number;
}
interface Data { as_of: string; days: number; review_hours: number; totals: Totals; regions: Group[]; districts: Group[]; stations_without_district: number; stations: Station[] }
interface Hier { stations: number; errors: number; warnings: number; info: number; findings: { severity: string; code: string; unit: string; message: string }[] }

const tone = (s: string) => (s === "operational" ? "approved" : s === "unverified" ? "draft" : "bad");

export function DetentionOversight() {
  const { t, name } = useI18n();
  const { can } = useAuth();
  const [unit, setUnit] = useState("");
  const [days, setDays] = useState(30);
  const data = useFetch<Data>("/detention-oversight/", { unit: unit || undefined, days });
  const hier = useFetch<Hier>(can("detention.verify") ? "/detention-oversight/hierarchy/" : null);
  const d = data.data;

  const num = (n: number | null, extra?: string) => (n == null ? t("ovr.notSet") : `${n}${extra ?? ""}`);
  const groupCols = (label: string): Column<Group>[] => [
    { id: "u", header: label, cell: (g) => (g.unit ? name(g.unit) : "—"), sort: (g) => g.unit?.name_en ?? "" },
    { id: "st", header: t("ovr.stations"), align: "right", cell: (g) => `${g.operational}/${g.stations}` },
    { id: "held", header: t("ovr.held"), align: "right", cell: (g) => g.in_custody, sort: (g) => g.in_custody },
    { id: "free", header: t("ovr.free"), align: "right", cell: (g) => (g.stations_with_known_capacity ? g.available : t("ovr.notSet")) },
    { id: "od", header: t("ovr.overdue"), align: "right", cell: (g) => (g.overdue_reviews ? <Chip tone="bad">{g.overdue_reviews}</Chip> : 0), sort: (g) => g.overdue_reviews },
    { id: "adm", header: t("ovr.admitted"), align: "right", cell: (g) => g.admitted },
    { id: "rel", header: t("ovr.released"), align: "right", cell: (g) => g.released },
    { id: "tr", header: t("ovr.transferred"), align: "right", cell: (g) => g.transferred_out },
    { id: "in", header: t("ovr.incoming"), align: "right", cell: (g) => g.incoming },
  ];
  const cols: Column<Station>[] = [
    { id: "u", header: t("ovr.stations"), cell: (r) => name(r.unit), sort: (r) => r.unit.name_en },
    { id: "reg", header: t("ovr.region"), cell: (r) => (r.region ? name(r.region) : "—") },
    { id: "dis", header: t("ovr.district"), cell: (r) => (r.district ? name(r.district) : "—") },
    { id: "state", header: t("ovr.state"), cell: (r) => <Chip tone={tone(r.facility_state)}>{t(`ovr.state.${r.facility_state}` as never)}</Chip>, sort: (r) => r.facility_state },
    { id: "held", header: t("ovr.held"), align: "right", cell: (r) => r.in_custody, sort: (r) => r.in_custody },
    { id: "cap", header: t("ovr.capacity"), align: "right", cell: (r) => <>{num(r.capacity)}{r.over_capacity && <> <Chip tone="bad">{t("ovr.over")}</Chip></>}</> },
    { id: "free", header: t("ovr.free"), align: "right", cell: (r) => num(r.available) },
    { id: "od", header: t("ovr.overdue"), align: "right", cell: (r) => (r.overdue_reviews ? <Chip tone="bad">{r.overdue_reviews}</Chip> : 0), sort: (r) => r.overdue_reviews },
    { id: "un", header: t("ovr.unplaced"), align: "right", cell: (r) => (r.held_without_verified_facility ? <Chip tone="draft">{r.held_without_verified_facility}</Chip> : 0) },
    { id: "adm", header: t("ovr.admitted"), align: "right", cell: (r) => r.admitted },
    { id: "rec", header: t("ovr.received"), align: "right", cell: (r) => r.received },
    { id: "rel", header: t("ovr.released"), align: "right", cell: (r) => r.released },
    { id: "tr", header: t("ovr.transferred"), align: "right", cell: (r) => r.transferred_out },
    { id: "in", header: t("ovr.incoming"), align: "right", cell: (r) => r.incoming },
  ];

  return (
    <>
      <PageHeader title={t("ovr.title")} subtitle={t("ovr.subtitle")} />
      <div className="row">
        <UnitPicker label={t("det.station")} value={unit} onChange={setUnit} allowAll />
        <label className="field"><span>{t("ovr.days")}</span>
          <select value={days} onChange={(e) => setDays(Number(e.target.value))}>{[7, 30, 90, 365].map((n) => <option key={n} value={n}>{n}</option>)}</select></label>
      </div>
      {d && (<>
        <p>{t("ovr.totals", { stations: d.totals.stations, operational: d.totals.operational, unverified: d.totals.unverified, out: d.totals.out_of_use, none: d.totals.no_facility })}</p>
        <p>{t("ovr.held")}: <strong>{d.totals.in_custody}</strong> · {t("ovr.free")}: <strong>{d.totals.stations_with_known_capacity ? d.totals.available : t("ovr.notSet")}</strong> · {t("ovr.overdue")}: <strong>{d.totals.overdue_reviews}</strong> ({d.review_hours} h) · {t("ovr.unplaced")}: <strong>{d.totals.held_without_verified_facility}</strong> · {t("ovr.incoming")}: <strong>{d.totals.incoming}</strong></p>
        {d.stations_without_district > 0 && <p className="muted">{t("ovr.noDistrict", { n: d.stations_without_district })}</p>}
        {d.regions.length > 1 && <DataTable id="ovr-regions" caption={t("ovr.byRegion")} columns={groupCols(t("ovr.region"))} rows={d.regions} rowKey={(g) => g.unit?.id ?? "none"} loading={false} empty={{ title: t("det.empty") }} />}
        {d.districts.length > 0 && <DataTable id="ovr-districts" caption={t("ovr.byDistrict")} columns={groupCols(t("ovr.district"))} rows={d.districts} rowKey={(g) => g.unit?.id ?? "none"} loading={false} empty={{ title: t("det.empty") }} />}
      </>)}
      <DataTable id="ovr-stations" caption={t("ovr.stations")} columns={cols} rows={d?.stations ?? []} rowKey={(r) => r.unit.id} loading={data.loading} empty={{ title: t("det.empty") }} />
      {hier.data && (
        <section className="card" aria-label={t("ovr.hierarchy")}>
          <h3>{t("ovr.hierarchy")}</h3>
          <p>{t("ovr.hierarchySummary", { stations: hier.data.stations, errors: hier.data.errors, warnings: hier.data.warnings, info: hier.data.info })}</p>
          <ul>{hier.data.findings.filter((f) => f.severity !== "info").slice(0, 50).map((f, i) => <li key={i}><Chip tone={f.severity === "error" ? "bad" : "draft"}>{f.severity}</Chip> {f.unit} · {f.message}</li>)}</ul>
        </section>)}
    </>
  );
}
