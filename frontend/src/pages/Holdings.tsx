import { useState, type FormEvent } from "react";
import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { useFetch } from "../api/useFetch";
import { Chip, ErrorNotice, Field, Notice } from "../components/ui";
import { UnitPicker } from "../components/UnitPicker";
import { useI18n, type Key } from "../i18n";

const KINDS = ["issue", "return", "expended", "lost"] as const;
type Kind = (typeof KINDS)[number];

interface Named { code: string; name_en: string; name_so: string }
interface UnitB { id: string; code: string; name_en: string; name_so: string }
interface HeldWeapon { id: string; serial: string; weapon_type: string; caliber: string; condition: string; issued_at: string; category: Named }
interface RoundsLine { stock_line: string; category: Named; issued: number; returned: number; expended: number; lost: number; held: number }
interface Soldier {
  personnel: { id: string; full_name: string; service_number: string | null; status: string; rank: Named; unit: UnitB | null };
  weapons: HeldWeapon[];
  rounds: { total: number; lines: RoundsLine[] };
}
interface Report { results: Soldier[]; totals: { soldiers: number; weapons: number; rounds: number }; truncated?: boolean }
interface Move {
  id: string; kind: Kind; quantity: number; delta: number; balance_after: number; category: Named; reference: string;
  authority_ref: string; note: string; actor: string; store_transaction: string | null; at: string;
}
interface AmmoLine { id: string; quantity: number; uom: string; category: Named; unit: UnitB }


/** Superior's report: what each soldier holds (weapons by serial number, rounds left per ammunition type), plus issuing and recording rounds. */
export function Holdings() {
  const { t, name } = useI18n();
  const { can } = useAuth();
  const canManage = can("weapons.manage");
  const [unit, setUnit] = useState("");
  const [q, setQ] = useState("");
  const [openId, setOpenId] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);
  const report = useFetch<Report>("/weapons/holdings/", { org_unit: unit || undefined, q: q.trim() || undefined, all: showAll ? 1 : undefined });

  return (
    <>
      <h1>{t("hold.title")}</h1>
      <ErrorNotice error={report.error} />
      <section className="card">
        <UnitPicker label={t("weap.holdingUnit")} value={unit} allowAll onChange={(id) => setUnit(id)} />
        <input type="search" value={q} maxLength={60} placeholder={t("hold.search")} aria-label={t("hold.search")} onChange={(e) => setQ(e.target.value)} />
        <label className="row"><input type="checkbox" style={{ width: "auto", minHeight: 0 }} checked={showAll} onChange={(e) => setShowAll(e.target.checked)} /><span>{t("hold.showAll")}</span></label>
        {report.data && (
          <div>
            <div className="stat"><span>{t("hold.soldiers")}</span><b>{report.data.totals.soldiers}</b></div>
            <div className="stat"><span>{t("hold.weapons")}</span><b>{report.data.totals.weapons}</b></div>
            <div className="stat"><span>{t("hold.rounds")}</span><b>{report.data.totals.rounds}</b></div>
          </div>
        )}
      </section>
      {report.data?.truncated && <Notice kind="error">{t("hold.truncated")}</Notice>}
      {report.data && report.data.results.length === 0 && <p className="muted">{t("hold.none")}</p>}
      <ul className="list">
        {(report.data?.results ?? []).map((s) => {
          const p = s.personnel;
          return (
            <li key={p.id} className="item">
              <button type="button" className="secondary" onClick={() => setOpenId(openId === p.id ? null : p.id)}>
                <b>{p.rank.code} {p.full_name}</b> ({p.service_number ?? "—"})
              </button>
              <div className="row">
                <Chip tone={s.weapons.length ? "approved" : "draft"}>{t("hold.weapons")}: {s.weapons.length}</Chip>
                <Chip tone={s.rounds.total ? "approved" : "draft"}>{t("hold.roundsLeft")}: {s.rounds.total}</Chip>
                {p.unit && <span className="muted">{name(p.unit)}</span>}
              </div>
              {openId === p.id && <SoldierDetail s={s} canManage={canManage} onChanged={report.reload} />}
            </li>
          );
        })}
      </ul>
    </>
  );
}

function SoldierDetail({ s, canManage, onChanged }: { s: Soldier; canManage: boolean; onChanged: () => void }) {
  const { t, name } = useI18n();
  const [open, setOpen] = useState(false);
  return (
    <div className="card">
      <h3>{t("hold.weapons")}</h3>
      {s.weapons.length === 0 && <p className="muted">{t("hold.noWeapons")}</p>}
      <ul className="list">
        {s.weapons.map((w) => (
          <li key={w.id} className="item">
            <b>{w.serial}</b> · {w.weapon_type}{w.caliber ? ` · ${w.caliber}` : ""}
            <div className="row"><Chip tone={w.condition === "serviceable" ? "approved" : w.condition === "unserviceable" ? "bad" : "draft"}>{t(`wcond.${w.condition}` as Key)}</Chip></div>
          </li>
        ))}
      </ul>
      <h3>{t("hold.rounds")}</h3>
      {s.rounds.lines.length === 0 && <p className="muted">{t("hold.noRounds")}</p>}
      <ul className="list">
        {s.rounds.lines.map((r) => (
          <li key={r.stock_line} className="item">
            <div className="stat"><span>{name(r.category)}</span><b>{r.held}</b></div>
            <p className="muted">{t("hold.issued")} {r.issued} · {t("hold.returned")} {r.returned} · {t("hold.expended")} {r.expended} · {t("hold.lost")} {r.lost}</p>
          </li>
        ))}
      </ul>
      <p className="muted">{t("hold.heldNote")}</p>
      <History personnelId={s.personnel.id} version={s.rounds.total} />
      {canManage && !open && s.personnel.unit && <div className="row"><button type="button" onClick={() => setOpen(true)}>{t("hold.manage")}</button></div>}
      {canManage && open && s.personnel.unit && (
        <RoundsForm person={s.personnel} unitId={s.personnel.unit.id} lines={s.rounds.lines}
                    onDone={() => { setOpen(false); onChanged(); }} onCancel={() => setOpen(false)} />
      )}
    </div>
  );
}

