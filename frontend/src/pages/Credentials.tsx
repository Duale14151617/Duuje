import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { useFetch } from "../api/useFetch";
import { useAuth } from "../auth/AuthContext";
import type { CredentialDoc } from "../components/CredentialSheet";
import { Chip, ErrorNotice, Field, Loading, PageHeader } from "../components/ui";
import { UnitPicker } from "../components/UnitPicker";
import { useI18n } from "../i18n";

interface Row { id: string; kind: "id_card" | "letter"; reference: string; state: string; title: string | null; issued_at: string; expires_on: string | null; unit: { id: string; name_en: string; name_so: string } }

const L = {
  en: {
    title: "ID cards and letters", subtitle: "Printable officer ID cards and official letters. Each carries a QR code that anyone can scan to check it is genuine.",
    newLetter: "New official letter", unit: "Issuing unit", recipient: "To (optional)", subject: "Subject", text: "Letter text", signTitle: "Your title (optional)",
    create: "Create letter", busy: "Creating...", issued: "Issued documents", none: "Nothing issued yet. ID cards are issued from a person's record.",
    kind: "Type", card: "ID card", letter: "Letter", ref: "Reference", what: "Name / subject", date: "Issued", status: "Status", open: "Open", all: "All",
    valid: "Valid", revoked: "Revoked", expired: "Expired", not_serving: "No longer serving",
    note: "The letter text is fixed when it is issued. To change it, issue a new letter and revoke the old one.",
  },
  so: {
    title: "Kaararka aqoonsiga iyo warqadaha", subtitle: "Kaararka aqoonsiga sarkaalka iyo warqadaha rasmiga ah ee la daabaci karo. Mid walba waxaa ku jira QR qof walba ku hubin karo inuu run yahay.",
    newLetter: "Warqad rasmi ah oo cusub", unit: "Cutubka soo saaray", recipient: "Loogu talagalay (ikhtiyaari)", subject: "Mawduuc", text: "Qoraalka warqadda", signTitle: "Magacaaga shaqo (ikhtiyaari)",
    create: "Samee warqadda", busy: "Waa la sameynayaa...", issued: "Dukumeentiyada la soo saaray", none: "Weli waxba lama soo saarin. Kaararka waxaa laga soo saaraa diiwaanka qofka.",
    kind: "Nooc", card: "Kaarka aqoonsiga", letter: "Warqad", ref: "Tixraac", what: "Magac / mawduuc", date: "La soo saaray", status: "Xaalad", open: "Fur", all: "Dhammaan",
    valid: "Ansax", revoked: "La burburiyay", expired: "Wuu dhacay", not_serving: "Ma shaqeyso hadda",
    note: "Qoraalka warqadda wuu go'aa marka la soo saaro. Si aad u beddesho, samee warqad cusub oo burburi tii hore.",
  },
} as const;

const tone = (state: string): string => (state === "valid" ? "ok" : state === "expired" ? "warn" : "bad");

export function Credentials() {
  const { lang } = useI18n();
  const s = L[lang === "so" ? "so" : "en"];
  const { can } = useAuth();
  const navigate = useNavigate();
  const [kind, setKind] = useState("");
  const list = useFetch<{ results: Row[] }>("/credentials/", { kind: kind || undefined });
  const [unit, setUnit] = useState("");
  const [recipient, setRecipient] = useState("");
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [signTitle, setSignTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const stateLabel = (st: string): string => (st === "valid" ? s.valid : st === "revoked" ? s.revoked : st === "expired" ? s.expired : s.not_serving);

  async function create(e: FormEvent) {
    e.preventDefault();
    setBusy(true); setErr(null);
    try {
      const d = await api<CredentialDoc>("/credentials/letter/", { method: "POST", body: { org_unit: unit, recipient, subject, body, signed_title: signTitle } });
      navigate(`/credentials/${d.id}`);
    } catch (x) { setErr(x); } finally { setBusy(false); }
  }

  return (
    <>
      <PageHeader title={s.title} subtitle={s.subtitle} />
      {can("credentials.issue") && (
        <section className="card">
          <h2>{s.newLetter}</h2>
          <form onSubmit={(e) => void create(e)}>
            <UnitPicker label={s.unit} value={unit} onChange={(id) => setUnit(id)} required />
            <Field label={s.recipient}><input value={recipient} maxLength={200} onChange={(e) => setRecipient(e.target.value)} /></Field>
            <Field label={s.subject}><input value={subject} maxLength={200} required onChange={(e) => setSubject(e.target.value)} /></Field>
            <Field label={s.text}><textarea value={body} maxLength={8000} rows={10} required onChange={(e) => setBody(e.target.value)} /></Field>
            <Field label={s.signTitle}><input value={signTitle} maxLength={120} onChange={(e) => setSignTitle(e.target.value)} /></Field>
            <p className="muted">{s.note}</p>
            <ErrorNotice error={err} />
            <button type="submit" disabled={busy || !unit}>{busy ? s.busy : s.create}</button>
          </form>
        </section>
      )}
      <section className="card">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <h2 className="flush">{s.issued}</h2>
          <label className="field" style={{ margin: 0 }}>
            <span className="sr-only">{s.kind}</span>
            <select value={kind} onChange={(e) => setKind(e.target.value)} aria-label={s.kind}>
              <option value="">{s.all}</option><option value="id_card">{s.card}</option><option value="letter">{s.letter}</option>
            </select>
          </label>
        </div>
        <ErrorNotice error={list.error} />
        {list.loading && !list.data ? <Loading /> : (list.data?.results.length ?? 0) === 0 ? <p className="muted">{s.none}</p> : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>{s.kind}</th><th>{s.what}</th><th>{s.ref}</th><th>{s.date}</th><th>{s.status}</th><th /></tr></thead>
              <tbody>
                {list.data?.results.map((r) => (
                  <tr key={r.id}>
                    <td>{r.kind === "id_card" ? s.card : s.letter}</td>
                    <td>{r.title}</td>
                    <td><code>{r.reference}</code></td>
                    <td>{r.issued_at.slice(0, 10)}</td>
                    <td><Chip tone={tone(r.state)}>{stateLabel(r.state)}</Chip></td>
                    <td><Link to={`/credentials/${r.id}`}>{s.open}</Link></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  );
}
