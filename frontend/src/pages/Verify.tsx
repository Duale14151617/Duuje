import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { brand, emblemName } from "../lib/brand";
import { useI18n } from "../i18n";
import { useDocumentTitle } from "../lib/pageTitles";

interface Result {
  state: "valid" | "revoked" | "expired" | "not_serving"; kind: "id_card" | "letter"; reference: string; issued_on: string;
  full_name?: string; service_number?: string; rank_en?: string; rank_so?: string; unit_en?: string; unit_so?: string; expires_on?: string | null;
  subject?: string; recipient?: string; signed_by?: string; signed_title?: string; fingerprint?: string;
}

const L = {
  en: {
    title: "Document check", checking: "Checking...", valid: "GENUINE", revoked: "NOT VALID: this document has been revoked", expired: "NOT VALID: this document has expired",
    not_serving: "NOT VALID: the holder is no longer serving", unknown: "NOT FOUND: this code does not match any document issued by this system. Treat the document as fake.",
    offline: "Could not reach the server. Check your connection and scan again.", idCard: "Officer identity card", letter: "Official letter", name: "Name", number: "Service no. (partly hidden)",
    rank: "Rank", unit: "Unit", valid_until: "Valid until", ref: "Reference", issued: "Issued", subject: "Subject", to: "To", signed: "Signed by", fingerprint: "Text fingerprint",
    compare: "Compare the name and rank with the card in hand and with the person. A letter must show the same fingerprint at its foot.",
  },
  so: {
    title: "Hubinta dukumeentiga", checking: "Waa la hubinayaa...", valid: "RUN AH", revoked: "MA ANSAXA: dukumeentigan waa la burburiyay", expired: "MA ANSAXA: dukumeentigan wuu dhacay",
    not_serving: "MA ANSAXA: qofka haysta ma shaqeeyo hadda", unknown: "LAMA HELIN: koodhkan kuma jiro dukumeenti uu nidaamkan soo saaray. U qaado mid been ah.",
    offline: "Server lama gaari karo. Hubi xiriirkaaga oo mar kale iskaan garee.", idCard: "Kaarka aqoonsiga sarkaalka", letter: "Warqad rasmi ah", name: "Magac", number: "Lambarka shaqada (qayb la qariyay)",
    rank: "Darajo", unit: "Cutub", valid_until: "Ansax ilaa", ref: "Tixraac", issued: "La soo saaray", subject: "Mawduuc", to: "Loogu talagalay", signed: "Saxiixay", fingerprint: "Faraha qoraalka",
    compare: "La barbardhig magaca iyo darajada kaarka gacanta ku jira iyo qofka. Warqaddu waa inay muujisaa isla faraha qoraalka ee hoose.",
  },
} as const;

/** Public page opened by scanning the QR code. No sign-in; shows only what the server allows anyone to see. */
export function Verify() {
  const { code } = useParams();
  const { t, lang, setLang } = useI18n();
  const s = L[lang === "so" ? "so" : "en"];
  useDocumentTitle(s.title, t("app.name"));
  const [res, setRes] = useState<Result | null>(null);
  const [problem, setProblem] = useState<"" | "unknown" | "offline">("");

  useEffect(() => {
    let live = true;
    fetch(`/api/v1/verify/${encodeURIComponent(code ?? "")}/`, { headers: { Accept: "application/json" } })
      .then(async (r) => {
        if (!live) return;
        if (r.status === 404) { setProblem("unknown"); return; }
        if (!r.ok) { setProblem("offline"); return; }
        setRes((await r.json()) as Result);
      })
      .catch(() => { if (live) setProblem("offline"); });
    return () => { live = false; };
  }, [code]);

  const ok = res?.state === "valid";
  const pick = (en?: string, so?: string): string => (lang === "so" && so ? so : en ?? "");
  const banner = problem === "unknown" ? s.unknown : problem === "offline" ? s.offline : res ? s[res.state] : s.checking;
  const bad = problem === "unknown" || (res !== null && !ok);
  return (
    <main style={{ maxWidth: 520, margin: "0 auto", padding: "1rem" }}>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <div className="row"><img src={brand.primary.img} alt="" width={40} height={40} /><b>{emblemName(brand.primary, lang)}</b></div>
        <button type="button" className="secondary sm" onClick={() => setLang(lang === "so" ? "en" : "so")}>{lang === "so" ? "English" : "Soomaali"}</button>
      </div>
      <h1>{s.title}</h1>
      <div className={`notice ${ok ? "info" : bad ? "error" : "info"}`} role="status" style={{ fontWeight: 700, fontSize: "1.1rem" }}>{ok ? `✔ ${s.valid}` : banner}</div>
      {res && ok && (
        <section className="card">
          <p className="muted">{res.kind === "id_card" ? s.idCard : s.letter}</p>
          <dl className="kv">
            {res.kind === "id_card" ? (
              <>
                <div><dt>{s.name}</dt><dd><b>{res.full_name}</b></dd></div>
                <div><dt>{s.rank}</dt><dd>{pick(res.rank_en, res.rank_so)}</dd></div>
                <div><dt>{s.number}</dt><dd>{res.service_number || "-"}</dd></div>
                <div><dt>{s.unit}</dt><dd>{pick(res.unit_en, res.unit_so)}</dd></div>
                <div><dt>{s.valid_until}</dt><dd>{res.expires_on ?? "-"}</dd></div>
              </>
            ) : (
              <>
                <div><dt>{s.subject}</dt><dd><b>{res.subject}</b></dd></div>
                {res.recipient && <div><dt>{s.to}</dt><dd>{res.recipient}</dd></div>}
                <div><dt>{s.signed}</dt><dd>{res.signed_by}{res.signed_title ? `, ${res.signed_title}` : ""}</dd></div>
                <div><dt>{s.unit}</dt><dd>{pick(res.unit_en, res.unit_so)}</dd></div>
                <div><dt>{s.fingerprint}</dt><dd><code>{res.fingerprint}</code></dd></div>
              </>
            )}
            <div><dt>{s.ref}</dt><dd><code>{res.reference}</code></dd></div>
            <div><dt>{s.issued}</dt><dd>{res.issued_on}</dd></div>
          </dl>
          <p className="muted">{s.compare}</p>
        </section>
      )}
      {res && !ok && <p className="muted">{s.ref}: <code>{res.reference}</code></p>}
    </main>
  );
}
