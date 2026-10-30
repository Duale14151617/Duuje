import type { ReactNode } from "react";
import { ApiError } from "../api/client";
import { useI18n } from "../i18n";

export function Notice({ kind = "info", children }: { kind?: "error" | "info"; children: ReactNode }) {
  return <div className={`notice ${kind}`} role={kind === "error" ? "alert" : "status"}>{children}</div>;
}

export function useErrorText() {
  const { tr } = useI18n();
  return (err: unknown): string => {
    if (err instanceof ApiError) {
      const code = err.code === "validation_error" ? err.fieldCode ?? "validation_error" : err.code;
      return tr(`err.${code}`) ?? tr(`err.${err.code}`) ?? tr("err.error") ?? "Error";
    }
    return tr("err.error") ?? "Error";
  };
}

export function ErrorNotice({ error }: { error: unknown }) {
  const text = useErrorText();
  if (!error) return null;
  return <Notice kind="error">{text(error)}</Notice>;
}

export function Loading() {
  const { t } = useI18n();
  return <p className="muted" role="status">{t("common.loading")}</p>;
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
    </label>
  );
}

export function Chip({ tone, children }: { tone?: string; children: ReactNode }) {
  return <span className={`chip ${tone ?? ""}`}>{children}</span>;
}

export function Pager({ page, count, pageSize, onPage }: { page: number; count: number; pageSize: number; onPage: (p: number) => void }) {
  const { t } = useI18n();
  const total = Math.max(1, Math.ceil(count / pageSize));
  if (total === 1) return null;
  return (
    <div className="row" style={{ justifyContent: "space-between", margin: ".75rem 0" }}>
      <button className="secondary" disabled={page <= 1} onClick={() => onPage(page - 1)}>{t("common.previous")}</button>
      <span className="muted">{t("common.pageOf", { page, total })}</span>
      <button className="secondary" disabled={page >= total} onClick={() => onPage(page + 1)}>{t("common.next")}</button>
    </div>
  );
}

export function formatDate(iso: string | null, lang: string): string {
  if (!iso) return "";
  return new Date(iso).toLocaleString(lang === "so" ? "so-SO" : "en-GB", { dateStyle: "medium", timeStyle: "short" });
}

export function Tabs<T extends string>({ tabs, value, onChange }: {
  tabs: { id: T; label: string }[]; value: T; onChange: (id: T) => void }) {
  return (
    <div className="row" style={{ marginBottom: "1rem" }} role="tablist">
      {tabs.map((x) => (
        <button key={x.id} role="tab" aria-selected={x.id === value} className={x.id === value ? "" : "secondary"}
                onClick={() => onChange(x.id)}>{x.label}</button>
      ))}
    </div>
  );
}
