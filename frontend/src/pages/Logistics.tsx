import { useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { Asset, AssetEvt, InvCategory, LogisticsSummary, Page, Recon, StockLine, StockTxn } from "../api/types";
import { useFetch } from "../api/useFetch";
import { useAuth } from "../auth/AuthContext";
import { usePlaceableUnits } from "../components/hooks";
import { DataTable, type Column } from "../components/DataTable";
import { FilterBar } from "../components/FilterBar";
import { statusTone } from "../components/status";
import { Chip, ErrorNotice, Field, formatDate, Loading, Notice, Pager, Tabs } from "../components/ui";
import { useI18n, type Key } from "../i18n";

type Tab = "stock" | "assets" | "recon" | "categories" | "summary";
const ASSET_FROM: Record<string, string[]> = {
  issue: ["in_stock"], return: ["issued"], maintenance: ["in_stock"], restore: ["maintenance", "missing", "lost"],
  missing: ["in_stock", "issued", "maintenance"], lost: ["in_stock", "issued", "maintenance", "missing"],
  retire: ["in_stock", "maintenance", "lost", "missing"], transfer: ["in_stock"],
};

function Restricted() {
  const { t } = useI18n();
  return <Chip tone="draft">{t("log.restrictedBadge")}</Chip>;
}

function useCategories(kind: "stock" | "asset") {
  const r = useFetch<InvCategory[]>("/logistics/categories/");
  return (r.data ?? []).filter((c) => c.kind === kind && c.approval_status === "approved" && c.active);
}

/* ---------------------------------------------------------------- stock */
function StockTab() {
  const { t, name } = useI18n();
  const { can } = useAuth();
  const [below, setBelow] = useState(false);
  const [page, setPage] = useState(1);
  const [adding, setAdding] = useState(false);
  const list = useFetch<Page<StockLine>>("/logistics/stock/", { page, below_reorder: below ? "1" : undefined });
  const units = usePlaceableUnits();
  const cats = useCategories("stock");
  const [f, setF] = useState({ category: "", org_unit: "", uom: "units", reorder_level: "0" });
  const [error, setError] = useState<unknown>(null);

  async function add(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await api("/logistics/stock/", { method: "POST", body: { ...f, reorder_level: Number(f.reorder_level) } });
      setAdding(false);
      list.reload();
    } catch (err) { setError(err); }
  }
  const columns: Column<StockLine>[] = [
    { id: "category", header: t("log.category"), width: 240, locked: true, sort: (r) => name(r.category),
      cell: (r) => <><Link to={`/logistics/stock/${r.id}`}>{name(r.category)}</Link>{r.category.restricted && <> <Restricted /></>}</> },
    { id: "unit", header: t("log.unit"), width: 220, sort: (r) => name(r.org_unit), cell: (r) => name(r.org_unit) },
    { id: "qty", header: t("log.quantity"), width: 130, align: "right", sort: (r) => Number(r.quantity), cell: (r) => <b>{r.quantity}</b> },
    { id: "uom", header: t("log.uom"), width: 130, sort: (r) => r.uom, cell: (r) => r.uom },
    { id: "state", header: t("log.status"), width: 190, cell: (r) => (r.below_reorder ? <Chip tone="warn">{t("log.belowReorder")}</Chip> : <span className="muted">—</span>) },
  ];
  return (
    <>
      <FilterBar
        advancedExtra={<label className="check"><input type="checkbox" checked={below} onChange={(e) => { setBelow(e.target.checked); setPage(1); }} /><span>{t("log.belowOnly")}</span></label>}
        custom={[{ id: "below", label: t("log.belowOnly"), active: below, onClear: () => { setBelow(false); setPage(1); } }]}
        onReset={() => { setBelow(false); setPage(1); }} />
      {can("logistics.manage") && !adding && <button style={{ marginBottom: ".75rem" }} onClick={() => setAdding(true)}>{t("log.addLine")}</button>}
      {adding && (
        <form className="card" onSubmit={(e) => void add(e)}>
          <ErrorNotice error={error} />
          <Field label={t("log.category")}>
            <select value={f.category} onChange={(e) => setF({ ...f, category: e.target.value })} required>
              <option value="" />{cats.map((c) => <option key={c.id} value={c.id}>{name(c)}</option>)}
            </select>
          </Field>
          <Field label={t("log.unit")}>
            <select value={f.org_unit} onChange={(e) => setF({ ...f, org_unit: e.target.value })} required>
              <option value="" />{units.map((u) => <option key={u.id} value={u.id}>{name(u)}</option>)}
            </select>
          </Field>
          <div className="grid">
            <Field label={t("log.uom")}><input value={f.uom} maxLength={16} onChange={(e) => setF({ ...f, uom: e.target.value })} /></Field>
            <Field label={t("log.reorder")}><input type="number" min={0} value={f.reorder_level} onChange={(e) => setF({ ...f, reorder_level: e.target.value })} /></Field>
          </div>
          <div className="row">
            <button type="submit">{t("common.create")}</button>
            <button type="button" className="secondary" onClick={() => setAdding(false)}>{t("common.cancel")}</button>
          </div>
        </form>
      )}
      <ErrorNotice error={list.error} />
      <DataTable id="logistics-stock" caption={t("log.category")} columns={columns} rows={list.data?.results} rowKey={(s) => s.id} loading={list.loading}
                 filtered={below} onReset={() => { setBelow(false); setPage(1); }} empty={{ icon: "box", title: t("log.noItems") }}
                 page={page} count={list.data?.count} pageSize={25} onPage={setPage} />
    </>
  );
}

