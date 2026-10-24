import { useState } from "react";
import { useFetch } from "../api/useFetch";
import { Chip, ErrorNotice, Field, Notice } from "../components/ui";
import { useI18n } from "../i18n";

interface Named { code: string; name_en: string; name_so: string }
interface UnitB { id: string; code: string; name_en: string; name_so: string }
interface LineRow { id: string; category: Named; unit: UnitB; in_store: number; held_by_soldiers: number }
interface Disposition {
  line: { id: string; category: Named; unit: UnitB; uom: string };
  store: { balance_start: number; issued: number; issued_to_soldiers: number; issued_other: number; returned: number; returned_from_soldiers: number; returned_other: number; balance_end: number; current: number };
  soldiers: { held_start: number; issued: number; returned: number; expended: number; lost: number; held_end: number };
  accountable_end: number;
  per_soldier: { personnel: { id: string; full_name: string; service_number: string | null; rank: Named }; issued: number; returned: number; expended: number; lost: number; held: number }[];
  checks: { issues_match_store: boolean; returns_match_store: boolean; unlinked_rows: number; negative_holdings: number; arithmetic_ok: boolean };
  consistent: boolean;
}
const today = () => new Date().toISOString().slice(0, 10);

/** Reconciles ammunition issued against returned, expended, lost and still held, keeping physical store stock apart from rounds on soldiers. */
export function AmmoAccountability() {
  const { t, name } = useI18n();
  const [lineId, setLineId] = useState("");
  const [from, setFrom] = useState(today().slice(0, 8) + "01");
  const [to, setTo] = useState(today());
  const lines = useFetch<{ results: LineRow[] }>("/weapons/disposition/");
  const d = useFetch<Disposition>(lineId ? "/weapons/disposition/" : null, { stock_line: lineId, from, to });
  const Row = ({ label, value, sub }: { label: string; value: number; sub?: boolean }) => (
    <div className="stat"><span>{sub ? "\u00a0\u00a0" : ""}{label}</span><b>{value}</b></div>
  );
  return (
    <>
      <h1>{t("acc.title")}</h1>
      <p className="muted">{t("acc.intro")}</p>
      <ErrorNotice error={lines.error ?? d.error} />
      <section className="card">
        <Field label={t("acc.pick")}>
          <select value={lineId} onChange={(e) => setLineId(e.target.value)}>
            <option value="">—</option>
            {(lines.data?.results ?? []).map((l) => <option key={l.id} value={l.id}>{name(l.category)} · {name(l.unit)} ({l.in_store} / {l.held_by_soldiers})</option>)}
          </select>
        </Field>
        <div className="grid">
          <Field label={t("att.from")}><input type="date" value={from} onChange={(e) => setFrom(e.target.value)} /></Field>
          <Field label={t("att.to")}><input type="date" value={to} min={from} onChange={(e) => setTo(e.target.value)} /></Field>
        </div>
      </section>
      {d.data && (
        <>
          {d.data.consistent
            ? <Notice>{t("acc.consistent")}</Notice>
            : (
              <Notice kind="error">
                {t("acc.inconsistent")}
                {!d.data.checks.issues_match_store && <><br />{t("acc.badIssues")}</>}
                {!d.data.checks.returns_match_store && <><br />{t("acc.badReturns")}</>}
                {d.data.checks.unlinked_rows > 0 && <><br />{t("acc.unlinked", { n: d.data.checks.unlinked_rows })}</>}
                {d.data.checks.negative_holdings > 0 && <><br />{t("acc.negative", { n: d.data.checks.negative_holdings })}</>}
                {!d.data.checks.arithmetic_ok && <><br />{t("acc.arithmetic")}</>}
              </Notice>
            )}
          <section className="card">
            <h3>{t("acc.store")}</h3>
            <Row label={t("acc.balanceStart")} value={d.data.store.balance_start} />
            <Row label={t("acc.issuedAll")} value={d.data.store.issued} />
            <Row sub label={t("acc.issuedToSoldiers")} value={d.data.store.issued_to_soldiers} />
            <Row sub label={t("acc.issuedOther")} value={d.data.store.issued_other} />
            <Row label={t("acc.returnedAll")} value={d.data.store.returned} />
            <Row sub label={t("acc.returnedFromSoldiers")} value={d.data.store.returned_from_soldiers} />
            <Row sub label={t("acc.returnedOther")} value={d.data.store.returned_other} />
            <Row label={t("acc.balanceEnd")} value={d.data.store.balance_end} />
          </section>
          <section className="card">
            <h3>{t("acc.soldiers")}</h3>
            <Row label={t("acc.heldStart")} value={d.data.soldiers.held_start} />
            <Row label={t("hold.issued")} value={d.data.soldiers.issued} />
            <Row label={t("hold.returned")} value={d.data.soldiers.returned} />
            <Row label={t("hold.expended")} value={d.data.soldiers.expended} />
            <Row label={t("hold.lost")} value={d.data.soldiers.lost} />
            <Row label={t("acc.heldEnd")} value={d.data.soldiers.held_end} />
            <Row label={t("acc.accountable")} value={d.data.accountable_end} />
          </section>
          <h3>{t("acc.perSoldier")}</h3>
          {d.data.per_soldier.length === 0 && <p className="muted">{t("acc.none")}</p>}
          <ul className="list">
            {d.data.per_soldier.map((s) => (
              <li key={s.personnel.id} className="item">
                <b>{s.personnel.rank.code} {s.personnel.full_name}</b> ({s.personnel.service_number ?? "—"})
                <div className="row">
                  <Chip tone="draft">{t("hold.issued")} {s.issued}</Chip>
                  <Chip tone="draft">{t("hold.returned")} {s.returned}</Chip>
                  <Chip tone="draft">{t("hold.expended")} {s.expended}</Chip>
                  <Chip tone={s.lost ? "bad" : "draft"}>{t("hold.lost")} {s.lost}</Chip>
                  <Chip tone={s.held < 0 ? "bad" : "approved"}>{t("hold.roundsLeft")} {s.held}</Chip>
                </div>
              </li>
            ))}
          </ul>
        </>
      )}
    </>
  );
}
