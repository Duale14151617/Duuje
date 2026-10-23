import { useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, fetchAll } from "../api/client";
import type { Page, ReportType, SubmissionDetail, SubmissionRow, Unit } from "../api/types";
import { useFetch } from "../api/useFetch";
import { useAuth } from "../auth/AuthContext";
import { ExportPdfButton } from "../components/ExportPdfButton";
import { Chip, ErrorNotice, Field, formatDate, Loading, Notice, Pager } from "../components/ui";
import { useI18n, type Key } from "../i18n";

const statusTone = (s: string) => (s === "approved" ? "approved" : s === "rejected" ? "bad" : "draft");

export function ReportList() {
  const { t, name } = useI18n();
  const { me, can } = useAuth();
  const [exportError, setExportError] = useState<unknown>(null);
  const [view, setView] = useState<"mine" | "review" | "all">(can("reports.submit") ? "mine" : "all");
  const [page, setPage] = useState(1);
  const query = { page, mine: view === "mine" ? "1" : undefined, awaiting_review: view === "review" ? "1" : undefined };
  const list = useFetch<Page<SubmissionRow>>("/reports/submissions/", query);
  const tabs: ["mine" | "review" | "all", Key, boolean][] = [
    ["mine", "rep.mine", can("reports.submit")], ["review", "rep.toReview", can("reports.review")], ["all", "rep.all", true]];

  const canExport = can("reports.export") && !!me?.features.report_export;
  const viewLabel: Record<typeof view, Key> = { mine: "rep.mine", review: "rep.toReview", all: "rep.all" };

  async function buildPdf() {
    const items = await fetchAll<SubmissionRow>("/reports/submissions/", { mine: query.mine, awaiting_review: query.awaiting_review });
    return {
      title: t("rep.title"), landscape: true,
      subtitle: `${t(viewLabel[view])}  |  ${t("pdf.rowsCount", { n: items.length })}`,
      sections: [{
        columns: [
          { header: t("rep.titleField"), width: 3 }, { header: t("rep.type"), width: 2 }, { header: t("rep.unit"), width: 2.5 },
          { header: `${t("rep.periodStart")} – ${t("rep.periodEnd")}`, width: 2.2 }, { header: t("rep.submitter"), width: 1.5 }, { header: t("pers.status"), width: 1.3 }],
        rows: items.map((s) => [s.title, name(s.report_type), name(s.org_unit), `${s.period_start} – ${s.period_end}`, s.submitter_username, t(`rstatus.${s.status}` as Key)]),
      }],
    };
  }

  return (
    <>
      <div className="row" style={{ justifyContent: "space-between", marginBottom: "1rem" }}>
        <h1 style={{ margin: 0 }}>{t("rep.title")}</h1>
        <div className="row">
          {canExport && <ExportPdfButton filename="reports.pdf" build={buildPdf} onError={setExportError} />}
          {can("reports.submit") && <Link className="btn" to="/reports/new">{t("rep.new")}</Link>}
        </div>
      </div>
      <div className="row" style={{ marginBottom: "1rem" }}>
        {tabs.filter(([, , show]) => show).map(([v, label]) => (
          <button key={v} className={view === v ? "" : "secondary"} onClick={() => { setView(v); setPage(1); }}>{t(label)}</button>
        ))}
      </div>
      <ErrorNotice error={list.error ?? exportError} />
      {list.loading && !list.data ? <Loading /> : null}
      {list.data && list.data.results.length === 0 && <p>{t("rep.noItems")}</p>}
      <ul className="list">
        {list.data?.results.map((s) => (
          <li key={s.id} className="item">
            <div className="row" style={{ justifyContent: "space-between" }}>
              <Link to={`/reports/${s.id}`}><h2>{s.title}</h2></Link>
              <Chip tone={statusTone(s.status)}>{t(`rstatus.${s.status}` as Key)}</Chip>
            </div>
            <span className="muted">{name(s.report_type)} · {name(s.org_unit)} · {s.period_start} – {s.period_end} · {s.submitter_username}</span>
          </li>
        ))}
      </ul>
      {list.data && <Pager page={page} count={list.data.count} pageSize={25} onPage={setPage} />}
    </>
  );
}

