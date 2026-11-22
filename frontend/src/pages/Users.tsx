import { useEffect, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { Assignment, Branch, Page, Person, Role, Unit, UserRow } from "../api/types";
import { useFetch } from "../api/useFetch";
import { useAuth } from "../auth/AuthContext";
import { DataTable, type Column } from "../components/DataTable";
import { FilterBar } from "../components/FilterBar";
import { Chip, ErrorNotice, Field, formatDate, Loading, Notice, PageHeader, EmptyState } from "../components/ui";
import { useI18n } from "../i18n";

function AddUser({ onDone }: { onDone: () => void }) {
  const { t, lang } = useI18n();
  const [username, setUsername] = useState("");
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [language, setLanguage] = useState("so");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [touched, setTouched] = useState(false);  // true once the administrator typed a username themselves
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [created, setCreated] = useState<{ username: string; password: string; expires: string } | null>(null);

  async function suggest() {
    if (!fullName.trim()) { setSuggestions([]); return; }
    try {
      const r = await api<{ suggestions: string[] }>("/users/suggest-username/", { query: { full_name: fullName.trim() } });
      setSuggestions(r.suggestions);
      if (!touched && r.suggestions[0]) setUsername(r.suggestions[0]);
    } catch { /* suggestions are a convenience; the server still validates the username */ }
  }

  async function save(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      const r = await api<UserRow & { temporary_password?: string }>("/users/", { method: "POST", body: {
        username, full_name: fullName, email, preferred_language: language, initial_password: password } });
      if (r.temporary_password) setCreated({ username: r.username, password: r.temporary_password, expires: r.temp_password_expires_at ?? "" });
      else onDone();
    } catch (err) { setError(err); }
  }
  if (created) {
    return (
      <section className="card">
        <h2>{t("users.add")}</h2>
        <Notice>{t("users.tempResult", { user: created.username, password: created.password, date: created.expires ? formatDate(created.expires, lang) : "" })}</Notice>
        <p className="muted">{t("users.tempOnce")}</p>
        <button type="button" onClick={onDone}>{t("users.done")}</button>
      </section>
    );
  }
  return (
    <form className="card" onSubmit={(e) => void save(e)}>
      <h2>{t("users.add")}</h2>
      <ErrorNotice error={error} />
      <Field label={t("users.fullName")}><input value={fullName} onChange={(e) => setFullName(e.target.value)} onBlur={() => void suggest()} required /></Field>
      <Field label={t("users.username")}>
        <input value={username} onChange={(e) => { setTouched(true); setUsername(e.target.value.toLowerCase()); }}
               autoCapitalize="none" autoComplete="off" spellCheck={false} minLength={3} maxLength={64}
               pattern={"[a-z0-9][a-z0-9_.\\-]{2,63}"} title={t("users.usernameRule")} required />
      </Field>
      <p className="muted">{t("users.usernameRule")}</p>
      {suggestions.length > 1 && (
        <div className="row">
          {suggestions.map((s) => <button key={s} type="button" className="secondary" onClick={() => { setTouched(true); setUsername(s); }}>{s}</button>)}
        </div>
      )}
      <Field label={t("users.email")}><input type="email" value={email} onChange={(e) => setEmail(e.target.value)} /></Field>
      <Field label={t("users.language")}>
        <select value={language} onChange={(e) => setLanguage(e.target.value)}>
          <option value="so">Soomaali</option><option value="en">English</option>
        </select>
      </Field>
      <Field label={t("users.initialPassword")}>
        <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" minLength={12} placeholder={t("users.generateHint")} />
      </Field>
      <p className="muted">{t("users.tempPasswordHelp")}</p>
      <button type="submit">{t("common.create")}</button>
    </form>
  );
}

type UserFilters = { is_active: string; email_verified: string; linked: string; has_role: string; never_signed_in: string };
const NO_FILTERS: UserFilters = { is_active: "", email_verified: "", linked: "", has_role: "", never_signed_in: "" };

