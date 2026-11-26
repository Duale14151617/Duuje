import { useState } from "react";
import { useFetch } from "../api/useFetch";
import { DataTable, type Column } from "../components/DataTable";
import { ExportPdfButton, type PdfContent } from "../components/ExportPdfButton";
import { Field, PageHeader } from "../components/ui";
import { UnitPicker } from "../components/UnitPicker";
import { useI18n, type Key } from "../i18n";
import { downloadText, toCsv } from "../lib/csv";

interface UnitB { id: string; code: string; name_en: string; name_so: string }
interface Counts {
  on_file: number; serving: number; active: number; on_leave: number; suspended: number; jailed: number; died: number; retired: number; discharged: number;
  joined: number; left: number; promoted: number;
}
interface UnitRow extends Counts { unit: UnitB; region: UnitB | null }
interface RegionRow extends Counts { unit: UnitB | null }
interface RankRow { name_en: string; name_so: string; on_file: number; serving: number }
interface Data { from: string; to: string; totals: Counts; regions: RegionRow[]; units: UnitRow[]; ranks: RankRow[] }

const KEYS = ["on_file", "serving", "active", "on_leave", "suspended", "jailed", "retired", "discharged", "died", "joined", "left", "promoted"] as const;

/** Personnel strength and movement for a period, by region, unit and rank. Counts only; exported as CSV for spreadsheets and PDF for commanders. */
export function PersonnelReport() {
  const { t, name, lang } = useI18n();
  const [unit, setUnit] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const data = useFetch<Data>("/personnel-report/", { unit: unit || undefined, from: from || undefined, to: to || undefined });
  const d = data.data;
  const label = (k: (typeof KEYS)[number]) => t((k === "on_file" ? "prep.onFile" : `prep.${k}`) as Key);
  const rankName = (r: RankRow) => (lang === "so" && r.name_so ? r.name_so : r.name_en);

  const countCols = <R extends Counts>(): Column<R>[] => KEYS.map((k) => ({ id: k, header: label(k), align: "right" as const, cell: (r: R) => r[k], sort: (r: R) => r[k] }));
  const regionCols: Column<RegionRow>[] = [{ id: "u", header: t("prep.region"), cell: (r) => (r.unit ? name(r.unit) : "—"), sort: (r) => r.unit?.name_en ?? "" }, ...countCols<RegionRow>()];
  const unitCols: Column<UnitRow>[] = [
    { id: "u", header: t("prep.unit"), cell: (r) => name(r.unit), sort: (r) => r.unit.name_en },
    { id: "reg", header: t("prep.region"), cell: (r) => (r.region ? name(r.region) : "—") }, ...countCols<UnitRow>()];
  const rankCols: Column<RankRow>[] = [
    { id: "r", header: t("prep.rank"), cell: rankName, sort: rankName },
    { id: "f", header: t("prep.onFile"), align: "right", cell: (r) => r.on_file, sort: (r) => r.on_file },
    { id: "s", header: t("prep.serving"), align: "right", cell: (r) => r.serving, sort: (r) => r.serving }];

  const head = () => [t("prep.region"), t("prep.unit"), ...KEYS.map(label)];
  const body = () => (d?.units ?? []).map((r) => [r.region ? name(r.region) : "", name(r.unit), ...KEYS.map((k) => String(r[k]))]);
  const period = () => (d ? `${d.from} → ${d.to}` : "");
  const pdf = (): PdfContent => ({
    title: t("prep.title"), subtitle: period(), landscape: true,
    sections: [
      { heading: t("prep.byRegion"), columns: [{ header: t("prep.region"), width: 3 }, ...KEYS.map((k) => ({ header: label(k), width: 1, align: "right" as const }))],
        rows: [...(d?.regions ?? []).map((r) => [r.unit ? name(r.unit) : "—", ...KEYS.map((k) => String(r[k]))]), ...(d ? [[t("prep.totals"), ...KEYS.map((k) => String(d.totals[k]))]] : [])] },
      { heading: t("prep.byUnit"), columns: head().map((h, i) => ({ header: h, width: i < 2 ? 3 : 1, align: i >= 2 ? "right" as const : "left" as const })), rows: body() },
      { heading: t("prep.byRank"), columns: [{ header: t("prep.rank"), width: 4 }, { header: t("prep.onFile"), width: 1, align: "right" }, { header: t("prep.serving"), width: 1, align: "right" }],
        rows: (d?.ranks ?? []).map((r) => [rankName(r), String(r.on_file), String(r.serving)]) },
      { heading: t("prep.definitions"), columns: [{ header: "", width: 1 }], rows: [[t("prep.defText")]] },
    ],
  });

  return (
    <>
      <PageHeader title={t("prep.title")} subtitle={t("prep.subtitle")} />
      <div className="row">
        <UnitPicker label={t("prep.unit")} value={unit} onChange={setUnit} allowAll />
        <Field label={t("ovr.from")}><input type="date" value={from} max={to || undefined} onChange={(e) => setFrom(e.target.value)} /></Field>
        <Field label={t("ovr.to")}><input type="date" value={to} min={from || undefined} onChange={(e) => setTo(e.target.value)} /></Field>
        <button type="button" className="secondary" disabled={!d} onClick={() => downloadText(`personnel-report-${new Date().toISOString().slice(0, 10)}.csv`, toCsv([head(), ...body()]))}>{t("prep.csv")}</button>
        <ExportPdfButton build={pdf} filename="personnel-report" disabled={!d} />
      </div>
      <p className="muted">{t("prep.defaultPeriod")}{d ? ` ${period()}` : ""}</p>
      {d && <p>{t("prep.totals")}: {KEYS.map((k) => `${label(k)} ${d.totals[k]}`).join(" · ")}</p>}
      {d && d.regions.length > 1 && <DataTable id="prep-regions" caption={t("prep.byRegion")} columns={regionCols} rows={d.regions} rowKey={(r) => r.unit?.id ?? "none"} loading={false} empty={{ title: t("common.empty") }} />}
      <DataTable id="prep-units" caption={t("prep.byUnit")} columns={unitCols} rows={d?.units ?? []} rowKey={(r) => r.unit.id} loading={data.loading} empty={{ title: t("common.empty") }} />
      <DataTable id="prep-ranks" caption={t("prep.byRank")} columns={rankCols} rows={d?.ranks ?? []} rowKey={(r) => r.name_en} loading={data.loading} empty={{ title: t("common.empty") }} />
      <details className="mt-1"><summary>{t("prep.definitions")}</summary><p>{t("prep.defText")}</p></details>
    </>
  );
}
