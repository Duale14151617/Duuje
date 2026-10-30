import { useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { Assignment, Branch, Page, Role, Unit, UserRow } from "../api/types";
import { useFetch } from "../api/useFetch";
import { useAuth } from "../auth/AuthContext";
import { DataTable, type Column } from "../components/DataTable";
import { FilterBar } from "../components/FilterBar";
import { Chip, ErrorNotice, Field, formatDate, Loading, Notice, PageHeader } from "../components/ui";
import { useI18n } from "../i18n";

function AddUser({ onDone }: { onDone: () => void }) {
  const { t } = useI18n();
  const [username, setUsername] = useState("");
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [language, setLanguage] = useState("so");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<unknown>(null);

  async function save(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await api("/users/", { method: "POST", body: {
        username, full_name: fullName, email, preferred_language: language, initial_password: password } });
      onDone();
    } catch (err) { setError(err); }
  }
  return (
    <form className="card" onSubmit={(e) => void save(e)}>
      <h2>{t("users.add")}</h2>
      <ErrorNotice error={error} />
      <Field label={t("users.username")}><input value={username} onChange={(e) => setUsername(e.target.value)} autoCapitalize="none" required /></Field>
      <Field label={t("users.fullName")}><input value={fullName} onChange={(e) => setFullName(e.target.value)} required /></Field>
      <Field label={t("users.email")}><input type="email" value={email} onChange={(e) => setEmail(e.target.value)} /></Field>
      <Field label={t("users.language")}>
        <select value={language} onChange={(e) => setLanguage(e.target.value)}>
          <option value="so">Soomaali</option><option value="en">English</option>
        </select>
      </Field>
      <Field label={t("users.initialPassword")}>
        <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" minLength={12} required />
      </Field>
      <button type="submit">{t("common.create")}</button>
    </form>
  );
}

export function Users() {
  const { t } = useI18n();
  const { can } = useAuth();
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [adding, setAdding] = useState(false);
  const users = useFetch<Page<UserRow>>("/users/", { q, page });

  const columns: Column<UserRow>[] = [
    { id: "name", header: t("pers.fullName"), width: 240, locked: true, sort: (u) => u.full_name, cell: (u) => <Link to={`/users/${u.id}`}>{u.full_name}</Link> },
    { id: "username", header: t("users.username"), width: 200, sort: (u) => u.username, cell: (u) => u.username },
    { id: "state", header: t("pers.status"), width: 260,
      cell: (u) => <>{!u.is_active && <Chip tone="bad">{t("users.disabledBadge")}</Chip>}{u.mfa_enabled && <> <Chip tone="ok">{t("users.mfa")}</Chip></>}{u.is_active && !u.mfa_enabled && <span className="muted">—</span>}</> },
  ];
  return (
    <>
      <PageHeader title={t("users.title")} actions={can("users.manage") && !adding ? <button onClick={() => setAdding(true)}>{t("users.add")}</button> : undefined} />
      {adding && <AddUser onDone={() => { setAdding(false); users.reload(); }} />}
      <FilterBar search={{ value: q, label: t("common.search"), onChange: (v) => { setQ(v); setPage(1); } }} onReset={() => { setQ(""); setPage(1); }} />
      <ErrorNotice error={users.error} />
      <DataTable id="users" caption={t("users.title")} columns={columns} rows={users.data?.results} rowKey={(u) => u.id} loading={users.loading}
                 filtered={!!q} onReset={() => { setQ(""); setPage(1); }} empty={{ icon: "users", title: t("common.empty") }}
                 page={page} count={users.data?.count} pageSize={25} onPage={setPage} />
    </>
  );
}

