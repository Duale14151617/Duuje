import { useState, type FormEvent } from "react";
import { api } from "../api/client";
import type { IntegrationCall, IntegrationClient, Page, Unit } from "../api/types";
import { useFetch } from "../api/useFetch";
import { useAuth } from "../auth/AuthContext";
import { Chip, ErrorNotice, Field, formatDate, Loading, Notice, Pager } from "../components/ui";
import { useI18n, type Key } from "../i18n";

const SECTIONS = ["personnel", "reports", "logistics", "training"] as const;

/** The key is held in component state only for as long as this panel is open: never stored, never put in a URL. */
function NewKey({ secret, onClose }: { secret: string; onClose: () => void }) {
  const { t } = useI18n();
  const [copied, setCopied] = useState(false);
  async function copy() {
    try { await navigator.clipboard.writeText(secret); setCopied(true); } catch { /* the user can select the text */ }
  }
  return (
    <div className="card" role="alert">
      <Notice>{t("int.newKey")}</Notice>
      <p className="mono">{secret}</p>
      <div className="row">
        <button className="secondary" onClick={() => void copy()}>{copied ? "✓" : t("common.copy")}</button>
        <button onClick={onClose}>{t("int.saved")}</button>
      </div>
    </div>
  );
}

function AddClient({ onCreated }: { onCreated: (c: IntegrationClient) => void }) {
  const { t, name } = useI18n();
  const [form, setForm] = useState({ name: "", description: "", org_unit: "", expires: "" });
  const [scopes, setScopes] = useState<string[]>([]);
  const [error, setError] = useState<unknown>(null);
  const units = useFetch<Page<Unit>>("/organization/units/", { active: "true", page_size: 100, level: "region" });

  async function save(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      const created = await api<IntegrationClient>("/integrations/clients/", { method: "POST", body: {
        name: form.name, description: form.description, org_unit: form.org_unit, scopes,
        expires_at: new Date(`${form.expires}T23:59:59`).toISOString() } });
      onCreated(created);
    } catch (err) { setError(err); }
  }
  const toggle = (s: string) => setScopes((cur) => (cur.includes(s) ? cur.filter((x) => x !== s) : [...cur, s]));
  return (
    <form className="card" onSubmit={(e) => void save(e)}>
      <h2>{t("int.add")}</h2>
      <ErrorNotice error={error} />
      <Field label={t("int.name")}><input value={form.name} maxLength={120} onChange={(e) => setForm({ ...form, name: e.target.value })} required /></Field>
      <Field label={t("int.description")}><input value={form.description} maxLength={300} onChange={(e) => setForm({ ...form, description: e.target.value })} /></Field>
      <fieldset>
        <legend>{t("int.sections")}</legend>
        {SECTIONS.map((s) => (
          <label key={s} className="row"><input type="checkbox" checked={scopes.includes(s)} onChange={() => toggle(s)} />{t(`an.tab.${s}` as Key)}</label>
        ))}
      </fieldset>
      <Field label={t("int.unit")}>
        <select value={form.org_unit} onChange={(e) => setForm({ ...form, org_unit: e.target.value })} required>
          <option value="" />
          {units.data?.results.map((u) => <option key={u.id} value={u.id}>{name(u)}</option>)}
        </select>
      </Field>
      <Field label={t("int.expires")}><input type="date" value={form.expires} onChange={(e) => setForm({ ...form, expires: e.target.value })} required /></Field>
      <button type="submit">{t("common.create")}</button>
    </form>
  );
}

