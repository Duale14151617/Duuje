import { useState } from "react";
import type {
  AnalyticsIndex, Dist, DistRow, LogisticsAnalytics, Named, Page, PersonnelAnalytics, ReportsAnalytics,
  TrainingAnalytics, Unit,
} from "../api/types";
import { useFetch } from "../api/useFetch";
import { ErrorNotice, Field, Loading, Notice, PageHeader, Tabs } from "../components/ui";
import { DataTable, type Column } from "../components/DataTable";
import { useI18n, type Key } from "../i18n";

type Section = "personnel" | "reports" | "logistics" | "training";

/** One distribution as a sortable table with a proportional bar. Withheld cells (null) are shown as a dash. */
function Distribution<R extends DistRow>({ title, dist, label }: { title: string; dist: Dist<R> | undefined; label: (r: R) => string }) {
  const { t } = useI18n();
  if (!dist) return null;
  const max = Math.max(1, ...dist.rows.map((r) => r.count ?? 0));
  const rows = dist.rows.map((r, i) => ({ r, i }));
  const columns: Column<{ r: R; i: number }>[] = [
    { id: "item", header: t("an.col.item"), width: 280, locked: true, sort: (x) => label(x.r), cell: (x) => label(x.r) },
    { id: "count", header: t("an.col.count"), width: 100, align: "right", sort: (x) => x.r.count, cell: (x) => (x.r.count === null ? "–" : x.r.count) },
    { id: "bar", header: "", width: 220, cell: (x) => (
      <span className="bar" aria-hidden="true" style={{ width: `${x.r.count === null ? 0 : Math.round((x.r.count / max) * 100)}%` }} />
    ) },
  ];
  return (
    <section className="card">
      <h2>{title}</h2>
      <DataTable id={`an-${title}`} caption={title} columns={columns} rows={rows} rowKey={(x) => String(x.i)}
                 empty={{ icon: "activity", title: t("an.empty") }} clientPageSize={100} />
      {dist.total !== null && <p className="muted">{t("an.total", { n: dist.total })}</p>}
      {dist.suppressed && <p className="muted">{t("an.withheld")}</p>}
    </section>
  );
}

export function Analytics() {
  const { t, name } = useI18n();
  const index = useFetch<AnalyticsIndex>("/analytics/");
  const [tab, setTab] = useState<Section | "">("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [unit, setUnit] = useState("");
  const regions = useFetch<Page<Unit>>("/organization/units/", { level: "region", active: "true", page_size: 100 });

  const sections = (index.data?.sections ?? []) as Section[];
  const current: Section | null = (tab && sections.includes(tab) ? tab : sections[0]) ?? null;
  const q = { from, to, unit };
  const data = useFetch<unknown>(current ? `/analytics/${current}/` : null, q);
  const d = data.data;
  const nm = (o: Named) => name(o);
  const statusLabel = (prefix: string) => (r: { status: string }) => t(`${prefix}.${r.status}` as Key);

  return (
    <>
      <PageHeader title={t("an.title")} />
      <Notice>{t("an.note")}</Notice>
      <ErrorNotice error={index.error} />
      {index.loading && !index.data ? <Loading /> : null}
      {index.data && sections.length === 0 && <p>{t("an.noSections")}</p>}
      {current && (
        <>
          <Tabs<Section> tabs={sections.map((s) => ({ id: s, label: t(`an.tab.${s}` as Key) }))} value={current} onChange={setTab} />
          <div className="grid">
            <Field label={t("an.from")}><input type="date" value={from} onChange={(e) => setFrom(e.target.value)} /></Field>
            <Field label={t("an.to")}><input type="date" value={to} onChange={(e) => setTo(e.target.value)} /></Field>
            <Field label={t("an.region")}>
              <select value={unit} onChange={(e) => setUnit(e.target.value)}>
                <option value="">{t("common.all")}</option>
                {regions.data?.results.map((r) => <option key={r.id} value={r.id}>{name(r)}</option>)}
              </select>
            </Field>
          </div>
          <ErrorNotice error={data.error} />
          {data.loading && !d ? <Loading /> : null}
          {current === "personnel" && d ? (() => {
            const p = d as PersonnelAnalytics;
            return (
              <>
                <Distribution title={t("an.byStatus")} dist={p.by_status} label={statusLabel("pstatus")} />
                <Distribution title={t("an.byRank")} dist={p.by_rank} label={nm} />
                <Distribution title={t("an.byBranch")} dist={p.by_branch} label={nm} />
                <Distribution title={t("an.byUnit")} dist={p.by_child_unit} label={(r) => name(r.unit)} />
                <Distribution title={t("an.changes")} dist={p.changes_by_month} label={(r) => `${r.month} · ${r.field}`} />
              </>
            );
          })() : null}
          {current === "reports" && d ? (() => {
            const r = d as ReportsAnalytics;
            return (
              <>
                <Distribution title={t("an.approvedByType")} dist={r.approved_by_type} label={nm} />
                <Distribution title={t("an.approvedByMonth")} dist={r.approved_by_month} label={(x) => x.month} />
                {r.pipeline && (
                  <>
                    <Distribution title={t("an.pipeline")} dist={r.pipeline.by_status} label={statusLabel("rstatus")} />
                    <p className="muted">{t("an.turnaround", { hours: r.pipeline.turnaround_hours.median ?? "–" })}</p>
                  </>
                )}
              </>
            );
          })() : null}
          {current === "logistics" && d ? (() => {
            const l = d as LogisticsAnalytics;
            return (
              <>
                <Distribution title={t("an.stockByCategory")} dist={l.stock_by_category} label={nm} />
                <p>{t("an.lowStock", { n: l.low_stock_lines ?? "–" })}</p>
                <Distribution title={t("an.assetsByStatus")} dist={l.assets_by_status} label={(r) => r.status} />
                <p className="muted">{t("an.excludesRestricted")}</p>
              </>
            );
          })() : null}
          {current === "training" && d ? (() => {
            const tr = d as TrainingAnalytics;
            return (
              <>
                <Distribution title={t("an.byCourse")} dist={tr.by_course}
                              label={(r) => `${name(r)}${r.completion_rate === null || r.completion_rate === undefined ? "" : ` · ${t("an.completionRate", { rate: Math.round(r.completion_rate * 100) })}`}`} />
                <Distribution title={t("an.completionsByMonth")} dist={tr.completions_by_month} label={(r) => r.month} />
              </>
            );
          })() : null}
        </>
      )}
    </>
  );
}