export function Users() {
  const { t, lang } = useI18n();
  const { can } = useAuth();
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [adding, setAdding] = useState(false);
  const [f, setF] = useState<UserFilters>(NO_FILTERS);
  const users = useFetch<Page<UserRow>>("/users/", { q, page, ...f });
  const set = (k: keyof UserFilters) => (v: string) => { setF((p) => ({ ...p, [k]: v })); setPage(1); };
  const yesNo = [{ value: "true", label: t("users.f.yes") }, { value: "false", label: t("users.f.no") }];
  const reset = () => { setQ(""); setF(NO_FILTERS); setPage(1); };
  const anyFilter = !!q || Object.values(f).some((v) => v !== "");

  const columns: Column<UserRow>[] = [
    { id: "name", header: t("pers.fullName"), width: 240, locked: true, sort: (u) => u.full_name, cell: (u) => <Link to={`/users/${u.id}`}>{u.full_name}</Link> },
    { id: "username", header: t("users.username"), width: 200, sort: (u) => u.username, cell: (u) => u.username },
    { id: "state", header: t("pers.status"), width: 260,
      cell: (u) => <>{!u.is_active && <Chip tone="bad">{t("users.disabledBadge")}</Chip>}{u.mfa_enabled && <> <Chip tone="ok">{t("users.mfa")}</Chip></>}{u.must_change_password && <> <Chip tone="draft">{t("users.mustChange")}</Chip></>}{u.is_active && !u.mfa_enabled && !u.must_change_password && <span className="muted">—</span>}</> },
    { id: "roles", header: t("users.col.roles"), width: 120, sort: (u) => u.role_count ?? 0,
      cell: (u) => (u.role_count ?? 0) > 0 ? String(u.role_count) : <Chip tone="warn">{t("users.col.noRole")}</Chip> },
    { id: "email", header: t("users.email"), width: 190,
      cell: (u) => !u.email ? <span className="muted">—</span> : u.email_verified ? <Chip tone="ok">{t("account.verified")}</Chip> : <Chip tone="warn">{t("account.notVerified")}</Chip> },
    { id: "record", header: t("users.personnelRecord"), width: 170,
      cell: (u) => u.personnel_id ? <Link to={`/personnel/${u.personnel_id}`}>{t("users.openRecord")}</Link> : <span className="muted">—</span> },
    { id: "lastLogin", header: t("users.lastLogin"), width: 170, sort: (u) => u.last_login ?? "",
      cell: (u) => u.last_login ? formatDate(u.last_login, lang) : <span className="muted">{t("users.never")}</span> },
  ];
  const actions = can("users.manage") && !adding
    ? <div className="row">
        <button onClick={() => setAdding(true)}>{t("users.add")}</button>
        {can("roles.assign") && <Link to="/users/import"><button type="button" className="secondary">{t("users.bulk.open")}</button></Link>}
        <Link to="/users/review"><button type="button" className="secondary">{t("review.open")}</button></Link>
      </div>
    : <Link to="/users/review"><button type="button" className="secondary">{t("review.open")}</button></Link>;
  return (
    <>
      <PageHeader title={t("users.title")} actions={actions} />
      {adding && <AddUser onDone={() => { setAdding(false); users.reload(); }} />}
      <FilterBar search={{ value: q, label: t("common.search"), onChange: (v) => { setQ(v); setPage(1); } }} onReset={reset}
                 filters={[
                   { id: "active", label: t("pers.status"), value: f.is_active, onChange: set("is_active"),
                     options: [{ value: "true", label: t("users.f.active") }, { value: "false", label: t("users.disabledBadge") }] },
                   { id: "role", label: t("users.f.hasRole"), value: f.has_role, onChange: set("has_role"), options: yesNo },
                   { id: "email", label: t("users.f.emailVerified"), value: f.email_verified, onChange: set("email_verified"), options: yesNo },
                   { id: "linked", label: t("users.f.linked"), value: f.linked, onChange: set("linked"), options: yesNo, advanced: true },
                   { id: "never", label: t("users.f.neverSignedIn"), value: f.never_signed_in, onChange: set("never_signed_in"),
                     options: [{ value: "true", label: t("users.f.yes") }], advanced: true },
                 ]} />
      <ErrorNotice error={users.error} />
      <DataTable id="users" caption={t("users.title")} columns={columns} rows={users.data?.results} rowKey={(u) => u.id} loading={users.loading}
                 filtered={anyFilter} onReset={reset} empty={{ icon: "users", title: t("common.empty") }}
                 page={page} count={users.data?.count} pageSize={25} onPage={setPage} />
    </>
  );
}