function Calls({ id }: { id: string }) {
  const { t, lang } = useI18n();
  const [page, setPage] = useState(1);
  const calls = useFetch<Page<IntegrationCall>>(`/integrations/clients/${id}/calls/`, { page });
  if (calls.loading && !calls.data) return <Loading />;
  if (calls.data && calls.data.results.length === 0) return <p className="muted">{t("int.noCalls")}</p>;
  return (
    <>
      <ErrorNotice error={calls.error} />
      <div className="table-wrap">
        <table>
          <thead><tr><th>{t("int.when")}</th><th>{t("int.endpoint")}</th><th>{t("int.httpStatus")}</th><th>{t("int.outcome")}</th></tr></thead>
          <tbody>
            {calls.data?.results.map((c) => (
              <tr key={c.id}><td>{formatDate(c.at, lang)}</td><td className="mono">{c.endpoint}</td><td>{c.status_code}</td><td>{c.outcome}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
      {calls.data && <Pager page={page} count={calls.data.count} pageSize={25} onPage={setPage} />}
    </>
  );
}

function ClientCard({ c, enabled, onChanged, onSecret }: {
  c: IntegrationClient; enabled: boolean; onChanged: () => void; onSecret: (k: string) => void }) {
  const { t, lang } = useI18n();
  const [error, setError] = useState<unknown>(null);
  const [showCalls, setShowCalls] = useState(false);
  const live = c.status === "active";

  async function revoke() {
    if (!window.confirm(t("int.confirmRevoke"))) return;
    setError(null);
    try { await api(`/integrations/clients/${c.id}/revoke/`, { method: "POST", body: {} }); onChanged(); } catch (err) { setError(err); }
  }
  async function rotate() {
    if (!window.confirm(t("int.confirmRotate"))) return;
    setError(null);
    try {
      const r = await api<IntegrationClient>(`/integrations/clients/${c.id}/rotate/`, { method: "POST", body: { version: c.version } });
      if (r.key) onSecret(r.key);
      onChanged();
    } catch (err) { setError(err); }
  }
  return (
    <li className="item">
      <h2>{c.name}</h2>
      <div className="row">
        <Chip tone={live ? "approved" : "bad"}>{t(`int.status.${c.status}` as Key)}</Chip>
        <span className="muted">{t("int.prefix")}: <span className="mono">{c.key_prefix}</span></span>
        <span className="muted">{t("int.expires")}: {formatDate(c.expires_at, lang)}</span>
      </div>
      <p className="muted">{c.scopes.map((s) => t(`an.tab.${s as typeof SECTIONS[number]}` as Key)).join(", ")} · {c.org_unit_code}</p>
      <p className="muted">{c.last_used_at ? t("int.lastUsed", { when: formatDate(c.last_used_at, lang) }) : t("int.neverUsed")}</p>
      {c.description && <p>{c.description}</p>}
      <ErrorNotice error={error} />
      <div className="row">
        {live && enabled && <button className="secondary" onClick={() => void rotate()}>{t("int.rotate")}</button>}
        {live && <button className="secondary" onClick={() => void revoke()}>{t("int.revoke")}</button>}
        <button className="secondary" onClick={() => setShowCalls(!showCalls)}>{showCalls ? t("int.hideCalls") : t("int.showCalls")}</button>
      </div>
      {showCalls && <><h3>{t("int.calls")}</h3><Calls id={c.id} /></>}
    </li>
  );
}

export function Integrations() {
  const { t } = useI18n();
  const { me, can } = useAuth();
  const [page, setPage] = useState(1);
  const [adding, setAdding] = useState(false);
  const [secret, setSecret] = useState<string | null>(null);
  const list = useFetch<Page<IntegrationClient>>("/integrations/clients/", { page });
  const enabled = !!me?.features.integrations;

  return (
    <>
      <div className="row" style={{ justifyContent: "space-between", marginBottom: "1rem" }}>
        <h1 style={{ margin: 0 }}>{t("int.title")}</h1>
        {can("integrations.manage") && enabled && !adding && <button onClick={() => setAdding(true)}>{t("int.add")}</button>}
      </div>
      <Notice>{t("int.note")}</Notice>
      {!enabled && <Notice kind="error">{t("int.disabled")}</Notice>}
      {secret && <NewKey secret={secret} onClose={() => setSecret(null)} />}
      {adding && <AddClient onCreated={(c) => { setAdding(false); if (c.key) setSecret(c.key); list.reload(); }} />}
      <ErrorNotice error={list.error} />
      {list.loading && !list.data ? <Loading /> : null}
      <ul className="list">
        {list.data?.results.map((c) => <ClientCard key={c.id} c={c} enabled={enabled} onChanged={list.reload} onSecret={setSecret} />)}
      </ul>
      {list.data && <Pager page={page} count={list.data.count} pageSize={25} onPage={setPage} />}
    </>
  );
}
