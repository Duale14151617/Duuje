import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError, api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { useI18n } from "../i18n";
import type { CredentialDoc } from "./CredentialSheet";
import { ErrorNotice, Notice } from "./ui";

const L = {
  en: { title: "Identity card", issue: "Issue ID card", busy: "Issuing...", help: "Creates a printable card with the photo and a QR code. A new card replaces any earlier one.",
        needPhoto: "Add a profile photo first (Identity profile above), then issue the card.", confirm: "Issue a new ID card? Any earlier card for this person stops being valid." },
  so: { title: "Kaarka aqoonsiga", issue: "Samee kaarka aqoonsiga", busy: "Waa la sameynayaa...", help: "Waxay abuurtaa kaar la daabaci karo oo leh sawirka iyo QR. Kaarka cusub wuxuu beddelaa kii hore.",
        needPhoto: "Marka hore sawir ku dar (Xogta aqoonsiga), kadibna samee kaarka.", confirm: "Samee kaar cusub? Kaarkii hore ee qofkan wuu joojoonayaa." },
} as const;

/** On a person's record: issue a printable ID card (photo + QR) and open it. Shown only to people who may issue cards. */
export function IdCardButton({ personId }: { personId: string }) {
  const { can } = useAuth();
  const { lang } = useI18n();
  const s = L[lang === "so" ? "so" : "en"];
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  if (!can("credentials.issue")) return null;

  async function issue() {
    if (!window.confirm(s.confirm)) return;
    setBusy(true); setErr(null);
    try {
      const d = await api<CredentialDoc>("/credentials/id-card/", { method: "POST", body: { personnel: personId } });
      navigate(`/credentials/${d.id}`);
    } catch (e) { setErr(e); } finally { setBusy(false); }
  }

  return (
    <section className="card">
      <h2>{s.title}</h2>
      <p className="muted">{s.help}</p>
      {err instanceof ApiError && err.fieldCode === "photo_required" ? <Notice kind="warn">{s.needPhoto}</Notice> : <ErrorNotice error={err} />}
      <button type="button" disabled={busy} onClick={() => void issue()}>{busy ? s.busy : s.issue}</button>
    </section>
  );
}
