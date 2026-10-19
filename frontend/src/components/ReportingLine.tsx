import { useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { Person, PersonBrief } from "../api/types";
import { useFetch } from "../api/useFetch";
import { useI18n } from "../i18n";
import { ErrorNotice, Field } from "./ui";

/**
 * Who this person reports to, who reports to them, and which login belongs to them.
 * Everyone who can read the person's unit sees the reporting line; only personnel managers can change it. The list of
 * possible supervisors comes from the server (same service, active, strictly senior, in the editor's reach), so the
 * screen never offers a choice the save would refuse.
 */
export function ReportingLine({ person, canManage, onChanged }: { person: Person; canManage: boolean; onChanged: () => void }) {
  const { t, name } = useI18n();
  const [editing, setEditing] = useState(false);
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  const [supervisor, setSupervisor] = useState("");
  const [account, setAccount] = useState("");
  const [error, setError] = useState<unknown>(null);
  useEffect(() => { const h = setTimeout(() => setDebounced(q.trim()), 250); return () => clearTimeout(h); }, [q]);

  const current = person.supervisor && !("restricted" in person.supervisor) ? person.supervisor : null;
  const hidden = !!person.supervisor && "restricted" in person.supervisor;
  const subs = person.subordinates ?? [];
  const candidates = useFetch<PersonBrief[]>(editing ? `/personnel/${person.id}/supervisor-candidates/` : null, { q: debounced });

  if (!canManage && person.supervisor === undefined && subs.length === 0) return null;  // e.g. a member viewing their own file

  const label = (p: PersonBrief) => `${p.rank.code} ${name(p.rank)} · ${p.full_name}`;
  const options = candidates.data ?? [];

  function start() {
    setSupervisor(person.supervisor?.id ?? ""); setAccount(person.account_username ?? ""); setQ(""); setError(null); setEditing(true);
  }

  async function save(e: FormEvent) {
    e.preventDefault();
    setError(null);
    const body: Record<string, unknown> = { version: person.version };
    if (supervisor !== (person.supervisor?.id ?? "")) body.supervisor = supervisor || null;  // only what changed, so an old
    if (account.trim() !== (person.account_username ?? "")) body.account_username = account.trim() || null;  // choice never blocks the other
    if (Object.keys(body).length === 1) { setEditing(false); return; }
    try {
      await api(`/personnel/${person.id}/`, { method: "PATCH", body });
      setEditing(false);
      onChanged();
    } catch (err) { setError(err); }
  }

  return (
    <section className="card">
      <h2>{t("rep.title")}</h2>
      <div className="stat">
        <span>{t("rep.supervisor")}</span>
        <b>
          {current ? <Link to={`/personnel/${current.id}`}>{label(current)}</Link> : hidden ? t("rep.restricted") : t("rep.none")}
        </b>
      </div>
      {canManage && (
        <div className="stat"><span>{t("rep.account")}</span><b>{person.account_username || t("rep.noAccount")}</b></div>
      )}
      <div className="stat"><span>{t("rep.reportsToThem")}</span><b>{subs.length}</b></div>
      {subs.length > 0 && (
        <ul className="list">
          {subs.map((s) => <li key={s.id} className="item"><Link to={`/personnel/${s.id}`}>{label(s)}</Link></li>)}
        </ul>
      )}
      {canManage && !editing && (
        <div className="row" style={{ marginTop: "1rem" }}>
          <button className="secondary" onClick={start}>{t("rep.edit")}</button>
        </div>
      )}
      {canManage && editing && (
        <form onSubmit={(e) => void save(e)} style={{ marginTop: "1rem" }}>
          <ErrorNotice error={error ?? candidates.error} />
          <input type="search" value={q} onChange={(e) => setQ(e.target.value)} maxLength={100}
                 aria-label={t("rep.search")} placeholder={t("rep.search")} />
          <Field label={t("rep.supervisor")}>
            <select value={supervisor} onChange={(e) => setSupervisor(e.target.value)}>
              <option value="">{t("rep.none")}</option>
              {current && !options.some((o) => o.id === current.id) && <option value={current.id}>{label(current)}</option>}
              {options.map((o) => <option key={o.id} value={o.id}>{label(o)}</option>)}
            </select>
          </Field>
          <p className="muted">{t("rep.rule")}</p>
          <Field label={t("rep.account")}>
            <input value={account} onChange={(e) => setAccount(e.target.value)} maxLength={64} autoCapitalize="none" autoComplete="off" />
          </Field>
          <p className="muted">{t("rep.accountHelp")}</p>
          <div className="row">
            <button type="submit">{t("common.save")}</button>
            <button type="button" className="secondary" onClick={() => setEditing(false)}>{t("common.cancel")}</button>
          </div>
        </form>
      )}
    </section>
  );
}