export function StockDetail() {
  const { id = "" } = useParams();
  const { t, lang, name } = useI18n();
  const { can } = useAuth();
  const line = useFetch<StockLine>(`/logistics/stock/${id}/`);
  const [page, setPage] = useState(1);
  const ledger = useFetch<Page<StockTxn>>(`/logistics/stock/${id}/transactions/`, { page });
  const units = usePlaceableUnits();
  const [kind, setKind] = useState("receive");
  const [qty, setQty] = useState("");
  const [reason, setReason] = useState("");
  const [toUnit, setToUnit] = useState("");
  const [error, setError] = useState<unknown>(null);
  const s = line.data;
  const refresh = () => { line.reload(); ledger.reload(); setQty(""); setReason(""); };

  async function apply(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await api(`/logistics/stock/${id}/transactions/`, { method: "POST", body: {
        kind, quantity: Number(qty), reason, expected_balance: s?.quantity } });
      refresh();
    } catch (err) { setError(err); }
  }
  async function transfer(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await api(`/logistics/stock/${id}/transfer/`, { method: "POST", body: { to_unit: toUnit, quantity: Number(qty), reason } });
      refresh();
    } catch (err) { setError(err); }
  }
  return (
    <>
      <p><Link to="/logistics">{t("common.back")}</Link></p>
      <ErrorNotice error={error ?? line.error} />
      {line.loading && !s ? <Loading /> : null}
      {s && (
        <section className="card">
          <div className="row" style={{ justifyContent: "space-between" }}>
            <h1 style={{ margin: 0 }}>{name(s.category)}</h1>
            {s.category.restricted && <Restricted />}
          </div>
          <p className="muted">{name(s.org_unit)}</p>
          <div className="stat"><span>{t("log.balance")}</span><b>{s.quantity} {s.uom}</b></div>
          <div className="stat"><span>{t("log.reorder")}</span><b>{s.reorder_level}</b></div>
        </section>
      )}
      {s && can("logistics.manage") && (
        <section className="card">
          <form onSubmit={(e) => void apply(e)}>
            <div className="grid">
              <Field label={t("log.action")}>
                <select value={kind} onChange={(e) => setKind(e.target.value)}>
                  <option value="receive">{t("log.receive")}</option><option value="issue">{t("log.issue")}</option>
                  <option value="adjust">{t("log.adjust")}</option>
                </select>
              </Field>
              <Field label={t("log.quantity")}><input type="number" value={qty} onChange={(e) => setQty(e.target.value)} required /></Field>
            </div>
            <Field label={t("log.reason")}><input value={reason} maxLength={300} onChange={(e) => setReason(e.target.value)} /></Field>
            <div className="row">
              <button type="submit">{t("log.apply")}</button>
            </div>
          </form>
          <form onSubmit={(e) => void transfer(e)} style={{ marginTop: "1rem" }}>
            <Field label={t("log.toUnit")}>
              <select value={toUnit} onChange={(e) => setToUnit(e.target.value)} required>
                <option value="" />{units.filter((u) => u.id !== s.org_unit.id).map((u) => <option key={u.id} value={u.id}>{name(u)}</option>)}
              </select>
            </Field>
            <button type="submit" className="secondary">{t("log.transfer")}</button>
          </form>
        </section>
      )}
      <h2>{t("log.ledger")}</h2>
      <ErrorNotice error={ledger.error} />
      <ul className="list">
        {ledger.data?.results.map((x) => (
          <li key={x.id} className="item">
            <b>{t(`tkind.${x.kind}` as Key)}</b> {x.delta > 0 ? `+${x.delta}` : x.delta} → {x.balance_after}
            {x.counterpart_unit ? <> · {name(x.counterpart_unit)}</> : null}
            <div className="muted">{x.actor_username} · {formatDate(x.created_at, lang)}{x.reason ? ` · ${x.reason}` : ""}</div>
          </li>
        ))}
      </ul>
      {ledger.data && <Pager page={page} count={ledger.data.count} pageSize={25} onPage={setPage} />}
    </>
  );
}

