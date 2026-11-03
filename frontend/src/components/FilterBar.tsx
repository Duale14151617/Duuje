import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { useI18n } from "../i18n";
import { Icon } from "./Icon";

export interface FilterOption { value: string; label: string }
export interface SelectFilter {
  id: string;
  label: string;
  value: string;
  options: FilterOption[];
  onChange: (value: string) => void;
  /** Kept inside "More filters" instead of the main row. */
  advanced?: boolean;
}
/** A filter the page draws itself (a unit picker, a checkbox); `label` is what the active chip says, `onClear` removes it. */
export interface CustomFilter { id: string; label: string; active: boolean; onClear: () => void }

interface Props {
  search?: { value: string; onChange: (v: string) => void; label: string };
  filters?: SelectFilter[];
  /** Controls for the "More filters" area, drawn by the page. */
  advancedExtra?: ReactNode;
  custom?: CustomFilter[];
  onReset?: () => void;
}

/**
 * Search box plus filters in one consistent bar. Everything is still held by the page and sent to the same server request as before;
 * this only presents it: a debounced search field, primary filters, a collapsible "More filters" area, removable chips and Reset.
 */
export function FilterBar({ search, filters = [], advancedExtra, custom = [], onReset }: Props) {
  const { t } = useI18n();
  const uid = useId();
  const primary = filters.filter((f) => !f.advanced);
  const advanced = filters.filter((f) => f.advanced);
  const activeSelects = filters.filter((f) => f.value !== "");
  const activeCustom = custom.filter((c) => c.active);
  const advancedActive = advanced.filter((f) => f.value !== "").length + activeCustom.length;
  const hasAdvanced = advanced.length > 0 || !!advancedExtra;
  const [open, setOpen] = useState(advancedActive > 0);
  const activeCount = activeSelects.length + activeCustom.length + (search?.value ? 1 : 0);

  // debounce typing so a fast typist sends one request, not one per key
  const [text, setText] = useState(search?.value ?? "");
  const latest = useRef(search);
  latest.current = search;
  useEffect(() => { setText(search?.value ?? ""); }, [search?.value]);
  useEffect(() => {
    if (!latest.current || text === latest.current.value) return;
    const timer = setTimeout(() => latest.current?.onChange(text), 300);
    return () => clearTimeout(timer);
  }, [text]);

  const select = (f: SelectFilter) => (
    <label className="field fb-field" key={f.id}>
      <span>{f.label}</span>
      <select value={f.value} onChange={(e) => f.onChange(e.target.value)}>
        <option value="">{t("common.all")}</option>
        {f.options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </label>
  );

  return (
    <div className="fb">
      <div className="fb-row">
        {search && (
          <div className="fb-search">
            <label className="sr-only" htmlFor={`${uid}-q`}>{search.label}</label>
            <Icon name="search" size={18} />
            <input id={`${uid}-q`} type="search" value={text} placeholder={search.label} autoComplete="off"
                   onChange={(e) => setText(e.target.value)}
                   onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); search.onChange(text); } }} />
            {text && <button type="button" className="ghost icon-btn fb-clear" aria-label={t("filter.clearSearch")}
                             onClick={() => { setText(""); search.onChange(""); }}><Icon name="close" size={16} /></button>}
          </div>
        )}
        {primary.map(select)}
        {hasAdvanced && (
          <button type="button" className="secondary fb-more" aria-expanded={open} aria-controls={`${uid}-adv`} onClick={() => setOpen((v) => !v)}>
            <Icon name="sliders" size={16} /> <span>{open ? t("filter.fewer") : t("filter.more")}</span>
            {advancedActive > 0 && <span className="fb-badge" aria-label={t("filter.activeCount", { count: advancedActive })}>{advancedActive}</span>}
          </button>
        )}
        {onReset && activeCount > 0 && <button type="button" className="ghost fb-reset" onClick={onReset}><Icon name="refresh" size={16} /> <span>{t("filter.reset")}</span></button>}
      </div>
      {hasAdvanced && open && (
        <div className="fb-adv" id={`${uid}-adv`}>
          {advanced.map(select)}
          {advancedExtra}
        </div>
      )}
      {activeCount > 0 && (
        <ul className="fb-chips" aria-label={t("filter.active")}>
          {search?.value ? (
            <li className="fb-chip"><span>{t("filter.chipSearch", { value: search.value })}</span>
              <button type="button" aria-label={t("filter.remove", { name: search.label })} onClick={() => { setText(""); search.onChange(""); }}><Icon name="close" size={12} /></button></li>
          ) : null}
          {activeSelects.map((f) => (
            <li key={f.id} className="fb-chip"><span>{f.label}: {f.options.find((o) => o.value === f.value)?.label ?? f.value}</span>
              <button type="button" aria-label={t("filter.remove", { name: f.label })} onClick={() => f.onChange("")}><Icon name="close" size={12} /></button></li>
          ))}
          {activeCustom.map((c) => (
            <li key={c.id} className="fb-chip"><span>{c.label}</span>
              <button type="button" aria-label={t("filter.remove", { name: c.label })} onClick={c.onClear}><Icon name="close" size={12} /></button></li>
          ))}
        </ul>
      )}
    </div>
  );
}
