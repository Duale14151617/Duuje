import type { PdfContent } from "../components/ExportPdfButton";

/** Printable onboarding papers for new accounts, built in the browser from what the person who created the accounts is looking at.
 *  The temporary passwords are in the sheet and nowhere else: the server shows them once and never stores them in clear. */
type T = (key: never, vars?: Record<string, string | number>) => string;
export interface NewAccount { username: string; full_name: string; role: string; unit: string; temporary_password: string; expires_at: string }

const BLANK = "________________________";
const STEPS = ["onb.s1", "onb.s2", "onb.s3", "onb.s4", "onb.s5", "onb.s6", "onb.s7", "onb.s8", "onb.s9"];

/** The first-login checklist as a PDF section: one row per step with a box to tick by hand. */
export function checklistSection(t: T) {
  const L = (k: string) => t(k as never);
  return {
    heading: L("onb.checkTitle"),
    columns: [{ header: L("onb.checkDone"), width: 1 }, { header: "", width: 12 }],
    rows: STEPS.map((k, i) => ["[   ]", `${i + 1}. ${L(k)}`]),
  };
}

export function checklistDoc(t: T): PdfContent {
  const L = (k: string) => t(k as never);
  return { title: L("onb.checkTitle"), subtitle: L("onb.checkIntro"), sections: [{ ...checklistSection(t), heading: undefined }] };
}

/** Sign-in sheet: one row per new account with the username, temporary password, expiry and a signature line, followed by the checklist
 *  so each person can be handed the same steps. `issuedBy` is the signed-in user's name; `fmtDate` formats an ISO date for the interface language. */
export function signInSheetDoc(accounts: NewAccount[], t: T, issuedBy: string, fmtDate: (iso: string) => string): PdfContent {
  const L = (k: string, v?: Record<string, string | number>) => t(k as never, v);
  const expires = accounts[0]?.expires_at ? fmtDate(accounts[0].expires_at) : "—";
  return {
    title: L("onb.sheetTitle"),
    subtitle: L("onb.sheetSubtitle", { date: fmtDate(new Date().toISOString()), by: issuedBy, expires }),
    landscape: true,
    sections: [
      { columns: [{ header: "", width: 1 }], rows: [[L("onb.warn")]] },
      { columns: [
        { header: L("onb.colNo"), width: 1 }, { header: L("users.username"), width: 3 }, { header: L("users.fullName"), width: 4 },
        { header: L("onb.colRole"), width: 4 }, { header: L("users.bulk.password"), width: 3 }, { header: L("users.bulk.expires"), width: 2 },
        { header: L("onb.colSign"), width: 4 }],
        rows: accounts.map((a, i) => [String(i + 1), a.username, a.full_name, `${a.role} · ${a.unit}`, a.temporary_password, a.expires_at ? fmtDate(a.expires_at) : "—", BLANK]) },
      checklistSection(t),
    ],
  };
}
