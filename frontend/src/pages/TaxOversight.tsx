import { useState } from "react";
import { useFetch } from "../api/useFetch";
import { DataTable, type Column } from "../components/DataTable";
import { ExportPdfButton, type PdfContent } from "../components/ExportPdfButton";
import { Chip, Field, PageHeader } from "../components/ui";
import { UnitPicker } from "../components/UnitPicker";
import { useI18n } from "../i18n";
import { downloadText, toCsv } from "../lib/csv";
import { formatMoneyList } from "../lib/format";

interface UnitB { id: string; code: string; name_en: string; name_so: string }
interface Money { currency: string; total: string }
interface Counts { receipts: number; voided: number; held_count: number; handovers: number; handovers_confirmed: number; handover_differences: number; vehicles: number; overdue: number; collected: Money[]; held: Money[] }
interface StationRow extends Counts { unit: UnitB; region: UnitB | null }
interface RegionRow extends Counts { unit: UnitB | null }
interface Data { from: string; to: string; totals: Counts; regions: RegionRow[]; units: StationRow[] }

const money = (m: Money[]) => formatMoneyList(m, "; ");

/** Tax collections by station and region for a period, the way the custody report is built: on screen, as CSV and as PDF. Counts and amounts only. */
export function TaxOversight() {
  const { t, name } = useI18n();
  const [unit, setUnit] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const data = useFetch<Data>("/tax/oversight/", { unit: unit || undefined, from: from || undefined, to: to || undefined });
  const d = data.data;

  const numCols = <R extends Counts>(): Column<R>[] => [
    { id: "rc", header: t("txo.receipts"), align: "right", cell: (r) => r.receipts, sort: (r) => r.receipts },
    { id: "col", header: t("txo.collected"), align: "right", cell: (r) => money(r.collected) },
    { id: "vd", header: t("txo.voided"), align: "right", cell: (r) => r.voided, sort: (r) => r.voided },
    { id: "held", header: t("txo.held"), align: "right", cell: (r) => (r.held_count ? <Chip tone="draft">{money(r.held)}</Chip> : "0") },
    { id: "ho", header: t("txo.handovers"), align: "right", cell: (r) => r.handovers, sort: (r) => r.handovers },
    { id: "cf", header: t("txo.confirmed"), align: "right", cell: (r) => r.handovers_confirmed },
    { id: "df", header: t("txo.differences"), align: "right", cell: (r) => (r.handover_differences ? <Chip tone="bad">{r.handover_differences}</Chip> : 0), sort: (r) => r.handover_differences },
    { id: "ve", header: t("txo.vehicles"), align: "right", cell: (r) => r.vehicles, sort: (r) => r.vehicles },
    { id: "od", header: t("txo.overdue"), align: "right", cell: (r) => (r.overdue ? <Chip tone="bad">{r.overdue}</Chip> : 0), sort: (r) => r.overdue },
  ];
  const regionCols: Column<RegionRow>[] = [{ id: "u", header: t("txo.region"), cell: (r) => (r.unit ? name(r.unit) : "—"), sort: (r) => r.unit?.name_en ?? "" }, ...numCols<RegionRow>()];
  const stationCols: Column<StationRow>[] = [
    { id: "u", header: t("txo.station"), cell: (r) => name(r.unit), sort: (r) => r.unit.name_en },
    { id: "reg", header: t("txo.region"), cell: (r) => (r.region ? name(r.region) : "—") }, ...numCols<StationRow>()];

  const head = () => [t("txo.station"), t("txo.region"), t("txo.receipts"), t("txo.collected"), t("txo.voided"), t("txo.heldCount"), t("txo.held"), t("txo.handovers"), t("txo.confirmed"),
    t("txo.differences"), t("txo.vehicles"), t("txo.overdue")];
  const line = (label: string, region: string, r: Counts) => [label, region, String(r.receipts), money(r.collected), String(r.voided), String(r.held_count), money(r.held),
    String(r.handovers), String(r.handovers_confirmed), String(r.handover_differences), String(r.vehicles), String(r.overdue)];
  const body = () => (d?.units ?? []).map((r) => line(name(r.unit), r.region ? name(r.region) : "", r));
  const pdf = (): PdfContent => {
    const cols = head().map((h, i) => ({ header: h, width: i < 2 ? 3 : i === 3 || i === 6 ? 3 : 1, align: i >= 2 ? "right" as const : "left" as const }));
    return {
      title: t("txo.title"), subtitle: d ? `${d.from} → ${d.to}` : "", landscape: true,
      sections: [
        { heading: t("txo.byRegion"), columns: cols, rows: [...(d?.regions ?? []).map((r) => line(r.unit ? name(r.unit) : "—", "", r)), ...(d ? [line(t("txo.totals"), "", d.totals)] : [])] },
        { heading: t("txo.byStation"), columns: cols, rows: body() },
        { columns: [{ header: "", width: 1 }], rows: [[t("txo.defText")]] },
      ],
    };
  };

  return (
    <>
      <PageHeader title={t("txo.title")} subtitle={t("txo.subtitle")} />
      <div className="row">
        <UnitPicker label={t("txo.station")} value={unit} onChange={setUnit} allowAll />
        <Field label={t("ovr.from")}><input type="date" value={from} max={to || undefined} onChange={(e) => setFrom(e.target.value)} /></Field>
        <Field label={t("ovr.to")}><input type="date" value={to} min={from || undefined} onChange={(e) => setTo(e.target.value)} /></Field>
        <button type="button" className="secondary" disabled={!d} onClick={() => downloadText(`tax-report-${new Date().toISOString().slice(0, 10)}.csv`, toCsv([head(), ...body()]))}>{t("txo.csv")}</button>
        <ExportPdfButton build={pdf} filename="tax-report" disabled={!d} />
      </div>
      <p className="muted">{t("prep.defaultPeriod")}{d ? ` ${d.from} → ${d.to}` : ""}</p>
      {d && <p>{t("txo.receipts")}: <strong>{d.totals.receipts}</strong> · {t("txo.collected")}: <strong>{money(d.totals.collected)}</strong> · {t("txo.held")}: <strong>{money(d.totals.held)}</strong> · {t("txo.overdue")}: <strong>{d.totals.overdue}</strong></p>}
      {d && d.regions.length > 1 && <DataTable id="txo-regions" caption={t("txo.byRegion")} columns={regionCols} rows={d.regions} rowKey={(r) => r.unit?.id ?? "none"} loading={false} empty={{ title: t("common.empty") }} />}
      <DataTable id="txo-stations" caption={t("txo.byStation")} columns={stationCols} rows={d?.units ?? []} rowKey={(r) => r.unit.id} loading={data.loading} empty={{ title: t("common.empty") }} />
      <p className="muted">{t("txo.defText")}</p>
    </>
  );
}
