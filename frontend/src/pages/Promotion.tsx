import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { api, ApiError } from "../api/client";
import { useFetch } from "../api/useFetch";
import { useAuth } from "../auth/AuthContext";
import { Chip, ErrorNotice, Field, Notice, PageHeader, TabPanel, Tabs } from "../components/ui";
import { UnitPicker } from "../components/UnitPicker";
import { useI18n, type Key } from "../i18n";
import { formatDay } from "../lib/format";

interface Named { id: string; code: string; name_en: string; name_so: string }
type State = "eligible" | "not_yet" | "blocked" | "no_rule" | "no_next";
const STATES = ["eligible", "not_yet", "blocked", "no_next", "no_rule"] as const;
interface Row {
  personnel: { id: string; full_name: string; service_number: string | null; status: string };
  unit: Omit<Named, "id">; rank: Named; next_rank: Named | null; rank_since: string; since_source: "history" | "record";
  months: number; required: number | null; months_left: number | null; state: State;
}
interface RankRule { id: string; code: string; name_en: string; name_so: string; rule: { min_months: number; active: boolean; next_rank: Named | null } | null }
const TONE: Record<State, string> = { eligible: "ok", not_yet: "neutral", blocked: "bad", no_rule: "warn", no_next: "warn" };

/** Who has served long enough in their rank. Advisory: it never changes a rank. */
export function Promotion() {
  const { t } = useI18n();
  const [tab, setTab] = useState<"list" | "rules">("list");
  return (
    <>
      <PageHeader title={t("pm.title")} subtitle={t("pm.subtitle")} />
      <Tabs label={t("pm.title")} value={tab} onChange={setTab} controls idPrefix="pm"
        tabs={[{ id: "list", label: t("pm.tab.list") }, { id: "rules", label: t("pm.tab.rules") }]} />
      <TabPanel id="list" active={tab === "list"} idPrefix="pm"><List /></TabPanel>
      <TabPanel id="rules" active={tab === "rules"} idPrefix="pm"><Rules /></TabPanel>
    </>
  );
}

function List() {
  const { t, lang, name } = useI18n();
  const { can } = useAuth();
  const canPropose = can("changes.propose"), appliesAtOnce = can("changes.approve");
  const [unit, setUnit] = useState("");
  const [state, setState] = useState("");
  const [picked, setPicked] = useState<Record<string, boolean>>({});
  const [error, setError] = useState<unknown>(null);
  const [failed, setFailed] = useState<{ index: number; code: string }[]>([]);
  const [made, setMade] = useState<number | null>(null);
  const data = useFetch<{ counts: Record<State, number>; results: Row[] }>(unit ? "/promotion/eligibility/" : null, { org_unit: unit, state: state || undefined });
  const day = (s: string) => formatDay(s, lang);
  const chosen = (data.data?.results ?? []).filter((r) => r.state === "eligible" && picked[r.personnel.id]);

  async function propose(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = Object.fromEntries(new FormData(e.currentTarget).entries());
    setError(null); setFailed([]); setMade(null);
    try {
      const r = await api<{ count: number }>("/promotion/propose/", {
        method: "POST",
        body: { items: chosen.map((c) => ({ personnel: c.personnel.id })), ...f, effective_date: f.effective_date || undefined } });
      setMade(r.count); setPicked({}); data.reload();
    } catch (err) {
      setError(err);
      if (err instanceof ApiError) setFailed(((err.body as unknown as { rows?: { index: number; code: string }[] })?.rows) ?? []);
    }
  }

  return (
    <section className="card">
      <UnitPicker label={t("pm.unit")} value={unit} onChange={(id) => { setUnit(id); setPicked({}); }} />
      <ErrorNotice error={data.error} />
      {!unit && <p className="muted">{t("pm.pick")}</p>}
      {unit && data.data && (
        <>
          <div className="row">
            {STATES.map((s) => <Chip key={s} tone={TONE[s]}>{t(`pm.state.${s}` as Key)}: {data.data!.counts[s] ?? 0}</Chip>)}
          </div>
          <Field label={t("pm.state")}>
            <select value={state} onChange={(e) => setState(e.target.value)}>
              <option value="">{t("common.all")}</option>
              {STATES.map((s) => <option key={s} value={s}>{t(`pm.state.${s}` as Key)}</option>)}
            </select>
          </Field>
          {data.data.results.length === 0 && <p className="muted">{t("pm.noRows")}</p>}
          <ul className="list">
            {data.data.results.map((r) => (
              <li key={r.personnel.id} className="item">
                <div className="row">
                  {canPropose && r.state === "eligible" && (
                    <input type="checkbox" aria-label={t("pm.propose.select")} checked={!!picked[r.personnel.id]}
                           onChange={(e) => setPicked((m) => ({ ...m, [r.personnel.id]: e.target.checked }))} />)}
                  <b>{r.personnel.full_name}</b>
                  <span>{name(r.rank)}{r.next_rank ? ` → ${name(r.next_rank)}` : ""}</span>
                  <Chip tone={TONE[r.state]}>{t(`pm.state.${r.state}` as Key)}</Chip>
                </div>
                <p className="muted">
                  {t("pm.since")} {day(r.rank_since)} · {t("pm.months", { n: r.months })}
                  {r.required !== null ? ` ${t("pm.of", { n: r.required })}` : ""}
                  {r.state === "not_yet" && r.months_left ? ` · ${t("pm.left", { n: r.months_left })}` : ""}
                </p>
                {r.since_source === "record" && <p className="muted">{t("pm.sinceRecord")}</p>}
              </li>))}
          </ul>
        </>)}

      {canPropose && unit && chosen.length > 0 && (
        <form onSubmit={(e) => void propose(e)} className="mt-1">
          <h3>{t("pm.propose.title")}</h3>
          <p className="muted">{t("pm.propose.hint")}</p>
          {appliesAtOnce && <Notice kind="warn">{t("pm.propose.hintSuper")}</Notice>}
          <Field label={t("pm.propose.orderRef")}><input name="order_ref" required maxLength={150} /></Field>
          <Field label={t("pm.propose.officer")}><input name="issuing_officer" required maxLength={150} /></Field>
          <div className="row">
            <Field label={t("pm.propose.orderDate")}><input type="date" name="order_date" required /></Field>
            <Field label={t("pm.propose.effective")}><input type="date" name="effective_date" /></Field>
          </div>
          <button type="submit">{t("pm.propose.submit", { n: chosen.length })}</button>
        </form>)}
      <ErrorNotice error={error} />
      {failed.length > 0 && (
        <ul className="list">
          {failed.map((f) => (
            <li key={f.index} className="item">{chosen[f.index]?.personnel.full_name ?? `#${f.index + 1}`}: {t(`err.${f.code}` as Key)}</li>))}
        </ul>)}
      {made !== null && <Notice>{t("pm.propose.sent", { n: made })} <Link to="/change-requests">{t("pm.propose.open")}</Link></Notice>}
    </section>
  );
}