/* ---------------------------------------------------------------- assets */
function AssetsTab() {
  const { t, name } = useI18n();
  const { can } = useAuth();
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const [adding, setAdding] = useState(false);
  const list = useFetch<Page<Asset>>("/logistics/assets/", { q, status, page });
  const units = usePlaceableUnits();
  const cats = useCategories("asset");
  const [f, setF] = useState({ category: "", org_unit: "", identifier: "", description: "" });
  const [error, setError] = useState<unknown>(null);

  async function add(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try { await api("/logistics/assets/", { method: "POST", body: f }); setAdding(false); list.reload(); }
    catch (err) { setError(err); }
  }
  const columns: Column<Asset>[] = [
    { id: "id", header: t("log.identifier"), width: 200, locked: true, sort: (r) => r.identifier,
      cell: (r) => <><Link to={`/logistics/assets/${r.id}`}>{r.identifier}</Link>{r.category.restricted && <> <Restricted /></>}</> },
    { id: "category", header: t("log.category"), width: 200, sort: (r) => name(r.category), cell: (r) => name(r.category) },
    { id: "unit", header: t("log.unit"), width: 260, sort: (r) => name(r.org_unit), cell: (r) => <>{name(r.org_unit)}{r.issued_to_unit ? ` → ${name(r.issued_to_unit)}` : ""}</> },
    { id: "status", header: t("log.status"), width: 150, sort: (r) => r.status, cell: (r) => <Chip tone={statusTone(r.status)}>{t(`astatus.${r.status}` as Key)}</Chip> },
  ];
  return (
    <>
      <Notice>{t("log.restrictedNote")}</Notice>
      <FilterBar
        search={{ value: q, label: t("common.search"), onChange: (v) => { setQ(v); setPage(1); } }}
        filters={[{ id: "status", label: t("log.status"), value: status, onChange: (v) => { setStatus(v); setPage(1); }, options: Object.keys(ASSET_STATUS).map((s) => ({ value: s, label: t(`astatus.${s}` as Key) })) }]}
        onReset={() => { setQ(""); setStatus(""); setPage(1); }} />
      {can("logistics.manage") && !adding && <button style={{ marginBottom: ".75rem" }} onClick={() => setAdding(true)}>{t("log.addAsset")}</button>}
      {adding && (
        <form className="card" onSubmit={(e) => void add(e)}>
          <ErrorNotice error={error} />
          <Field label={t("log.category")}>
            <select value={f.category} onChange={(e) => setF({ ...f, category: e.target.value })} required>
              <option value="" />{cats.map((c) => <option key={c.id} value={c.id}>{name(c)}{c.restricted ? " *" : ""}</option>)}
            </select>
          </Field>
          <Field label={t("log.unit")}>
            <select value={f.org_unit} onChange={(e) => setF({ ...f, org_unit: e.target.value })} required>
              <option value="" />{units.map((u) => <option key={u.id} value={u.id}>{name(u)}</option>)}
            </select>
          </Field>
          <Field label={t("log.identifier")}><input value={f.identifier} onChange={(e) => setF({ ...f, identifier: e.target.value })} required /></Field>
          <Field label={t("log.description")}><input value={f.description} maxLength={200} onChange={(e) => setF({ ...f, description: e.target.value })} /></Field>
          <div className="row">
            <button type="submit">{t("common.create")}</button>
            <button type="button" className="secondary" onClick={() => setAdding(false)}>{t("common.cancel")}</button>
          </div>
        </form>
      )}
      <ErrorNotice error={list.error} />
      <DataTable id="logistics-assets" caption={t("log.addAsset")} columns={columns} rows={list.data?.results} rowKey={(a) => a.id} loading={list.loading}
                 filtered={!!(q || status)} onReset={() => { setQ(""); setStatus(""); setPage(1); }} empty={{ icon: "box", title: t("log.noItems") }}
                 page={page} count={list.data?.count} pageSize={25} onPage={setPage} />
    </>
  );
}
const ASSET_STATUS: Record<string, true> = { in_stock: true, issued: true, maintenance: true, missing: true, lost: true, retired: true };

