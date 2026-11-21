import { useState } from "react";
import { useI18n } from "../i18n";

/** Shows a fresh set of backup codes once, with copy, download and print, so the person really keeps them. */
export function BackupCodesPanel({ codes, onDone }: { codes: string[]; onDone: () => void }) {
  const { t } = useI18n();
  const [copied, setCopied] = useState(false);
  const text = codes.join("\n");

  const copy = async () => {
    try { await navigator.clipboard.writeText(text); setCopied(true); window.setTimeout(() => setCopied(false), 2500); } catch { /* no clipboard permission */ }
  };
  const download = () => {
    const url = URL.createObjectURL(new Blob([`${t("backup.fileTitle")}\n\n${text}\n`], { type: "text/plain" }));
    const a = document.createElement("a");
    a.href = url; a.download = "backup-codes.txt"; a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="card backup-codes">
      <h3>{t("backup.title")}</h3>
      <p className="muted">{t("backup.intro")}</p>
      <ul className="backup-list mono" aria-label={t("backup.title")}>
        {codes.map((c) => <li key={c}>{c}</li>)}
      </ul>
      <div className="row backup-actions" style={{ gap: ".5rem", flexWrap: "wrap" }}>
        <button type="button" className="secondary" onClick={() => void copy()}>{copied ? t("backup.copied") : t("common.copy")}</button>
        <button type="button" className="secondary" onClick={download}>{t("backup.download")}</button>
        <button type="button" className="secondary" onClick={() => window.print()}>{t("backup.print")}</button>
        <button type="button" onClick={onDone}>{t("backup.saved")}</button>
      </div>
    </div>
  );
}
