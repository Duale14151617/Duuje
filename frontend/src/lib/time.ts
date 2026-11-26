/** Small date helpers shared by the dashboard and profile screens. */

export function greetingKey(date = new Date()): "dash.greet.morning" | "dash.greet.afternoon" | "dash.greet.evening" {
  const h = date.getHours();
  return h < 12 ? "dash.greet.morning" : h < 18 ? "dash.greet.afternoon" : "dash.greet.evening";
}

const localeOf = (lang: string) => (lang === "so" ? "so-SO" : "en-GB");

export function formatLongDate(date: Date, lang: string): string {
  try { return date.toLocaleDateString(localeOf(lang), { weekday: "long", day: "numeric", month: "long", year: "numeric" }); }
  catch { return date.toDateString(); }
}

/** "2 hours ago" in the interface language; falls back to English if the browser lacks Somali data. */
export function timeAgo(iso: string, lang: string, now = Date.now()): string {
  const diff = new Date(iso).getTime() - now;
  if (Number.isNaN(diff)) return "";
  const units: [Intl.RelativeTimeFormatUnit, number][] = [["day", 864e5], ["hour", 36e5], ["minute", 6e4]];
  let rtf: Intl.RelativeTimeFormat;
  try { rtf = new Intl.RelativeTimeFormat(localeOf(lang), { numeric: "auto" }); }
  catch { rtf = new Intl.RelativeTimeFormat("en-GB", { numeric: "auto" }); }
  for (const [unit, ms] of units) {
    if (Math.abs(diff) >= ms) return rtf.format(Math.round(diff / ms), unit);
  }
  return rtf.format(0, "minute");
}

/** Whole years between an ISO date and now; null when the date is missing or invalid. */
export function yearsSince(iso: string | null | undefined, now = new Date()): number | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  let y = now.getFullYear() - d.getFullYear();
  const m = now.getMonth() - d.getMonth();
  if (m < 0 || (m === 0 && now.getDate() < d.getDate())) y -= 1;
  return y < 0 ? null : y;
}
