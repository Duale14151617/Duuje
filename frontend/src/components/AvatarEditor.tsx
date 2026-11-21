import { useRef, useState, type ChangeEvent, type CSSProperties } from "react";
import { api, upload } from "../api/client";
import { useI18n } from "../i18n";
import { shrink } from "./PersonnelProfile";
import { ErrorNotice } from "./ui";

/** Visually hidden but still in the layout: some mobile browsers ignore programmatic clicks on display:none file inputs. */
const HIDDEN_INPUT: CSSProperties = { position: "absolute", width: 1, height: 1, opacity: 0, overflow: "hidden", pointerEvents: "none" };

/** Set or remove the profile picture of one login account (own or someone else's; the server decides who may).
 *  `onChanged` runs after a successful change so the caller can refresh what it shows. */
export function AvatarEditor({ userId, onChanged }: { userId: string; onChanged?: () => void }) {
  const { t } = useI18n();
  const [tick, setTick] = useState(0);        // bumps after each change so the preview refetches
  const [failed, setFailed] = useState(false); // true once the picture request fails (404 = none set): show the default
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  async function run(work: () => Promise<unknown>) {
    setBusy(true); setErr(null);
    try { await work(); setFailed(false); setTick((n) => n + 1); onChanged?.(); } catch (x) { setErr(x); } finally { setBusy(false); }
  }
  const pick = (e: ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    e.target.value = "";
    if (f) void run(async () => upload(`/users/${userId}/avatar/upload/`, "photo", await shrink(f)));
  };
  const remove = () => run(async () => { await api(`/users/${userId}/avatar/remove/`, { method: "POST" }); setFailed(true); });

  const src = failed ? "/avatar-default.png" : `/api/v1/users/${userId}/avatar/?t=${tick}`;
  return (
    <div>
      <ErrorNotice error={err} />
      <div style={{ display: "flex", alignItems: "center", gap: "1rem", flexWrap: "wrap" }}>
        <img className="avatar" src={src} alt="" width={72} height={72} onError={() => setFailed(true)} />
        <div className="row">
          <input ref={fileRef} type="file" accept="image/jpeg,image/png,image/webp" style={HIDDEN_INPUT} onChange={pick} tabIndex={-1} />
          <button type="button" className="secondary" disabled={busy} onClick={() => fileRef.current?.click()}>
            {busy ? t("avatar.uploading") : failed ? t("avatar.upload") : t("avatar.change")}
          </button>
          {!failed && <button type="button" className="secondary" disabled={busy} onClick={() => void remove()}>{t("avatar.remove")}</button>}
        </div>
      </div>
      <p className="muted" style={{ marginBottom: 0 }}>{t("avatar.hint")}</p>
    </div>
  );
}