export function UserDetail() {
  const { id = "" } = useParams();
  const { t, lang, name } = useI18n();
  const { can } = useAuth();
  const user = useFetch<UserRow>(`/users/${id}/`);
  const assignments = useFetch<Assignment[]>(`/users/${id}/assignments/`);
  const roles = useFetch<Role[]>("/roles/");
  const units = useFetch<Page<Unit>>("/organization/units/", { page_size: 100 });
  const branches = useFetch<Page<Branch>>("/organization/branches/", { page_size: 100 });
  const [error, setError] = useState<unknown>(null);
  const [role, setRole] = useState("");
  const [unit, setUnit] = useState("");
  const [branch, setBranch] = useState("");
  const [validFrom, setValidFrom] = useState("");
  const [validUntil, setValidUntil] = useState("");
  const [issued, setIssued] = useState<{ code: string; valid_minutes: number } | null>(null);
  const manage = can("users.manage");
  const assign = can("roles.assign");

  async function run(fn: () => Promise<unknown>) {
    setError(null);
    try { await fn(); user.reload(); assignments.reload(); } catch (err) { setError(err); }
  }
  const post = (path: string, body?: unknown) => run(() => api(`/users/${id}/${path}`, { method: "POST", body }));

  async function addAssignment(e: FormEvent) {
    e.preventDefault();
    await post("assignments/", {
      role, org_unit: unit, branch: branch || null, valid_from: validFrom || null, valid_until: validUntil || null });
  }
  async function issueResetCode() {
    setError(null);
    setIssued(null);
    try { setIssued(await api<{ code: string; valid_minutes: number }>(`/users/${id}/issue-reset-code/`, { method: "POST" })); }
    catch (err) { setError(err); }
  }
  async function resetPassword() {
    const temp = window.prompt(t("users.tempPassword"));
    if (temp) await post("reset-password/", { temporary_password: temp });
  }

  const u = user.data;
  return (
    <>
      <p><Link to="/users">{t("common.back")}</Link></p>
      <ErrorNotice error={error ?? user.error} />
      {user.loading && !u ? <Loading /> : null}
      {u && (
        <section className="card">
          <h1>{u.full_name}</h1>
          <p className="muted">{u.username} · {t("users.lastLogin")}: {u.last_login ? formatDate(u.last_login, lang) : t("users.never")}</p>
          <div className="row">
            {!u.is_active && <Chip tone="bad">{t("users.disabledBadge")}</Chip>}
            {u.mfa_enabled && <Chip tone="approved">{t("users.mfa")}</Chip>}
            {u.must_change_password && <Chip tone="draft">{t("users.mustChange")}</Chip>}
          </div>
          {manage && (
            <>
            <div className="row" style={{ marginTop: "1rem" }}>
              {u.is_active
                ? <button className="danger" onClick={() => void post("disable/")}>{t("users.disable")}</button>
                : <button onClick={() => void post("enable/")}>{t("users.enable")}</button>}
              <button className="secondary" onClick={() => void post("revoke-sessions/")}>{t("users.revokeSessions")}</button>
              <button className="secondary" onClick={() => void post("reset-mfa/")}>{t("users.resetMfa")}</button>
              <button className="secondary" onClick={() => void resetPassword()}>{t("users.resetPassword")}</button>
              <button className="secondary" onClick={() => void issueResetCode()}>{t("users.issueReset")}</button>
            </div>
            {issued && <Notice>{t("users.resetCodeShown", { minutes: issued.valid_minutes, code: issued.code })}</Notice>}
            </>
          )}
        </section>
      )}
      <h2>{t("users.assignments")}</h2>
      {assignments.data && assignments.data.length === 0 && <p>{t("users.noAssignments")}</p>}
      <ul className="list">
        {assignments.data?.map((a) => (
          <li key={a.id} className="item">
            <div className="row" style={{ justifyContent: "space-between" }}>
              <div>
                <h2>{name(a.role)}</h2>
                <span className="muted">
                  {name(a.org_unit)} › {a.branch ? name(a.branch) : t("scope.allBranches")}
                  {a.valid_until ? ` · ${t("scope.until", { date: a.valid_until })}` : ""}
                </span>
              </div>
              {a.revoked_at
                ? <Chip tone="bad">{t("users.revoke")}</Chip>
                : assign && <button className="secondary" onClick={() => void post(`assignments/${a.id}/revoke/`)}>{t("users.revoke")}</button>}
            </div>
          </li>
        ))}
      </ul>
      {assign && (
        <form className="card" onSubmit={(e) => void addAssignment(e)}>
          <h2>{t("users.assignRole")}</h2>
          <Field label={t("users.role")}>
            <select value={role} onChange={(e) => setRole(e.target.value)} required>
              <option value="" />
              {roles.data?.map((r) => <option key={r.id} value={r.code}>{name(r)}</option>)}
            </select>
          </Field>
          <Field label={t("org.parent")}>
            <select value={unit} onChange={(e) => setUnit(e.target.value)} required>
              <option value="" />
              {units.data?.results.map((x) => <option key={x.id} value={x.id}>{"\u00a0\u00a0".repeat(x.depth)}{name(x)}</option>)}
            </select>
          </Field>
          <Field label={t("org.branch")}>
            <select value={branch} onChange={(e) => setBranch(e.target.value)}>
              <option value="">{t("scope.allBranches")}</option>
              {branches.data?.results.map((b) => <option key={b.id} value={b.id}>{name(b)}</option>)}
            </select>
          </Field>
          <div className="grid">
            <Field label={t("users.validFrom")}><input type="date" value={validFrom} onChange={(e) => setValidFrom(e.target.value)} /></Field>
            <Field label={t("users.validUntil")}><input type="date" value={validUntil} onChange={(e) => setValidUntil(e.target.value)} /></Field>
          </div>
          <button type="submit">{t("users.assignRole")}</button>
        </form>
      )}
    </>
  );
}
