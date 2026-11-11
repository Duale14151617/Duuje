import { ReactNode, createContext, useContext, useState } from "react";

// Lightweight English / Somali switch. The English text itself is the key, so a string that has no Somali entry
// simply stays in English and nothing breaks. Somali wording should be reviewed by a native speaker before launch.
export type Lang = "en" | "so";

const SO: Record<string, string> = {
  // navigation and shell
  "Dashboard": "Bogga hore", "Notifications": "Ogeysiisyada", "Security": "Amniga", "Platform admin": "Maamulka madasha",
  "My technician profile": "Xogtayda farsamoyaqaanka", "Become a technician": "Noqo farsamoyaqaan",
  "Home": "Hoyga", "Alerts": "Digniino", "Technician": "Farsamoyaqaan", "Admin": "Maamul",
  "Sign out": "Ka bax", "Dark mode": "Habka mugdiga", "Light mode": "Habka iftiinka",
  "Sign out?": "Ka bixid?", "Are you sure you want to sign out? This signs you out on every device.": "Ma hubtaa inaad ka bixayso? Waxay kaa saaraysaa aaladaha oo dhan.",
  "Cancel": "Jooji", "Yes, sign out": "Haa, ka bax", "Signing you out…": "Waan ku saaraynaa…", "See you soon.": "Si dhawaan ah ayaan kuu arki doonnaa.",
  // auth
  "Welcome back": "Ku soo dhawow mar kale", "Create your account": "Samee akoonkaaga", "Two-step check": "Hubinta labada tallaabo",
  "Email": "Iimayl", "Password": "Erayga sirta ah", "Name": "Magac", "Full name": "Magaca oo dhan", "Phone": "Taleefan",
  "Sign in": "Gal", "Register": "Isdiiwaangeli", "Have an account?": "Akoon ma leedahay?", "Create account": "Samee akoon", "Verify": "Xaqiiji",
  "Forgot your password?": "Ma illowday erayga sirta ah?", "At least 12 characters.": "Ugu yaraan 12 xaraf.",
  "I'm a company": "Waxaan ahay shirkad", "I'm a technician": "Waxaan ahay farsamoyaqaan",
  // technician area
  "Profile": "Xogtayda", "Jobs": "Shaqooyin", "Availability": "Waqtiga la heli karo", "Earnings": "Dakhliga",
  "Register as a technician": "Isdiiwaangeli farsamoyaqaan", "Create technician profile": "Samee xogta farsamoyaqaanka",
  "Your details": "Xogtaada", "Save details": "Kaydi xogta", "Saved.": "Waa la kaydiyay.",
  "Skills": "Xirfado", "Save skills": "Kaydi xirfadaha", "Skills saved.": "Xirfadaha waa la kaydiyay.",
  "Service areas": "Meelaha shaqada", "Save service areas": "Kaydi meelaha shaqada", "Service areas saved.": "Meelaha shaqada waa la kaydiyay.",
  "Documents": "Dukumiintiyada", "Upload": "Soo geli", "Uploading…": "Waa la soo gelinayaa…", "Type": "Nooca", "File": "Faylka", "Status": "Xaalad",
  "Identity": "Aqoonsi", "Qualification": "Shahaado", "Other": "Kale",
  "Companies": "Shirkadaha", "Accept": "Aqbal", "Decline": "Diid", "Company": "Shirkad",
  "Profile progress": "Horumarka xogta", "Name and phone added": "Magac iyo taleefan waa la geliyay", "Skills chosen": "Xirfadaha waa la doortay",
  "Service areas chosen": "Meelaha shaqada waa la doortay", "ID document uploaded": "Dukumiinti aqoonsi waa la soo geliyay",
  "Your profile is complete. Companies can now invite you.": "Xogtaadu waa dhammaystiran tahay. Shirkaduhu hadda way ku martiqaadi karaan.",
  // jobs
  "No jobs yet. Companies you work with will offer jobs here.": "Weli shaqo ma jirto. Shirkadaha aad la shaqeyso halkan ayay shaqo kugu soo bandhigi doonaan.",
  "Open job": "Fur shaqada", "Back to jobs": "Ku noqo shaqooyinka", "Customer": "Macmiil", "Access": "Gelitaan",
  "I'm on my way": "Waan imaanayaa", "I've arrived": "Waan imid", "Start work": "Bilow shaqada", "Resume work": "Sii wad shaqada",
  "Evidence": "Cadeymo", "Add photo or PDF": "Ku dar sawir ama PDF", "Scope change (optional)": "Isbeddel xadka shaqada (ikhtiyaar)",
  "Report scope change": "Ka warbixi isbeddelka xadka shaqada", "Work report": "Warbixinta shaqada", "What did you do?": "Maxaad qabatay?",
  "Hours worked (optional)": "Saacadaha la shaqeeyay (ikhtiyaar)", "Submit for review": "U gudbi dib-u-eegis",
  "Reason (optional)": "Sabab (ikhtiyaar)", "Decline this job?": "Ma diidaysaa shaqadan?",
  // availability and earnings
  "Add the times you can work. Companies only see you for jobs inside these windows.": "Ku dar waqtiyada aad shaqayn karto. Shirkaduhu kaliya waxay kuu soo bandhigaan shaqooyin ku jira waqtiyadan.",
  "Available from": "La heli karaa laga bilaabo", "Available until": "La heli karaa ilaa", "Add window": "Ku dar waqti", "Remove": "Ka saar",
  "No payments yet. They appear after your work is approved.": "Weli lacag ma jirto. Waxay soo muuqdaan ka dib marka shaqadaada la oggolaado.",
  "I received money": "Lacag baan helay", "Report a problem": "Ka warbixi dhibaato",
  // company side
  "Invite a technician": "U yeer farsamoyaqaan", "Invite": "Martiqaad", "Technician email": "Iimaylka farsamoyaqaanka", "Copy link": "Koobi linkiga", "Copied": "Waa la koobiyay",
  "Import technicians from CSV": "Ka soo dhoofi farsamoyaqaanno CSV", "Import": "Soo dhoofi",
  // language
  "Language": "Luqad", "Verification": "Xaqiijin", "Verified": "La xaqiijiyay", "Not verified": "Aan la xaqiijin", "Send code": "Dir koodhka", "Use a different email": "Isticmaal iimayl kale", "Email address": "Ciwaanka iimaylka", "Change address": "Beddel ciwaanka", "Current password": "Erayga sirta ah ee hadda", "Code": "Koodh", "Confirm": "Xaqiiji", "Ratings": "Qiimeynaha",
  "Add a phone number above to verify it.": "Ku dar lambar taleefan kor ka xaqiiji.", "Job history": "Taariikhda shaqooyinka",
  "At least one skill verified (needed before companies can invite you)": "Ugu yaraan hal xirfad oo la xaqiijiyay (loo baahan yahay ka hor intaan shirkaduhu ku martiqaadin)",
};

type Ctx = { lang: Lang; setLang: (l: Lang) => void; t: (s: string, vars?: Record<string, string | number>) => string };
const I18nContext = createContext<Ctx>({ lang: "en", setLang: () => {}, t: (s) => s });

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(() => { try { return localStorage.getItem("lang") === "so" ? "so" : "en"; } catch { return "en"; } });
  const setLang = (l: Lang) => {
    setLangState(l);
    document.documentElement.lang = l;
    try { localStorage.setItem("lang", l); } catch { /* private mode */ }
  };
  const t = (s: string, vars?: Record<string, string | number>) => {
    let out = lang === "so" ? SO[s] ?? s : s;
    if (vars) for (const [k, v] of Object.entries(vars)) out = out.split(`{${k}}`).join(String(v));
    return out;
  };
  return <I18nContext.Provider value={{ lang, setLang, t }}>{children}</I18nContext.Provider>;
}

export const useT = () => useContext(I18nContext);

export function LangToggle({ className = "ghost" }: { className?: string }) {
  const { lang, setLang } = useT();
  return (
    <button type="button" className={className} onClick={() => setLang(lang === "en" ? "so" : "en")} aria-label="Language / Luqad">
      {lang === "en" ? "Soomaali" : "English"}
    </button>
  );
}
