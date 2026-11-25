/**
 * The one place that decides how numbers, money and dates are written, so every screen, table and PDF agrees, in English and Somali.
 *
 * - Numbers and money group thousands with commas and use a dot for decimals in BOTH languages (1,234.50). Somali writes numbers
 *   the same way, and using one fixed locale means the result never depends on the computer or browser the person happens to use
 *   (a bare `toLocaleString()` does, which is how two officers can see the same figure written two ways).
 * - Money is "amount currency": 1,234.50 USD. Always two decimals; the currency code is never dropped or guessed.
 * - Dates follow the interface language when the browser has its data (Somali month names), else fall back to English; the shape is
 *   always the same: 20 Nov 2026, 20 Nov 2026, 11:45 (24-hour).
 * - A bare calendar date ("2026-11-20") is read as that day in the person's own calendar, never shifted by a time zone.
 */

const NUMBER_LOCALE = "en-GB";
const NBSP = "\u00A0";

const numberFormats = new Map<string, Intl.NumberFormat>();
function numberFormat(min: number, max: number): Intl.NumberFormat {
  const key = `${min}:${max}`;
  let f = numberFormats.get(key);
  if (!f) { f = new Intl.NumberFormat(NUMBER_LOCALE, { minimumFractionDigits: min, maximumFractionDigits: max }); numberFormats.set(key, f); }
  return f;
}

/** A number as text. Whole numbers stay whole; fractions show up to 3 places unless `decimals` fixes the count. "-" when it is not a number. */
export function formatNumber(value: number | string | null | undefined, decimals?: number): string {
  if (value === null || value === undefined || value === "") return "-";
  const n = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(n)) return "-";
  return decimals === undefined ? numberFormat(0, 3).format(n) : numberFormat(decimals, decimals).format(n);
}

/** Money as "1,234.50 USD". Amounts arrive from the server as decimal strings; they are only formatted here, never added up. */
export function formatMoney(amount: number | string | null | undefined, currency?: string | null): string {
  const n = formatNumber(amount, 2);
  if (n === "-") return "-";
  return currency ? `${n}${NBSP}${currency}` : n;
}

/** Several currencies in one line ("1,200.00 USD + 5,000.00 SOS"); "0" when there is nothing. */
export function formatMoneyList(rows: { total: number | string; currency?: string | null }[], joiner = " + "): string {
  return rows.length ? rows.map((r) => formatMoney(r.total, r.currency)).join(joiner) : "0";
}

const localeCache = new Map<string, string>();
/** The locale to write dates in: Somali when this browser has Somali date data, otherwise British English. */
export function dateLocale(lang: string): string {
  let l = localeCache.get(lang);
  if (l === undefined) {
    const want = lang === "so" ? ["so-SO", "so"] : ["en-GB"];
    try { l = Intl.DateTimeFormat.supportedLocalesOf(want)[0]; } catch { l = undefined; }
    l = l ?? "en-GB";
    localeCache.set(lang, l);
  }
  return l;
}

/** A Date from an ISO timestamp, a Date, or a bare "YYYY-MM-DD" (taken as local midnight, so it never slips a day). Null if invalid. */
export function toDate(value: string | Date | null | undefined): Date | null {
  if (value === null || value === undefined || value === "") return null;
  const d = value instanceof Date ? value : new Date(/^\d{4}-\d{2}-\d{2}$/.test(value) ? `${value}T00:00:00` : value);
  return Number.isNaN(d.getTime()) ? null : d;
}

interface Shape { weekday?: "long" | "short"; month: "long" | "short"; year?: boolean; time?: boolean }

/** Writes a date as "[weekday] day month [year][, hh:mm]" in that fixed order whatever the language, using the locale only for the
 *  words (month and weekday names). Somali browser data would otherwise put the month first and the shape would differ by language. */
function compose(value: string | Date | null | undefined, lang: string, shape: Shape): string {
  const d = toDate(value);
  if (!d) return "";
  try {
    const p: Record<string, string> = {};
    for (const part of new Intl.DateTimeFormat(dateLocale(lang), {
      weekday: shape.weekday, day: "numeric", month: shape.month, year: "numeric", hour: "2-digit", minute: "2-digit", hourCycle: "h23",
    }).formatToParts(d)) p[part.type] = part.value;
    const date = [p.day, p.month, shape.year === false ? "" : p.year].filter(Boolean).join(" ");
    const text = [shape.weekday ? p.weekday : "", date].filter(Boolean).join(" ");
    return shape.time ? `${text}, ${p.hour}:${p.minute}` : text;
  } catch { return d.toDateString(); }
}

/** 20 Nov 2026 */
export const formatDay = (value: string | Date | null | undefined, lang: string): string => compose(value, lang, { month: "short" });

/** 20 Nov 2026, 11:45 (24-hour) */
export const formatDateTime = (value: string | Date | null | undefined, lang: string): string =>
  compose(value, lang, { month: "short", time: true });

/** 11:45 (24-hour) */
export function formatTime(value: string | Date | null | undefined, lang: string): string {
  const d = toDate(value);
  if (!d) return "";
  try { return new Intl.DateTimeFormat(dateLocale(lang), { hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).format(d); }
  catch { return d.toTimeString().slice(0, 5); }
}

/** Friday 20 November 2026 */
export const formatLongDate = (value: string | Date | null | undefined, lang: string): string =>
  compose(value, lang, { weekday: "long", month: "long" });

/** Fri 20 Nov, or Friday 20 November: no year, for headers and chart labels. */
export const formatDayMonth = (value: string | Date | null | undefined, lang: string, weekday?: "long" | "short", month: "long" | "short" = "short"): string =>
  compose(value, lang, { weekday, month, year: false });