function PersonnelLink({ user, onChanged }: { user: UserRow; onChanged: () => void }) {
  const { t, name } = useI18n();
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  const [pick, setPick] = useState("");
  const [error, setError] = useState<unknown>(null);
  useEffect(() => { const h = setTimeout(() => setDebounced(q.trim()), 250); return () => clearTimeout(h); }, [q]);
  const linked = user.personnel_id ?? null;
  const record = useFetch<Person>(linked ? `/personnel/${linked}/` : null);
  const results = useFetch<Page<Person>>(!linked && debounced.length >= 2 ? "/personnel/" : null, { q: debounced, page_size: 20 });
  const options = results.data?.results ?? [];
  const label = (p: Person) => `${p.rank.code} ${name(p.rank)} · ${p.full_name}${p.service_number ? ` · ${p.service_number}` : ""}`;

  async function link(e: FormEvent) {
    e.preventDefault();
    setError(null);
    const person = options.find((p) => p.id === pick);
    if (!person) return;
    try {
      await api(`/personnel/${person.id}/`, { method: "PATCH", body: { version: person.version, account_username: user.username } });
      setQ(""); setPick(""); onChanged();
    } catch (err) { setError(err); }
  }
  async function unlink() {
    if (!record.data) return;
    setError(null);
    try {
      await api(`/personnel/${record.data.id}/`, { method: "PATCH", body: { version: record.data.version, account_username: null } });
      onChanged();
    } catch (err) { setError(err); }
  }

  return (
    <section className="card">
      <h2>{t("users.personnelRecord")}</h2>
      <ErrorNotice error={error ?? record.error} />
      {linked ? (
        <>
          {record.data && <p>{label(record.data)}</p>}
          <div className="row">
            <Link to={`/personnel/${linked}`}>{t("users.openRecord")}</Link>
            <button type="button" className="secondary" onClick={() => void unlink()} disabled={!record.data}>{t("users.unlinkRecord")}</button>
          </div>
        </>
      ) : (
        <form onSubmit={(e) => void link(e)}>
          <p className="muted">{t("users.linkHelp")}</p>
          <input type="search" value={q} onChange={(e) => { setQ(e.target.value); setPick(""); }} maxLength={100}
                 aria-label={t("rline.search")} placeholder={t("rline.search")} />
          <ErrorNotice error={results.error} />
          {options.length > 0 && (
            <Field label={t("users.personnelRecord")}>
              <select value={pick} onChange={(e) => setPick(e.target.value)} required>
                <option value="" />
                {options.map((p) => <option key={p.id} value={p.id}>{label(p)}</option>)}
              </select>
            </Field>
          )}
          <button type="submit" disabled={!pick}>{t("users.linkRecord")}</button>
        </form>
      )}
    </section>
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
  const [tempShown, setTempShown] = useState<{ password: string; expires: string } | null>(null);
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
    const temp = window.prompt(t("users.resetPrompt"));
    if (temp === null) return;  // cancelled
    setError(null);
    setTempShown(null);
    try {
      const r = await api<{ temporary_password?: string; expires_at?: string } | undefined>(`/users/${id}/reset-password/`, {
        method: "POST", body: temp ? { temporary_password: temp } : {} });
      if (r?.temporary_password) setTempShown({ password: r.temporary_password, expires: r.expires_at ?? "" });
      user.reload(); assignments.reload();
    } catch (err) { setError(err); }
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
            {u.must_change_password && u.temp_password_expires_at && <Chip tone="warn">{t("users.tempExpires", { date: formatDate(u.temp_password_expires_at, lang) })}</Chip>}
            {u.email && (u.email_verified ? <Chip tone="ok">{t("account.verified")}</Chip> : <Chip tone="warn">{t("account.notVerified")}</Chip>)}
          </div>
          {manage && (
            <>
            <div className="row mt-1">
              {u.is_active
                ? <button className="danger" onClick={() => void post("disable/")}>{t("users.disable")}</button>
                : <button onClick={() => void post("enable/")}>{t("users.enable")}</button>}
              <button className="secondary" onClick={() => void post("revoke-sessions/")}>{t("users.revokeSessions")}</button>
              <button className="secondary" onClick={() => void post("reset-mfa/")}>{t("users.resetMfa")}</button>
              <button className="secondary" onClick={() => void resetPassword()}>{t("users.resetPassword")}</button>
              <button className="secondary" onClick={() => void issueResetCode()}>{t("users.issueReset")}</button>
            </div>
            {tempShown && <Notice>{t("users.tempResult", { user: u.username, password: tempShown.password, date: tempShown.expires ? formatDate(tempShown.expires, lang) : "" })}</Notice>}
            {issued && <Notice>{t("users.resetCodeShown", { minutes: issued.valid_minutes, code: issued.code })}</Notice>}
            </>
          )}
        </section>
      )}
      {u && can("personnel.manage") && <PersonnelLink user={u} onChanged={() => user.reload()} />}
      <h2>{t("users.assignments")}</h2>
      {assignments.data && assignments.data.length === 0 && <EmptyState title={t("users.noAssignments")} />}
      <ul className="list">
        {assignments.data?.map((a) => (
          <li key={a.id} className="item">
            <div className="row row-between">
              <div>
                <h2>{name(a.role)}</h2>
                <span className="muted">
                  {name(a.org_unit)}{a.branch ? ` › ${name(a.branch)}` : ""}
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
          {(branches.data?.results.length ?? 0) > 1 && (
            <Field label={t("org.branch")}>
              <select value={branch} onChange={(e) => setBranch(e.target.value)}>
                <option value="">{t("scope.allBranches")}</option>
                {branches.data?.results.map((b) => <option key={b.id} value={b.id}>{name(b)}</option>)}
              </select>
            </Field>
          )}
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
