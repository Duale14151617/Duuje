import { useRef, type KeyboardEvent, type ReactNode } from "react";
import { ApiError } from "../api/client";
import { useI18n } from "../i18n";
import { pageRange, pageWindow } from "../lib/tableUtils";
import { Icon, type IconName } from "./Icon";

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

/**
 * Status indicator. `tone` takes the design-system tones (ok, warn, bad, info, neutral) and, unchanged, the older names
 * (approved, success, draft, denied, failure) that existing pages still pass. Toned chips get a leading dot so state is not colour-only.
 */
export function Chip({ tone, children }: { tone?: string; children: ReactNode }) {
  return <span className={`chip ${tone ?? ""}`}>{children}</span>;
}

/** Title row shared by every page: heading on the left, page-level actions on the right. */
export function PageHeader({ title, subtitle, actions }: { title: ReactNode; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="page-head">
      <div className="page-head-text">
        <h1>{title}</h1>
        {subtitle ? <p className="muted">{subtitle}</p> : null}
      </div>
      {actions ? <div className="row page-head-actions">{actions}</div> : null}
    </div>
  );
}

/** What a list shows when there is nothing to list: says why, and offers the next step. */
export function EmptyState({ icon = "inbox", title, hint, action }: { icon?: IconName; title: string; hint?: string; action?: ReactNode }) {
  return (
    <div className="empty-state" role="status">
      <span className="empty-ico" aria-hidden="true"><Icon name={icon} size={28} /></span>
      <h3>{title}</h3>
      {hint ? <p className="muted">{hint}</p> : null}
      {action ? <div className="row empty-action">{action}</div> : null}
    </div>
  );
}

/** Numbered pager used by DataTable and by every page that still lists records itself. Hidden when everything fits on one page. */
export function Pager({ page, count, pageSize, onPage }: { page: number; count: number; pageSize: number; onPage: (p: number) => void }) {
  const { t } = useI18n();
  const total = Math.max(1, Math.ceil(count / pageSize));
  if (total === 1) return null;
  const { from, to } = pageRange(page, pageSize, count);
  return (
    <nav className="pager" aria-label={t("table.pagination")}>
      <span className="muted pager-info">{t("table.showing", { from, to, count })}</span>
      <div className="pager-ctrl">
        <button type="button" className="secondary sm" disabled={page <= 1} onClick={() => onPage(page - 1)}>{t("common.previous")}</button>
        <span className="pager-pages">
          {pageWindow(page, total).map((p, i) => p === "gap"
            ? <span key={`g${i}`} className="pager-gap" aria-hidden="true">…</span>
            : <button key={p} type="button" className={`sm pager-num${p === page ? "" : " secondary"}`} aria-current={p === page ? "page" : undefined}
                      aria-label={t("common.pageOf", { page: p, total })} onClick={() => onPage(p)}>{p}</button>)}
        </span>
        <span className="pager-compact muted">{t("common.pageOf", { page, total })}</span>
        <button type="button" className="secondary sm" disabled={page >= total} onClick={() => onPage(page + 1)}>{t("common.next")}</button>
      </div>
    </nav>
  );
}

export function formatDate(iso: string | null, lang: string): string {
  if (!iso) return "";
  return new Date(iso).toLocaleString(lang === "so" ? "so-SO" : "en-GB", { dateStyle: "medium", timeStyle: "short" });
}

/**
 * Accessible tab strip (arrow keys, Home/End, roving focus). Pass `controls` and render the content in <TabPanel> to link each tab to its panel.
 * Existing callers need no change: `tabs`, `value` and `onChange` behave as before.
 */
export function Tabs<T extends string>({ tabs, value, onChange, label, controls = false, idPrefix = "tab" }: {
  tabs: { id: T; label: string; icon?: IconName }[]; value: T; onChange: (id: T) => void; label?: string; controls?: boolean; idPrefix?: string }) {
  const refs = useRef(new Map<string, HTMLButtonElement>());
  const move = (e: KeyboardEvent<HTMLDivElement>) => {
    const i = tabs.findIndex((x) => x.id === value);
    const to = e.key === "ArrowRight" ? (i + 1) % tabs.length : e.key === "ArrowLeft" ? (i - 1 + tabs.length) % tabs.length
      : e.key === "Home" ? 0 : e.key === "End" ? tabs.length - 1 : -1;
    if (to < 0) return;
    e.preventDefault();
    const next = tabs[to].id;
    onChange(next);
    refs.current.get(next)?.focus();
  };
  return (
    <div className="tabs" role="tablist" aria-label={label} onKeyDown={move}>
      {tabs.map((x) => (
        <button key={x.id} type="button" role="tab" id={`${idPrefix}-${x.id}`} className="tab"
                ref={(el) => { if (el) refs.current.set(x.id, el); else refs.current.delete(x.id); }}
                aria-selected={x.id === value} aria-controls={controls ? `${idPrefix}-panel-${x.id}` : undefined}
                tabIndex={x.id === value ? 0 : -1} onClick={() => onChange(x.id)}>
          {x.icon ? <Icon name={x.icon} size={16} /> : null}<span>{x.label}</span>
        </button>
      ))}
    </div>
  );
}

/** Content of one tab. Children are only mounted while the tab is open, so a tab's data is fetched when it is first viewed. */
export function TabPanel({ id, active, idPrefix = "tab", children }: { id: string; active: boolean; idPrefix?: string; children: ReactNode }) {
  if (!active) return null;
  return <div role="tabpanel" id={`${idPrefix}-panel-${id}`} aria-labelledby={`${idPrefix}-${id}`} tabIndex={0} className="tab-panel">{children}</div>;
}
