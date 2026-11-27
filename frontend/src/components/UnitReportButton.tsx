import { useState } from "react";
import { downloadWithQuery } from "../api/client";
import { useI18n } from "../i18n";
import { ErrorNotice } from "./ui";

const PERIODS = [7, 30, 90, 365];

/** Makes the unit report (strength, leave, weapons, vehicles and fuel for this unit and everything below it) and downloads it as a PDF.
 *  The server decides what each person may see in it; totals only, so a printed copy can go to a commander with no login. */
export function UnitReportButton({ unitId, code }: { unitId: string; code: string }) {
  const { t } = useI18n();
  const [days, setDays] = useState(30);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function run() {
    setBusy(true);
    setError(null);
    const to = new Date();
    const from = new Date(to.getTime() - (days - 1) * 86_400_000);
    const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    try {
      await downloadWithQuery("/unit-report/", { unit: unitId, from: iso(from), to: iso(to) }, `unit-report-${code}-${iso(to)}.pdf`);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }

  return (
    <span className="row" style={{ gap: ".5rem", alignItems: "center" }}>
      <select aria-label={t("ureport.period")} value={days} onChange={(e) => setDays(Number(e.target.value))} disabled={busy}>
        {PERIODS.map((d) => <option key={d} value={d}>{t("ureport.days", { n: d })}</option>)}
      </select>
      <button type="button" className="secondary" disabled={busy} onClick={() => void run()}>{busy ? t("ureport.busy") : t("ureport.button")}</button>
      {error ? <ErrorNotice error={error} /> : null}
    </span>
  );
}