export function ReportForm() {
  const { id } = useParams();
  const { t, name } = useI18n();
  const navigate = useNavigate();
  const types = useFetch<ReportType[]>("/reports/types/");
  const unitsRes = useFetch<Page<Unit>>("/organization/units/", { page_size: 100 });
  const existing = useFetch<SubmissionDetail>(id ? `/reports/submissions/${id}/` : null);
  const [typeId, setTypeId] = useState("");
  const [unitId, setUnitId] = useState("");
  const [title, setTitle] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [body, setBody] = useState("");
  const [figures, setFigures] = useState<Record<string, string>>({});
  const [error, setError] = useState<unknown>(null);
  const [loadedId, setLoadedId] = useState("");

  const s = existing.data;
  if (s && loadedId !== s.id) {  // fill the form once when editing
    setLoadedId(s.id); setTitle(s.title); setStart(s.period_start); setEnd(s.period_end); setBody(s.body);
    setFigures(Object.fromEntries(Object.entries(s.figures).map(([k, v]) => [k, String(v)])));
    setTypeId(s.report_type.id); setUnitId(s.org_unit.id);
  }
  const type = s?.report_type ?? types.data?.find((x) => x.id === typeId);
  const computed = type?.code === "unit_situation_report";  // figures are calculated from saved records, never typed in
  const units = (unitsRes.data?.results ?? []).filter((u) => (u.level === "branch_command" || u.level === "unit") && u.active);

  async function save(e: FormEvent) {
    e.preventDefault();
    setError(null);
    const nums: Record<string, number> = {};
    for (const [k, v] of Object.entries(figures)) if (v !== "") nums[k] = Number(v);
    const content = { title, period_start: start, period_end: end, body, ...(computed ? {} : { figures: nums }) };
    try {
      const saved = id
        ? await api<SubmissionDetail>(`/reports/submissions/${id}/`, { method: "PATCH", body: { ...content, version: s?.version } })
        : await api<SubmissionDetail>("/reports/submissions/", { method: "POST", body: { ...content, report_type: typeId, org_unit: unitId } });
      navigate(`/reports/${saved.id}`);
    } catch (err) { setError(err); }
  }

  return (
    <>
      <p><Link to={id ? `/reports/${id}` : "/reports"}>{t("common.back")}</Link></p>
      <h1>{id ? t("rep.edit") : t("rep.new")}</h1>
      <ErrorNotice error={error ?? existing.error} />
      <form className="card" onSubmit={(e) => void save(e)}>
        {!id && (
          <>
            <Field label={t("rep.type")}>
              <select value={typeId} onChange={(e) => setTypeId(e.target.value)} required>
                <option value="" />
                {types.data?.filter((x) => x.active !== false && x.code !== "unit_situation_report").map((x) => <option key={x.id} value={x.id}>{name(x)}</option>)}
              </select>
            </Field>
            <Field label={t("rep.unit")}>
              <select value={unitId} onChange={(e) => setUnitId(e.target.value)} required>
                <option value="" />
                {units.map((u) => <option key={u.id} value={u.id}>{name(u)}</option>)}
              </select>
            </Field>
          </>
        )}
        <Field label={t("rep.titleField")}><input value={title} maxLength={200} onChange={(e) => setTitle(e.target.value)} required /></Field>
        <div className="grid">
          <Field label={t("rep.periodStart")}><input type="date" value={start} onChange={(e) => setStart(e.target.value)} required /></Field>
          <Field label={t("rep.periodEnd")}><input type="date" value={end} onChange={(e) => setEnd(e.target.value)} required /></Field>
        </div>
        {type && !computed && type.figure_keys.length > 0 && (
          <fieldset className="card" style={{ margin: "0 0 .85rem" }}>
            <legend>{t("rep.figures")}</legend>
            {type.figure_keys.map((k) => (
              <Field key={k} label={t(`fig.${k}` as Key)}>
                <input type="number" inputMode="numeric" min={0} step={1} value={figures[k] ?? ""}
                       onChange={(e) => setFigures({ ...figures, [k]: e.target.value })} />
              </Field>
            ))}
          </fieldset>
        )}
        <Field label={t("rep.body")}><textarea value={body} maxLength={5000} rows={5} onChange={(e) => setBody(e.target.value)} style={{ width: "100%", font: "inherit" }} /></Field>
        <button type="submit">{t("rep.saveDraft")}</button>
      </form>
    </>
  );
}