export function AssetDetail() {
  const { id = "" } = useParams();
  const { t, lang, name } = useI18n();
  const { can } = useAuth();
  const asset = useFetch<Asset>(`/logistics/assets/${id}/`);
  const events = useFetch<AssetEvt[]>(`/logistics/assets/${id}/events/`);
  const units = usePlaceableUnits();
  const [action, setAction] = useState("");
  const [toUnit, setToUnit] = useState("");
  const [note, setNote] = useState("");
  const [custodian, setCustodian] = useState("");
  const [error, setError] = useState<unknown>(null);
  const a = asset.data;
  const options = a ? Object.keys(ASSET_FROM).filter((k) => ASSET_FROM[k].includes(a.status)) : [];
  const refresh = () => { asset.reload(); events.reload(); setNote(""); setAction(""); };

  async function change(e: FormEvent) {
    e.preventDefault();
    if (!a) return;
    setError(null);
    try {
      await api(`/logistics/assets/${a.id}/change/`, { method: "POST", body: { action, version: a.version, note, to_unit: toUnit || undefined } });
      refresh();
    } catch (err) { setError(err); }
  }
  async function setCust(clear: boolean) {
    if (!a) return;
    setError(null);
    try {
      await api(`/logistics/assets/${a.id}/custodian/`, { method: "POST", body: { username: clear ? null : custodian, version: a.version } });
      refresh();
    } catch (err) { setError(err); }
  }
  return (
    <>
      <p><Link to="/logistics">{t("common.back")}</Link></p>
      <ErrorNotice error={error ?? asset.error} />
      {asset.loading && !a ? <Loading /> : null}
      {a && (
        <section className="card">
          <div className="row" style={{ justifyContent: "space-between" }}>
            <h1 style={{ margin: 0 }}>{a.identifier}</h1>
            <div className="row">{a.category.restricted && <Restricted />}<Chip tone={a.status === "in_stock" ? "approved" : "draft"}>{t(`astatus.${a.status}` as Key)}</Chip></div>
          </div>
          <p className="muted">{name(a.category)} · {name(a.org_unit)}{a.issued_to_unit ? ` → ${name(a.issued_to_unit)}` : ""}</p>
          {a.description && <p>{a.description}</p>}
          <div className="stat"><span>{t("log.custodian")}</span><b>{a.custodian_username ?? t("log.noCustodian")}</b></div>
        </section>
      )}
      {a && can("logistics.manage") && (
        <>
          {options.length > 0 && (
            <form className="card" onSubmit={(e) => void change(e)}>
              <Field label={t("log.action")}>
                <select value={action} onChange={(e) => setAction(e.target.value)} required>
                  <option value="" />{options.map((o) => <option key={o} value={o}>{t(`aact.${o}` as Key)}</option>)}
                </select>
              </Field>
              {(action === "issue" || action === "transfer") && (
                <Field label={t("log.toUnit")}>
                  <select value={toUnit} onChange={(e) => setToUnit(e.target.value)} required>
                    <option value="" />{units.filter((u) => u.id !== a.org_unit.id).map((u) => <option key={u.id} value={u.id}>{name(u)}</option>)}
                  </select>
                </Field>
              )}
              <Field label={t("log.note")}><input value={note} maxLength={300} onChange={(e) => setNote(e.target.value)} /></Field>
              <button type="submit">{t("log.apply")}</button>
            </form>
          )}
          <section className="card">
            <Field label={t("log.custodian")}><input value={custodian} autoCapitalize="none" onChange={(e) => setCustodian(e.target.value)} /></Field>
            <div className="row">
              <button className="secondary" onClick={() => void setCust(false)} disabled={!custodian}>{t("log.setCustodian")}</button>
              {a.custodian_username && <button className="secondary" onClick={() => void setCust(true)}>{t("log.noCustodian")}</button>}
            </div>
          </section>
        </>
      )}
      <h2>{t("log.events")}</h2>
      <ul className="list">
        {events.data?.map((x) => (
          <li key={x.id} className="item">
            <b>{t(`aevent.${x.kind}` as Key)}</b>
            {x.to_unit ? <> · {name(x.to_unit)}</> : null}
            <div className="muted">{x.actor_username} · {formatDate(x.created_at, lang)}{x.note ? ` · ${x.note}` : ""}</div>
          </li>
        ))}
      </ul>
    </>
  );
}

