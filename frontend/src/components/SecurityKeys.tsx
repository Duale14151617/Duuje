import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { useI18n } from "../i18n";
import { createPasskey, passkeysSupported, wasCancelled } from "../lib/webauthn";
import { formatDateTime } from "../lib/format";
import { BackupCodesPanel } from "./BackupCodesPanel";
import { ErrorNotice, Notice } from "./ui";

interface Passkey { id: string; name: string; created_at: string; last_used_at: string | null }

/** Account page: the backup codes and passkeys that sit beside the authenticator app. Only shown when the authenticator is on. */
export function SecurityKeys() {
  const { me, reload } = useAuth();
  const { t, lang } = useI18n();
  const [keys, setKeys] = useState<Passkey[]>([]);
  const [name, setName] = useState("");
  const [codes, setCodes] = useState<string[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [note, setNote] = useState("");
  const load = useCallback(() => {
    api<{ results: Passkey[] }>("/auth/passkeys/").then((r) => setKeys(r.results)).catch(() => undefined);
  }, []);
  useEffect(() => { if (me?.mfa_enabled) load(); }, [me?.mfa_enabled, load]);
  if (!me?.mfa_enabled) return null;

  const left = me.backup_codes_remaining ?? 0;

  async function run(work: () => Promise<void>) {
    setBusy(true); setError(null); setNote("");
    try { await work(); } catch (err) { if (!wasCancelled(err)) setError(err); } finally { setBusy(false); }
  }

  const regenerate = () => run(async () => {
    if (left > 0 && !window.confirm(t("backup.confirmNew"))) return;
    const r = await api<{ backup_codes: string[] }>("/auth/mfa/backup-codes/", { method: "POST" });
    setCodes(r.backup_codes);
    await reload();
  });

  const add = () => run(async () => {
    const opts = await api<{ challenge_id: string; options: Record<string, unknown> }>("/auth/passkeys/register/options/", { method: "POST" });
    const credential = await createPasskey(opts.options);
    await api("/auth/passkeys/register/verify/", { method: "POST", body: { challenge_id: opts.challenge_id, credential, name: name.trim() || t("passkey.defaultName") } });
    setName(""); setNote(t("passkey.added"));
    load(); await reload();
  });

  const remove = (k: Passkey) => run(async () => {
    if (!window.confirm(t("passkey.confirmRemove", { name: k.name }))) return;
    await api(`/auth/passkeys/${k.id}/`, { method: "DELETE" });
    load(); await reload();
  });

  return (
    <>
      <section className="card">
        <h2>{t("backup.heading")}</h2>
        <p className={left <= 2 ? "notice warn" : "muted"}>{t("backup.remaining", { n: left })}{left <= 2 ? ` ${t("backup.low")}` : ""}</p>
        {codes
          ? <BackupCodesPanel codes={codes} onDone={() => setCodes(null)} />
          : <button type="button" className="secondary" disabled={busy} onClick={() => void regenerate()}>{t(left > 0 ? "backup.regenerate" : "backup.generate")}</button>}
      </section>
      <section className="card">
        <h2>{t("passkey.heading")}</h2>
        <p className="muted">{t("passkey.intro")}</p>
        {!passkeysSupported() && <Notice kind="warn">{t("passkey.unsupported")}</Notice>}
        {keys.length === 0 ? <p className="muted">{t("passkey.none")}</p> : (
          <ul className="list passkey-list">
            {keys.map((k) => (
              <li key={k.id} className="row" style={{ justifyContent: "space-between", gap: ".75rem", alignItems: "center" }}>
                <span><b>{k.name}</b><br /><small className="muted">{t("passkey.added1", { date: formatDateTime(k.created_at, lang) })}
                  {k.last_used_at ? ` · ${t("passkey.lastUsed", { date: formatDateTime(k.last_used_at, lang) })}` : ""}</small></span>
                <button type="button" className="secondary" disabled={busy} onClick={() => void remove(k)}>{t("passkey.remove")}</button>
              </li>
            ))}
          </ul>
        )}
        {passkeysSupported() && (
          <div className="row" style={{ gap: ".5rem", flexWrap: "wrap", marginTop: ".5rem" }}>
            <input value={name} maxLength={60} placeholder={t("passkey.namePlaceholder")} aria-label={t("passkey.namePlaceholder")} onChange={(e) => setName(e.target.value)} />
            <button type="button" disabled={busy} onClick={() => void add()}>{t("passkey.add")}</button>
          </div>
        )}
        {note ? <Notice kind="info">{note}</Notice> : null}
        <ErrorNotice error={error} />
      </section>
    </>
  );
}
