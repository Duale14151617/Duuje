import { useRef, useState, type ChangeEvent, type CSSProperties, type FormEvent } from "react";
import { api, upload, photoUrl } from "../api/client";
import { useFetch } from "../api/useFetch";
import { ErrorNotice, Field, Loading } from "./ui";
import { useI18n } from "../i18n";

interface Profile {
  blood_type: string; gender: string; weapon_id: string; date_of_birth: string | null; enlistment_date: string | null;
  home_district: string; emergency_contact_name: string; emergency_contact_phone: string;
  has_photo: boolean; photo_updated_at: string | null;
}

/** Phone photos are huge; shrink to <=1600px JPEG in the browser so uploads stay small and fast. Falls back to the original. */
async function shrink(file: File): Promise<File> {
  if (file.size < 1_000_000 && file.type === "image/jpeg") return file;
  try {
    const bmp = await createImageBitmap(file);
    const k = Math.min(1, 1600 / Math.max(bmp.width, bmp.height));
    const c = document.createElement("canvas");
    c.width = Math.round(bmp.width * k); c.height = Math.round(bmp.height * k);
    c.getContext("2d")!.drawImage(bmp, 0, 0, c.width, c.height);
    const blob = await new Promise<Blob | null>((r) => c.toBlob(r, "image/jpeg", 0.85));
    return blob ? new File([blob], "photo.jpg", { type: "image/jpeg" }) : file;
  } catch { return file; }
}