/* ---------------------------------------------------------------- reconciliation */
function ReconTab() {
  const { t, name, lang } = useI18n();
  const navigate = useNavigate();
  const [page, setPage] = useState(1);
  const list = useFetch<Page<Recon>>("/logistics/reconciliations/", { page });
  const units = usePlaceableUnits();
  const [unit, setUnit] = useState("");
  const [error, setError] = useState<unknown>(null);

  async function start(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      const r = await api<Recon>("/logistics/reconciliations/", { method: "POST", body: { org_unit: unit } });
      navigate(`/logistics/reconciliations/${r.id}`);
    } catch (err) { setError(err); }
  }
  return (
    <>
      <form className="card row" onSubmit={(e) => void start(e)}>
        <div className="grow">
          <Field label={t("log.unit")}>
            <select value={unit} onChange={(e) => setUnit(e.target.value)} required>
              <option value="" />{units.map((u) => <option key={u.id} value={u.id}>{name(u)}</option>)}
            </select>
          </Field>
        </div>
        <button type="submit">{t("rec.start")}</button>
      </form>
      <ErrorNotice error={error ?? list.error} />
      {list.loading && !list.data ? <Loading /> : null}
      {list.data && list.data.results.length === 0 && <p>{t("log.noItems")}</p>}
      <ul className="list">
        {list.data?.results.map((r) => (
          <li key={r.id} className="item">
            <div className="row" style={{ justifyContent: "space-between" }}>
              <Link to={`/logistics/reconciliations/${r.id}`}><h2>{name(r.org_unit)}</h2></Link>
              <div className="row">{r.includes_restricted && <Restricted />}<Chip tone={r.status === "completed" ? "approved" : "draft"}>{t(`rstat.${r.status}` as Key)}</Chip></div>
            </div>
            <span className="muted">{r.started_by_username} · {formatDate(r.started_at, lang)}</span>
          </li>
        ))}
      </ul>
      {list.data && <Pager page={page} count={list.data.count} pageSize={25} onPage={setPage} />}
    </>
  );
}

