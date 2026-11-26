import { photoUrl } from "../api/client";
import { brand, emblemName } from "../lib/brand";
import { useI18n } from "../i18n";

export interface CredentialDoc {
  id: string; kind: "id_card" | "letter"; code: string; reference: string; state: string; status: string;
  personnel_id: string | null; org_unit: { id: string; name_en: string; name_so: string };
  subject: string; recipient: string; body: string; snapshot: Record<string, string>;
  issued_at: string; issued_by: string; expires_on: string | null; revoked_at: string | null; revoked_reason: string;
  verify_url: string; qr: string; fingerprint: string | null;
}

const T = {
  en: {
    card: "OFFICER IDENTITY CARD", name: "Name", rank: "Rank", number: "Service no.", unit: "Unit", valid: "Valid until",
    scan: "Scan to verify this card", code: "Code", found: "If found, return to the nearest military unit.", sign: "Holder's signature",
    qrAlt: "QR code to verify this document", ref: "Ref", date: "Date", to: "To", verifyAt: "Verify this letter at", fingerprint: "Text fingerprint",
    revoked: "REVOKED", expired: "EXPIRED", not_serving: "NO LONGER SERVING",
  },
  so: {
    card: "KAARKA AQOONSIGA SARKAALKA", name: "Magac", rank: "Darajo", number: "Lambarka shaqada", unit: "Cutub", valid: "Ansax ilaa",
    scan: "Sawir ka qaad si aad u hubiso kaarkan", code: "Koodh", found: "Haddii la helo, la geeyo cutubka ciidanka ugu dhow.", sign: "Saxiixa qofka haysta",
    qrAlt: "QR si loo hubiyo dukumeentigan", ref: "Tixraac", date: "Taariikh", to: "Loogu talagalay", verifyAt: "Warqaddan ka hubi", fingerprint: "Faraha qoraalka",
    revoked: "LA BURBURIYAY", expired: "WAA DHACAY", not_serving: "MA SHAQEYSO HADDA",
  },
} as const;

type Strings = (typeof T)["en"] | (typeof T)["so"];
const voidText = (s: Strings, state: string): string => (state === "revoked" ? s.revoked : state === "expired" ? s.expired : state === "not_serving" ? s.not_serving : "");

/** Two ID-card faces (CR80 size, 85.6 x 54 mm) laid out for printing. The photo is loaded with the signed-in user's session. */
export function IdCardSheet({ doc }: { doc: CredentialDoc }) {
  const { lang } = useI18n();
  const s: Strings = T[lang === "so" ? "so" : "en"];
  const snap = doc.snapshot;
  const pick = (en: string, so: string): string => (lang === "so" && snap[so] ? snap[so] : snap[en] ?? "");
  const mark = voidText(s, doc.state);
  return (
    <div className="idsheet">
      <div className="idcard idfront">
        {mark && <div className="idvoid">{mark}</div>}
        <div className="idhead">
          <img src={brand.primary.img} alt="" />
          <div><b>{emblemName(brand.primary, lang)}</b><span>{s.card}</span></div>
        </div>
        <div className="idbody">
          {doc.personnel_id ? <img className="idphoto" src={photoUrl(doc.personnel_id, 0)} alt="" /> : <div className="idphoto" />}
          <dl>
            <div><dt>{s.name}</dt><dd className="idname">{snap.full_name}</dd></div>
            <div><dt>{s.rank}</dt><dd>{pick("rank_en", "rank_so")}</dd></div>
            <div><dt>{s.number}</dt><dd>{snap.service_number || "-"}</dd></div>
            <div><dt>{s.unit}</dt><dd>{pick("unit_en", "unit_so")}</dd></div>
            <div><dt>{s.valid}</dt><dd>{doc.expires_on ?? "-"}</dd></div>
          </dl>
        </div>
        <div className="idfoot">{doc.reference}</div>
      </div>
      <div className="idcard idback">
        {mark && <div className="idvoid">{mark}</div>}
        <div className="idqr">
          {doc.qr ? <img src={doc.qr} alt={s.qrAlt} /> : null}
          <div><b>{s.scan}</b><span>{s.code}: <code>{doc.code}</code></span><span className="idurl">{doc.verify_url}</span></div>
        </div>
        <p className="idfound">{s.found}</p>
        <div className="idsign"><span /><small>{s.sign}</small></div>
      </div>
    </div>
  );
}

/** An official letter on letterhead with a QR code and a fingerprint of its text, for printing on A4. */
export function LetterSheet({ doc }: { doc: CredentialDoc }) {
  const { lang } = useI18n();
  const s: Strings = T[lang === "so" ? "so" : "en"];
  const snap = doc.snapshot;
  const unit = lang === "so" && snap.unit_so ? snap.unit_so : snap.unit_en;
  const mark = voidText(s, doc.state);
  return (
    <article className="letter">
      {mark && <div className="idvoid">{mark}</div>}
      <header className="lt-head">
        <img src={brand.primary.img} alt="" />
        <div><b>{emblemName(brand.primary, lang)}</b><span>{unit}</span></div>
      </header>
      <div className="lt-meta"><span>{s.ref}: {doc.reference}</span><span>{s.date}: {doc.issued_at.slice(0, 10)}</span></div>
      {doc.recipient && <p className="lt-to">{s.to}: {doc.recipient}</p>}
      <h2 className="lt-subject">{doc.subject}</h2>
      <div className="lt-body">{doc.body}</div>
      <div className="lt-sign"><div className="lt-line" /><b>{snap.signed_by}</b>{snap.signed_title && <span>{snap.signed_title}</span>}</div>
      <footer className="lt-verify">
        {doc.qr ? <img src={doc.qr} alt={s.qrAlt} /> : null}
        <div>
          <span>{s.verifyAt}</span><span className="idurl">{doc.verify_url}</span>
          <span>{s.code}: <code>{doc.code}</code> · {s.fingerprint}: <code>{doc.fingerprint}</code></span>
        </div>
      </footer>
    </article>
  );
}