export function ReportDetail() {
  const { id = "" } = useParams();
  const { t, lang, name } = useI18n();
  const sub = useFetch<SubmissionDetail>(`/reports/submissions/${id}/`);
  const [comment, setComment] = useState("");
  const [error, setError] = useState<unknown>(null);
  const s = sub.data;

  async function act(path: string) {
    if (!s) return;
    setError(null);
    try {
      await api(`/reports/submissions/${s.id}/${path}/`, { method: "POST", body: { version: s.version, comment } });
      setComment("");
      sub.reload();
    } catch (err) { setError(err); }
  }
  const c = s?.capabilities;
  const needsComment = !!c && (c.decide || c.amend);

  return (
    <>
      <p><Link to="/reports">{t("common.back")}</Link></p>
      <ErrorNotice error={error ?? sub.error} />
      {sub.loading && !s ? <Loading /> : null}
      {s && c && (
        <>
          <section className="card">
            <div className="row" style={{ justifyContent: "space-between" }}>
              <h1 style={{ margin: 0 }}>{s.title}</h1>
              <Chip tone={statusTone(s.status)}>{t(`rstatus.${s.status}` as Key)}</Chip>
            </div>
            <p className="muted">{name(s.report_type)} · {name(s.org_unit)} · {s.period_start} – {s.period_end}</p>
            <p className="muted">{t("rep.submitter")}: {s.submitter_username}
              {s.approved_revision_no ? ` · ${t("rep.approvedRev", { n: s.approved_revision_no })}` : ""}</p>
            {Object.entries(s.figures).map(([k, v]) => (
              <div className="stat" key={k}><span>{t(`fig.${k}` as Key)}</span><b>{v}</b></div>
            ))}
            {s.body && <p style={{ marginTop: ".75rem", whiteSpace: "pre-wrap" }}>{s.body}</p>}
          </section>
          {(c.edit || c.submit || c.start_review || c.decide || c.amend) && (
            <section className="card">
              {needsComment && (
                <>
                  <Field label={t("rep.comment")}>
                    <input value={comment} maxLength={1000} onChange={(e) => setComment(e.target.value)} />
                  </Field>
                  <Notice>{t("rep.commentHint")}</Notice>
                </>
              )}
              <div className="row">
                {c.edit && <Link className="btn secondary" to={`/reports/${s.id}/edit`}>{t("rep.edit")}</Link>}
                {c.submit && <button onClick={() => void act("submit")}>{t("rep.submit")}</button>}
                {c.start_review && <button onClick={() => void act("start-review")}>{t("rep.startReview")}</button>}
                {c.decide && <button onClick={() => void act("approve")}>{t("rep.approve")}</button>}
                {c.decide && <button className="secondary" onClick={() => void act("return")}>{t("rep.returnIt")}</button>}
                {c.decide && <button className="danger" onClick={() => void act("reject")}>{t("rep.reject")}</button>}
                {c.amend && <button className="secondary" onClick={() => void act("amend")}>{t("rep.amend")}</button>}
              </div>
            </section>
          )}
          <h2>{t("rep.history")}</h2>
          <ul className="list">
            {[...s.actions].reverse().map((a) => (
              <li key={a.id} className="item">
                <b>{t(`raction.${a.action}` as Key)}</b>
                {a.revision_no > 0 && <> · {t("rep.revision", { n: a.revision_no })}</>}
                <div className="muted">{a.actor_username} · {formatDate(a.created_at, lang)}</div>
                {a.comment && <div>{a.comment}</div>}
              </li>
            ))}
          </ul>
        </>
      )}
    </>
  );
}