export function ReconDetail() {
  const { id = "" } = useParams();
  const { t, name } = useI18n();
  const rec = useFetch<Recon>(`/logistics/reconciliations/${id}/`);
  const [counts, setCounts] = useState<Record<string, string>>({});
  const [found, setFound] = useState<Record<string, boolean>>({});
  const [loaded, setLoaded] = useState("");
  const [error, setError] = useState<unknown>(null);
  const r = rec.data;
  if (r && loaded !== r.id + r.version) {
    setLoaded(r.id + r.version);
    setCounts(Object.fromEntries((r.lines ?? []).filter((l) => l.counted_quantity !== null).map((l) => [l.id, String(l.counted_quantity)])));
    setFound(Object.fromEntries((r.lines ?? []).filter((l) => l.found !== null).map((l) => [l.id, !!l.found])));
  }
  const open = r?.status === "open";

  async function post(path: string, body: unknown) {
    setError(null);
    try { await api(`/logistics/reconciliations/${id}/${path}/`, { method: "POST", body }); rec.reload(); }
    catch (err) { setError(err); }
  }
  function save() {
    const lines = (r?.lines ?? []).flatMap<{ id: string; counted_quantity?: number; found?: boolean }>((l) =>
      l.kind === "stock"
        ? (counts[l.id] !== undefined && counts[l.id] !== "" ? [{ id: l.id, counted_quantity: Number(counts[l.id]) }] : [])
        : (found[l.id] !== undefined ? [{ id: l.id, found: found[l.id] }] : []));
    void post("count", { lines });
  }
  return (
    <>
      <p><Link to="/logistics">{t("common.back")}</Link></p>
      <ErrorNotice error={error ?? rec.error} />
      {rec.loading && !r ? <Loading /> : null}
      {r && (
        <>
          <div className="row" style={{ justifyContent: "space-between" }}>
            <h1 style={{ margin: 0 }}>{name(r.org_unit)}</h1>
            <div className="row">{r.includes_restricted && <Restricted />}<Chip tone={r.status === "completed" ? "approved" : "draft"}>{t(`rstat.${r.status}` as Key)}</Chip></div>
          </div>
          <h2 style={{ marginTop: "1rem" }}>{t("rec.lines")}</h2>
          <ul className="list">
            {(r.lines ?? []).map((l) => (
              <li key={l.id} className="item">
                <b>{l.label}</b>
                {l.kind === "stock" ? (
                  <div className="row" style={{ marginTop: ".4rem" }}>
                    <span className="muted">{t("rec.expected")}: {l.expected_quantity}</span>
                    <input type="number" min={0} style={{ maxWidth: "8rem" }} disabled={!open} aria-label={t("rec.counted")}
                           value={counts[l.id] ?? ""} onChange={(e) => setCounts({ ...counts, [l.id]: e.target.value })} />
                  </div>
                ) : (
                  <label className="row" style={{ marginTop: ".4rem" }}>
                    <input type="checkbox" style={{ width: "auto", minHeight: 0 }} disabled={!open} checked={found[l.id] ?? false}
                           onChange={(e) => setFound({ ...found, [l.id]: e.target.checked })} />
                    <span>{t("rec.found")}</span>
                  </label>
                )}
              </li>
            ))}
          </ul>
          {open && (
            <div className="row">
              <button className="secondary" onClick={save}>{t("rec.saveCounts")}</button>
              <button onClick={() => void post("complete", { version: r.version })}>{t("rec.complete")}</button>
              <button className="danger" onClick={() => void post("cancel", { version: r.version })}>{t("rec.cancel")}</button>
            </div>
          )}
        </>
      )}
    </>
  );
}

