import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import { useFetch } from "../api/useFetch";
import { useAuth } from "../auth/AuthContext";
import { IdCardSheet, LetterSheet, type CredentialDoc } from "../components/CredentialSheet";
import { ErrorNotice, Field, Loading, PageHeader } from "../components/ui";
import { useI18n } from "../i18n";

const L = {
  en: { back: "All documents", print: "Print", revoke: "Revoke", reason: "Reason for revoking", confirm: "Revoke this document? Anyone scanning it will be told it is no longer valid.",
        revoked: "This document was revoked", tip: "Print on card stock (ID card, 85.6 x 54 mm) or A4 (letter). In the print dialog you can also save as PDF.", card: "ID card", letter: "Official letter" },
  so: { back: "Dukumeentiyada oo dhan", print: "Daabac", revoke: "Burburi", reason: "Sababta loo burburinayo", confirm: "Burburi dukumeentigan? Qof kasta oo iskaan gareeya waxaa la sheegi doonaa inuusan sii ansaxeyn.",
        revoked: "Dukumeentigan waa la burburiyay", tip: "Ku daabac warqad adag (kaarka, 85.6 x 54 mm) ama A4 (warqadda). Daabacaadda gudaheeda waxaad kaydin kartaa PDF.", card: "Kaarka aqoonsiga", letter: "Warqad rasmi ah" },
} as const;

/** One issued document, ready to print. Revoking is here too (it keeps the record and tells anyone who scans it). */
export function CredentialView() {
  const { id } = useParams();
  const { lang } = useI18n();
  const s = L[lang === "so" ? "so" : "en"];
  const { can } = useAuth();
  const d = useFetch<CredentialDoc>(id ? `/credentials/${id}/` : null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const doc = d.data;

  async function revoke() {
    if (!doc || !window.confirm(s.confirm)) return;
    setBusy(true); setErr(null);
    try { await api(`/credentials/${doc.id}/revoke/`, { method: "POST", body: { reason } }); setReason(""); d.reload(); }
    catch (e) { setErr(e); } finally { setBusy(false); }
  }

  return (
    <>
      <div className="no-print">
        <PageHeader title={doc ? (doc.kind === "id_card" ? s.card : s.letter) : "…"} subtitle={doc?.reference}
                    actions={<><Link className="btn secondary" to="/credentials">{s.back}</Link><button type="button" onClick={() => window.print()}>{s.print}</button></>} />
        <ErrorNotice error={d.error} />
        {doc && <p className="muted">{s.tip}</p>}
        {doc?.status === "revoked" && <p role="status"><b>{s.revoked}:</b> {doc.revoked_reason}</p>}
      </div>
      {d.loading && !doc ? <Loading /> : null}
      {doc && <div className="print-area">{doc.kind === "id_card" ? <IdCardSheet doc={doc} /> : <LetterSheet doc={doc} />}</div>}
      {doc && doc.status === "valid" && can("credentials.issue") && (
        <section className="card no-print">
          <Field label={s.reason}><input value={reason} maxLength={300} onChange={(e) => setReason(e.target.value)} /></Field>
          <ErrorNotice error={err} />
          <button type="button" className="secondary" disabled={busy || !reason.trim()} onClick={() => void revoke()}>{s.revoke}</button>
        </section>
      )}
    </>
  );
}
