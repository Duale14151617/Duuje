import { useEffect, useState } from "react";
import type { Page, Unit } from "../api/types";
import { useFetch } from "../api/useFetch";
import { useI18n } from "../i18n";
import { Field } from "./ui";

/**
 * Searchable unit selector. A national structure has thousands of units, so a plain dropdown of "the first 100"
 * cannot reach most of them: type part of a name or code, then choose from the matches.
 */
export function UnitPicker({ label, value, onChange, params, required, allowAll, exclude }: {
  label: string; value: string; onChange: (id: string, unit: Unit | null) => void;
  params?: Record<string, string | number | undefined>; required?: boolean; allowAll?: boolean; exclude?: string;
}) {
  const { t, name } = useI18n();
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  const [chosen, setChosen] = useState<Unit | null>(null);
  useEffect(() => { const h = setTimeout(() => setDebounced(q.trim()), 250); return () => clearTimeout(h); }, [q]);
  const list = useFetch<Page<Unit>>("/organization/units/", { placeable: 1, active: "true", page_size: 30, q: debounced, ...params });
  const options = (list.data?.results ?? []).filter((u) => u.id !== exclude);
  const showChosen = chosen && chosen.id === value && !options.some((u) => u.id === value);
  return (
    <>
      <input type="search" value={q} onChange={(e) => setQ(e.target.value)} maxLength={100}
             aria-label={t("org.searchUnits")} placeholder={t("org.searchUnits")} />
      <Field label={label}>
        <select value={value} required={required}
                onChange={(e) => { const u = options.find((x) => x.id === e.target.value) ?? null; setChosen(u); onChange(e.target.value, u); }}>
          {allowAll ? <option value="">{t("common.all")}</option> : <option value="" />}
          {showChosen && <option value={chosen.id}>{name(chosen)}</option>}
          {options.map((u) => <option key={u.id} value={u.id}>{name(u)} · {u.code}</option>)}
        </select>
      </Field>
    </>
  );
}