/* ---------------------------------------------------------------- categories + summary */
function CategoriesTab() {
  const { t, name } = useI18n();
  const { can } = useAuth();
  const list = useFetch<InvCategory[]>("/logistics/categories/");
  const [adding, setAdding] = useState(false);
  const [f, setF] = useState({ code: "", name_en: "", name_so: "", kind: "stock", restricted: false });
  const [error, setError] = useState<unknown>(null);

  async function add(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try { await api("/logistics/categories/", { method: "POST", body: f }); setAdding(false); list.reload(); }
    catch (err) { setError(err); }
  }
  async function approve(c: InvCategory) {
    setError(null);
    try { await api(`/logistics/categories/${c.id}/approve/`, { method: "POST", body: { version: c.version } }); list.reload(); }
    catch (err) { setError(err); }
  }
  return (
    <>
      {can("logistics.configure") && !adding && <button style={{ marginBottom: ".75rem" }} onClick={() => setAdding(true)}>{t("cat.add")}</button>}
      {adding && (
        <form className="card" onSubmit={(e) => void add(e)}>
          <Field label={t("cat.code")}><input value={f.code} onChange={(e) => setF({ ...f, code: e.target.value })} required /></Field>
          <Field label={t("org.nameEn")}><input value={f.name_en} onChange={(e) => setF({ ...f, name_en: e.target.value })} required /></Field>
          <Field label={t("org.nameSo")}><input value={f.name_so} onChange={(e) => setF({ ...f, name_so: e.target.value })} /></Field>
          <Field label={t("cat.kind")}>
            <select value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}>
              <option value="stock">{t("cat.stock")}</option><option value="asset">{t("cat.asset")}</option>
            </select>
          </Field>
          <label className="row" style={{ marginBottom: ".75rem" }}>
            <input type="checkbox" style={{ width: "auto", minHeight: 0 }} checked={f.restricted} onChange={(e) => setF({ ...f, restricted: e.target.checked })} />
            <span>{t("cat.restricted")}</span>
          </label>
          <div className="row">
            <button type="submit">{t("common.create")}</button>
            <button type="button" className="secondary" onClick={() => setAdding(false)}>{t("common.cancel")}</button>
          </div>
        </form>
      )}
      <ErrorNotice error={error ?? list.error} />
      {list.loading && !list.data ? <Loading /> : null}
      <ul className="list">
        {list.data?.map((c) => {
          const mayApprove = c.restricted ? can("logistics.restricted_approve") : can("logistics.approve");
          return (
            <li key={c.id} className="item">
              <div className="row" style={{ justifyContent: "space-between" }}>
                <h2>{name(c)}</h2>
                <div className="row">
                  {c.restricted && <Restricted />}
                  <Chip tone={c.approval_status}>{t(`status.${c.approval_status}` as Key)}</Chip>
                </div>
              </div>
              <span className="muted">{c.code} · {t(c.kind === "stock" ? "cat.stock" : "cat.asset")}{!c.name_so ? ` · ${t("ranks.translationPending")}` : ""}</span>
              {mayApprove && c.approval_status === "draft" && (
                <div style={{ marginTop: ".5rem" }}><button onClick={() => void approve(c)}>{t("cat.approve")}</button></div>
              )}
            </li>
          );
        })}
      </ul>
    </>
  );
}

function SummaryTab() {
  const { t, name } = useI18n();
  const data = useFetch<LogisticsSummary>("/logistics/summary/");
  return (
    <>
      <ErrorNotice error={data.error} />
      {data.loading && !data.data ? <Loading /> : null}
      {data.data && data.data.rows.length === 0 && <p>{t("log.noItems")}</p>}
      {data.data && data.data.rows.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead><tr><th>{t("log.category")}</th><th>{t("sum.region")}</th><th>{t("lsum.lines")}</th>
              <th>{t("lsum.quantity")}</th><th>{t("lsum.below")}</th><th>{t("lsum.assets")}</th></tr></thead>
            <tbody>
              {data.data.rows.map((r) => (
                <tr key={`${r.category.id}-${r.region.id}`}>
                  <td>{name(r.category)}{r.category.restricted ? " *" : ""}</td><td>{name(r.region)}</td>
                  <td>{r.stock_lines}</td><td>{r.quantity}</td><td>{r.below_reorder}</td>
                  <td>{Object.entries(r.assets).map(([k, v]) => `${t(`astatus.${k}` as Key)}: ${v}`).join(", ") || "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

export function LogisticsHome() {
  const { t } = useI18n();
  const { can } = useAuth();
  const view = can("logistics.view") || can("logistics.restricted");
  const all: [Tab, Key, boolean][] = [
    ["stock", "log.tab.stock", view], ["assets", "log.tab.assets", view],
    ["recon", "log.tab.recon", can("logistics.reconcile")],
    ["categories", "log.tab.categories", view || can("logistics.configure") || can("logistics.approve") || can("logistics.restricted_approve")],
    ["summary", "log.tab.summary", can("logistics.report")],
  ];
  const tabs = all.filter(([, , show]) => show).map(([id, label]) => ({ id, label: t(label) }));
  const [tab, setTab] = useState<Tab>(tabs[0]?.id ?? "categories");
  return (
    <>
      <h1>{t("log.title")}</h1>
      <Tabs tabs={tabs} value={tab} onChange={setTab} />
      {tab === "stock" && <StockTab />}
      {tab === "assets" && <AssetsTab />}
      {tab === "recon" && <ReconTab />}
      {tab === "categories" && <CategoriesTab />}
      {tab === "summary" && <SummaryTab />}
    </>
  );
}
