import { useState } from "react";
import { useI18n } from "../i18n";
import { downloadPdf, type PdfColumn, type PdfSection } from "../lib/pdf";
import { ErrorNotice } from "./ui";

export interface PdfContent {
  title: string;
  subtitle?: string;
  landscape?: boolean;
  sections: (Omit<PdfSection, "columns"> & { heading?: string; columns: (Omit<PdfColumn, "header"> & { header: string })[] })[];
}

/**
 * Builds a PDF in the browser from data the person can already see. `build` may be async so callers can fetch every
 * page of a filtered list first. Nothing is uploaded anywhere.
 */
export function ExportPdfButton({ build, filename, className = "secondary", disabled, onError }: {
  build: () => PdfContent | Promise<PdfContent>; filename: string; className?: string; disabled?: boolean;
  /** When given, errors are reported here instead of being shown beside the button. */
  onError?: (err: unknown) => void;
}) {
  const { t, lang } = useI18n();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function run() {
    setBusy(true); setError(null); onError?.(null);
    try {
      const content = await build();
      downloadPdf({
        ...content,
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
        {busy ? t("pdf.preparing") : t("common.exportPdf")}
      </button>
      {error && !onError ? <ErrorNotice error={error} /> : null}
    </>
  );
}