/** Name: keep letters (any script), spaces, dots, apostrophes and hyphens. Digits and other symbols are dropped as you type. */
const cleanName = (v: string) => v.replace(/[^\p{L}\s.'\u2019-]/gu, "");
/** Phone: digits only, with an optional + at the very start. */
const cleanPhone = (v: string) => { const plus = v.trimStart().startsWith("+"); return (plus ? "+" : "") + v.replace(/\D/g, "").slice(0, 15); };

/** Visually hidden but still in the layout: some mobile browsers ignore programmatic clicks on display:none file inputs. */
const HIDDEN_INPUT: CSSProperties = { position: "absolute", width: 1, height: 1, opacity: 0, overflow: "hidden", pointerEvents: "none" };

const BLOOD = ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"];

const L = {
  en: {
    title: "Identity profile", photo: "Photo", noPhoto: "No photo", upload: "Upload photo", change: "Change photo", tapAdd: "Tap to add photo", uploading: "Uploading...",
    blood: "Blood type", gender: "Sex", male: "Male", female: "Female", weapon: "Weapon ID", dob: "Date of birth",
    enlisted: "Enlistment date", district: "Home district", ecName: "Emergency contact / Guardian (name only)", ecPhone: "Emergency contact / Guardian phone (numbers only)",
    edit: "Edit profile", save: "Save", cancel: "Cancel", choose: "Choose", sensitive: "Sensitive: access is logged.",
  },
  so: {
    title: "Xogta aqoonsiga", photo: "Sawir", noPhoto: "Sawir ma jiro", upload: "Soo geli sawir", change: "Beddel sawirka", tapAdd: "Taabo si aad sawir ugu darto", uploading: "Waa la soo gelinayaa...",
    blood: "Nooca dhiigga", gender: "Jinsi", male: "Lab", female: "Dhedig", weapon: "Lambarka hubka", dob: "Taariikhda dhalashada",
    enlisted: "Taariikhda ku biiridda", district: "Degmada guriga", ecName: "Qofka degdegga ah / Masuulka (magac kaliya)", ecPhone: "Taleefanka degdegga ah / Masuulka (lambar kaliya)",
    edit: "Wax ka beddel", save: "Kaydi", cancel: "Jooji", choose: "Dooro", sensitive: "Xasaasi: marin-gelidda waa la diiwaangeliyaa.",
  },
} as const;

/** Photo + sensitive profile (blood type, weapon ID, emergency contact...). Readable/editable by personnel managers only;
 *  everyone who can view a person sees the photo. */
export function PersonnelProfile({ personId, canManage }: { personId: string; canManage: boolean }) {
  const { lang } = useI18n();
  const s = L[lang === "so" ? "so" : "en"];
  const profile = useFetch<Profile>(canManage ? `/personnel/${personId}/profile/` : null);
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState<Profile | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const [photoV, setPhotoV] = useState(0);
  const [busy, setBusy] = useState(false);
  const [broken, setBroken] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const d = profile.data;

  const set = (k: keyof Profile) => (e: ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setForm((f) => (f ? { ...f, [k]: e.target.value } : f));

  async function save(e: FormEvent) {
    e.preventDefault();
    if (!form) return;
    setBusy(true); setErr(null);
    try {
      await api(`/personnel/${personId}/profile/`, {
        method: "PATCH",
        body: {
          blood_type: form.blood_type, gender: form.gender, weapon_id: form.weapon_id,
          date_of_birth: form.date_of_birth || null, enlistment_date: form.enlistment_date || null,
          home_district: form.home_district, emergency_contact_name: form.emergency_contact_name,
          emergency_contact_phone: form.emergency_contact_phone,
        },
      });
      setEditing(false); profile.reload();
    } catch (x) { setErr(x); } finally { setBusy(false); }
  }

  async function pick(e: ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    e.target.value = "";
    if (!f) return;
    setBusy(true); setErr(null);
    try {
      await upload(`/personnel/${personId}/photo/upload/`, "photo", await shrink(f));
      setBroken(false); setPhotoV((v) => v + 1); profile.reload();
    } catch (x) { setErr(x); } finally { setBusy(false); }
  }

  const setClean = (k: "emergency_contact_name" | "emergency_contact_phone", fn: (v: string) => string) =>
    (e: ChangeEvent<HTMLInputElement>) => setForm((f) => (f ? { ...f, [k]: fn(e.target.value) } : f));

  const row = (label: string, value: string | null | undefined) => (
    <div className="stat"><span>{label}</span><b>{value || "-"}</b></div>
  );

  return (
    <section className="card" style={{ marginTop: "1rem" }}>
      <h2>{s.title}</h2>
      <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap", alignItems: "flex-start" }}>
        <div style={{ width: 120 }}>
          {(() => {
            // Managers know from the profile whether a photo exists; viewers just try to load it.
            const showImg = !broken && (canManage ? photoV > 0 || !!d?.has_photo : true);
            const box: CSSProperties = {
              width: 120, height: 150, borderRadius: 6, padding: 0, display: "flex", flexDirection: "column",
              alignItems: "center", justifyContent: "center", textAlign: "center", overflow: "hidden",
              border: "2px dashed var(--control-border, #7B8AA0)", background: "var(--surface-2, #f2f4f7)",
              color: "var(--accent-text, #1d2b4f)", fontSize: ".8rem", gap: ".25rem",
              cursor: canManage ? "pointer" : "default",
            };
            const inner = showImg ? (
              <img src={photoUrl(personId, photoV)} alt={s.photo} width={120} height={150}
                   style={{ objectFit: "cover", display: "block", width: 120, height: 150 }} onError={() => setBroken(true)} />
            ) : (
              <>
                <span style={{ fontSize: "2rem", lineHeight: 1 }} aria-hidden="true">{canManage ? "\uD83D\uDCF7" : "\uD83D\uDC64"}</span>
                <span>{canManage ? (busy ? s.uploading : s.tapAdd) : s.noPhoto}</span>
              </>
            );
            return canManage ? (
              <button type="button" aria-label={broken || !showImg ? s.upload : s.change} disabled={busy}
                      onClick={() => fileRef.current?.click()}
                      style={{ ...box, border: showImg ? "1px solid var(--control-border, #7B8AA0)" : box.border }}>
                {inner}
              </button>
            ) : (
              <div style={box}>{inner}</div>
            );
          })()}
          {canManage && (
            <>
              <button type="button" className="secondary" disabled={busy} onClick={() => fileRef.current?.click()}
                      style={{ display: "block", width: "100%", marginTop: ".5rem" }}>
                {busy ? s.uploading : broken || !(photoV > 0 || d?.has_photo) ? s.upload : s.change}
              </button>
              <input ref={fileRef} type="file" accept="image/*" onChange={pick} tabIndex={-1} aria-hidden="true" style={HIDDEN_INPUT} />
            </>
          )}
        </div>
        <div style={{ flex: 1, minWidth: 200 }}>
          {canManage && profile.loading && !d ? <Loading /> : null}
          {canManage && d && !editing && (
            <>
              {row(s.blood, d.blood_type)}
              {row(s.gender, d.gender === "male" ? s.male : d.gender === "female" ? s.female : "")}
              {row(s.weapon, d.weapon_id)}
              {row(s.dob, d.date_of_birth)}
              {row(s.enlisted, d.enlistment_date)}
              {row(s.district, d.home_district)}
              {row(s.ecName, d.emergency_contact_name)}
              {row(s.ecPhone, d.emergency_contact_phone)}
              <p className="muted small">{s.sensitive}</p>
              <button className="secondary" onClick={() => { setForm(d); setEditing(true); setErr(null); }}>{s.edit}</button>
            </>
          )}
          {canManage && d && editing && form && (
            <form onSubmit={save}>
              <Field label={s.blood}>
                <select value={form.blood_type} onChange={set("blood_type")}>
                  <option value="">{s.choose}</option>
                  {BLOOD.map((b) => <option key={b} value={b}>{b}</option>)}
                </select>
              </Field>
              <Field label={s.gender}>
                <select value={form.gender} onChange={set("gender")}>
                  <option value="">{s.choose}</option>
                  <option value="male">{s.male}</option>
                  <option value="female">{s.female}</option>
                </select>
              </Field>
              <Field label={s.weapon}><input value={form.weapon_id} maxLength={32} onChange={set("weapon_id")} /></Field>
              <Field label={s.dob}><input type="date" value={form.date_of_birth ?? ""} onChange={set("date_of_birth")} /></Field>
              <Field label={s.enlisted}><input type="date" value={form.enlistment_date ?? ""} onChange={set("enlistment_date")} /></Field>
              <Field label={s.district}><input value={form.home_district} maxLength={120} onChange={set("home_district")} /></Field>
              <Field label={s.ecName}><input value={form.emergency_contact_name} maxLength={100} autoComplete="off" onChange={setClean("emergency_contact_name", cleanName)} /></Field>
              <Field label={s.ecPhone}><input type="tel" inputMode="numeric" value={form.emergency_contact_phone} maxLength={16} autoComplete="off" placeholder="252901234567" onChange={setClean("emergency_contact_phone", cleanPhone)} /></Field>
              <div className="row">
                <button type="submit" disabled={busy}>{s.save}</button>
                <button type="button" className="secondary" onClick={() => setEditing(false)}>{s.cancel}</button>
              </div>
            </form>
          )}
          <ErrorNotice error={err ?? (canManage ? profile.error : null)} />
        </div>
      </div>
    </section>
  );
}