function Rules() {
  const { t, name } = useI18n();
  const { can } = useAuth();
  const canSet = can("promotion.configure");
  const ranks = useFetch<{ results: RankRule[] }>("/promotion/rules/");
  const [error, setError] = useState<unknown>(null);
  const [saved, setSaved] = useState(false);
  const [draft, setDraft] = useState<Record<string, string>>({});

  async function save(r: RankRule) {
    setError(null); setSaved(false);
    const months = Number(draft[r.id] ?? r.rule?.min_months);
    try {
      await api("/promotion/rules/set/", { method: "POST", body: { rank: r.id, min_months: months, next_rank: r.rule?.next_rank?.id } });
      setDraft((d) => Object.fromEntries(Object.entries(d).filter(([k]) => k !== r.id))); setSaved(true); ranks.reload();
    } catch (err) { setError(err); }
  }
  async function remove(r: RankRule) {
    setError(null); setSaved(false);
    try { await api("/promotion/rules/set/", { method: "POST", body: { rank: r.id, remove: true } }); ranks.reload(); }
    catch (err) { setError(err); }
  }

  return (
    <section className="card">
      <p className="muted">{t("pm.rules.hint")}</p>
      <ErrorNotice error={error ?? ranks.error} />
      {saved && <Notice>{t("pm.rules.saved")}</Notice>}
      <ul className="list">
        {(ranks.data?.results ?? []).map((r) => (
          <li key={r.id} className="item">
            <div className="row">
              <b>{name(r)}</b>
              {!canSet && <span>{r.rule ? t("pm.months", { n: r.rule.min_months }) : t("pm.rules.none")}</span>}
              {canSet && (
                <>
                  <Field label={t("pm.rules.months")}>
                    <input type="number" min={1} max={600} value={draft[r.id] ?? String(r.rule?.min_months ?? "")}
                           onChange={(e) => setDraft((d) => ({ ...d, [r.id]: e.target.value }))} />
                  </Field>
                  <button type="button" disabled={!(draft[r.id] ?? r.rule)} onClick={() => void save(r)}>{t("pm.rules.save")}</button>
                  {r.rule && <button type="button" className="secondary" onClick={() => void remove(r)}>{t("pm.rules.remove")}</button>}
                </>)}
            </div>
          </li>))}
      </ul>
    </section>
  );
}
