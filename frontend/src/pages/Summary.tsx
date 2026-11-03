import { useState } from "react";
import { downloadCsv } from "../api/client";
import type { ReportType, Summary as Data } from "../api/types";
import { useFetch } from "../api/useFetch";
import { useAuth } from "../auth/AuthContext";
import { ExportPdfButton } from "../components/ExportPdfButton";
import { ErrorNotice, Field, EmptyState, Loading, Notice, PageHeader } from "../components/ui";
import { DataTable, type Column } from "../components/DataTable";
import { useI18n, type Key } from "../i18n";

export function Summary() {
  const { t, name } = useI18n();
  const { me, can } = useAuth();
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [type, setType] = useState("");
  const [exportError, setExportError] = useState<unknown>(null);
  const types = useFetch<ReportType[]>("/reports/types/");
  const q = { from, to, report_type: type };
  const data = useFetch<Data>("/reports/summary/", q);
  const canExport = can("reports.export") && !!me?.features.report_export;
  const d = data.data;
  const columns = (x: Data): Column<Data["regions"][number]>[] => [
    { id: "region", header: t("sum.region"), width: 220, locked: true, sort: (r) => name(r.region), cell: (r) => name(r.region) },
    { id: "subs", header: t("sum.submissions"), width: 130, align: "right", sort: (r) => r.submissions, cell: (r) => r.submissions },
    ...x.figure_keys.map((k): Column<Data["regions"][number]> => ({ id: `f-${k}`, header: t(`fig.${k}` as Key), width: 140, align: "right", sort: (r) => r.totals[k] ?? 0, cell: (r) => r.totals[k] ?? 0 })),
  ];

  async function exportCsv() {
    setExportError(null);
    try { await downloadCsv("/reports/summary/export/", { from, to, report_type: type }, "summary.csv"); }
    catch (err) { setExportError(err); }
  }

  return (
    <>
      <PageHeader title={t("sum.title")} actions={
        canExport ? (
          <>
            <button className="secondary" onClick={() => void exportCsv()}>{t("sum.export")}</button>
            {d && d.consolidated.submissions > 0 && (
              <ExportPdfButton filename="summary.pdf" onError={setExportError} build={() => ({
                title: t("sum.title"), landscape: d.figure_keys.length > 4,
                subtitle: [from && `${t("sum.from")}: ${from}`, to && `${t("sum.to")}: ${to}`,
                  type && `${t("sum.type")}: ${types.data?.find((x) => x.id === type) ? name(types.data.find((x) => x.id === type)!) : type}`,
                  t("sum.note")].filter(Boolean).join("  |  "),
                sections: [{
                  columns: [{ header: t("sum.region"), width: 2.5 }, { header: t("sum.submissions"), width: 1.3, align: "right" as const },
                    ...d.figure_keys.map((k) => ({ header: t(`fig.${k}` as Key), width: 1.3, align: "right" as const }))],
                  rows: [...d.regions.map((r) => [name(r.region), String(r.submissions), ...d.figure_keys.map((k) => String(r.totals[k] ?? 0))]),
                    [t("sum.consolidated"), String(d.consolidated.submissions), ...d.figure_keys.map((k) => String(d.consolidated.totals[k] ?? 0))]],
                }],
              })} />
            )}
          </>
        ) : undefined} />
      <Notice>{t("sum.note")}</Notice>
      <div className="grid">
        <Field label={t("sum.from")}><input type="date" value={from} onChange={(e) => setFrom(e.target.value)} /></Field>
        <Field label={t("sum.to")}><input type="date" value={to} onChange={(e) => setTo(e.target.value)} /></Field>
        <Field label={t("sum.type")}>
          <select value={type} onChange={(e) => setType(e.target.value)}>
            <option value="">{t("common.all")}</option>
            {types.data?.map((x) => <option key={x.id} value={x.id}>{name(x)}</option>)}
          </select>
        </Field>
      </div>
      <ErrorNotice error={data.error ?? exportError} />
      {data.loading && !d ? <Loading /> : null}
      {d && d.consolidated.submissions === 0 && <section className="card"><EmptyState icon="file" title={t("sum.empty")} /></section>}
      {d && d.consolidated.submissions > 0 && (
        <>
          <section className="card">
            <h2>{t("sum.consolidated")}</h2>
            <dl className="kv">
              <div><dt>{t("sum.submissions")}</dt><dd>{d.consolidated.submissions}</dd></div>
              {d.figure_keys.map((k) => <div key={k}><dt>{t(`fig.${k}` as Key)}</dt><dd>{d.consolidated.totals[k] ?? 0}</dd></div>)}
            </dl>
          </section>
          <DataTable id="summary" caption={t("sum.title")} columns={columns(d)} rows={d.regions} rowKey={(r) => r.region.id}
                     empty={{ icon: "file", title: t("sum.empty") }} clientPageSize={100} />
        </>
      )}
    </>
  );
}
