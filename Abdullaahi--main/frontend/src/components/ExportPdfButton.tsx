import { useState } from "react";
import { useAuth } from "../auth/AuthContext";
import { brand, emblemName } from "../lib/brand";
import { loadCrest } from "../lib/crest";
import { useI18n } from "../i18n";
import { downloadPdf, type PdfBrand, type PdfColumn, type PdfSection } from "../lib/pdf";
import { ErrorNotice } from "./ui";

export interface PdfContent {
  title: string;
  subtitle?: string;
  landscape?: boolean;
  sections: (Omit<PdfSection, "columns"> & { heading?: string; columns: (Omit<PdfColumn, "header"> & { header: string })[] })[];
}

/** Document reference printed on every page: institution prefix, date, time and a short random suffix, e.g. PHQ-20261120-0624-7F3K.
 *  It is generated in the browser and identifies this printout; it is not a registered serial number. */
function newReference(): string {
  const d = new Date().toISOString();
  const prefix = /police/i.test(brand.primary.name) ? "PHQ" : "AHQ";
  const rand = Array.from(crypto.getRandomValues(new Uint8Array(4)), (b) => "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"[b % 32]).join("");
  return `${prefix}-${d.slice(0, 10).replace(/-/g, "")}-${d.slice(11, 16).replace(":", "")}-${rand}`;
}

/**
 * Builds a PDF in the browser from data the person can already see. `build` may be async so callers can fetch every
 * page of a filtered list first. Nothing is uploaded anywhere.
 */
export function ExportPdfButton({ build, filename, className = "secondary", disabled, onError, label }: {
  build: () => PdfContent | Promise<PdfContent>; filename: string; className?: string; disabled?: boolean;
  /** When given, errors are reported here instead of being shown beside the button. */
  onError?: (err: unknown) => void;
  /** Button text; defaults to "Export PDF". */
  label?: string;
}) {
  const { t, lang } = useI18n();
  const { me } = useAuth();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function run() {
    setBusy(true); setError(null); onError?.(null);
    try {
      const content = await build();
      const letterhead: PdfBrand = {
        org: emblemName(brand.primary, lang),
        unit: t("pdf.hq"),
        classification: t("pdf.classification"),
        reference: newReference(),
        referenceLabel: t("pdf.reference"),
        generatedByLabel: t("pdf.generatedBy"),
        generatedBy: me ? `${me.full_name} (${me.username})` : "-",
        crest: await loadCrest(brand.primary.img),
      };
      downloadPdf({
        ...content,
        brand: letterhead,
        footer: t("app.name"),
        generatedLabel: t("pdf.generated"),
        pageLabel: (p, n) => t("pdf.page", { page: p, total: n }),
      }, filename.replace(/\.pdf$/, "") + `-${new Date().toISOString().slice(0, 10)}.pdf`);
    } catch (err) { setError(err); onError?.(err); }
    finally { setBusy(false); }
  }

  return (
    <>
      <button type="button" className={className} disabled={busy || disabled} lang={lang} onClick={() => void run()}>
        {busy ? t("pdf.preparing") : (label ?? t("common.exportPdf"))}
      </button>
      {error && !onError ? <ErrorNotice error={error} /> : null}
    </>
  );
}