function RoundsForm({ person, unitId, lines, onDone, onCancel }: {
  person: Soldier["personnel"]; unitId: string; lines: RoundsLine[]; onDone: () => void; onCancel: () => void;
}) {
  const { t, name } = useI18n();
  const [kind, setKind] = useState<Kind>("issue");
  const [line, setLine] = useState("");
  const [quantity, setQuantity] = useState("");
  const [reference, setReference] = useState("");
  const [authority, setAuthority] = useState("");
  const [note, setNote] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const store = useFetch<{ results: AmmoLine[] }>("/weapons/ammo_lines/", { org_unit: unitId });
  const storeLines = store.data?.results ?? [];
  // Return, expended and lost can only act on types the soldier already holds; issue draws from the unit's store.
  const heldLines = lines.filter((l) => l.held > 0);
  const options = kind === "issue"
    ? storeLines.map((l) => ({ id: l.id, label: `${name(l.category)} (${l.quantity} ${t("hold.inStore")})` }))
    : heldLines.map((l) => ({ id: l.stock_line, label: `${name(l.category)} (${l.held})` }));
  const needsVoucher = kind === "issue" || kind === "return";

  async function submit(e: FormEvent) {
    e.preventDefault(); setBusy(true); setError(null);
    try {
      await api("/weapons/rounds/", { method: "POST", body: {
        personnel: person.id, stock_line: line, kind, quantity: Number(quantity),
        reference: needsVoucher ? reference : "", authority_ref: kind === "lost" ? authority : "", note,
      } });
      onDone();
    } catch (err) { setError(err); } finally { setBusy(false); }
  }

  return (
    <form onSubmit={(e) => void submit(e)}>
      <ErrorNotice error={error ?? store.error} />
      <Field label={t("hold.kind")}>
        <select value={kind} onChange={(e) => { setKind(e.target.value as Kind); setLine(""); }}>
          {KINDS.map((k) => <option key={k} value={k}>{t(`hold.kind.${k}` as Key)}</option>)}
        </select>
      </Field>
      <Field label={t("hold.ammoType")}>
        <select value={line} required onChange={(e) => setLine(e.target.value)}>
          <option value="">—</option>
          {options.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
        </select>
      </Field>
      {kind === "issue" && store.data && storeLines.length === 0 && <Notice kind="error">{t("hold.noLines")}</Notice>}
      <Field label={t("ammo.quantity")}><input type="number" min={1} step={1} required value={quantity} onChange={(e) => setQuantity(e.target.value)} /></Field>
      {needsVoucher && <Field label={t("ammo.voucher")}><input value={reference} required maxLength={60} onChange={(e) => setReference(e.target.value)} /></Field>}
      {kind === "lost" && <Field label={t("ammo.authority")}><input value={authority} required maxLength={150} onChange={(e) => setAuthority(e.target.value)} /></Field>}
      <Field label={kind === "expended" || kind === "lost" ? t("ammo.reason") : t("att.note")}>
        <input value={note} required={kind === "expended" || kind === "lost"} maxLength={300} onChange={(e) => setNote(e.target.value)} />
      </Field>
      <div className="row">
        <button type="submit" disabled={busy || !line || !quantity}>{t("hold.record")}</button>
        <button type="button" className="secondary" onClick={onCancel}>{t("common.cancel")}</button>
      </div>
    </form>
  );
}

function History({ personnelId, version }: { personnelId: string; version: number }) {
  const { t, name } = useI18n();
  const h = useFetch<{ results: Move[] }>("/weapons/rounds_history/", { personnel: personnelId, v: version });
  const rows = h.data?.results ?? [];
  return (
    <>
      <h3>{t("hold.history")}</h3>
      <ErrorNotice error={h.error} />
      {h.data && rows.length === 0 && <p className="muted">{t("hold.noHistory")}</p>}
      <ul className="list">
        {rows.map((m) => (
          <li key={m.id} className="item">
            <div className="stat"><span>{t(`hold.${m.kind === "issue" ? "issued" : m.kind === "return" ? "returned" : m.kind}` as Key)} · {name(m.category)}</span><b>{m.delta > 0 ? `+${m.delta}` : m.delta}</b></div>
            <p className="muted">
              {new Date(m.at).toLocaleString()} · {t("hold.balanceAfter")} {m.balance_after}
              {m.reference ? ` · ${t("hold.voucher")} ${m.reference}` : ""}{m.authority_ref ? ` · ${m.authority_ref}` : ""}{m.note ? ` · ${m.note}` : ""} · {m.actor}
            </p>
          </li>
        ))}
      </ul>
    </>
  );
}
