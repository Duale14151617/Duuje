import type { Unit } from "../api/types";
import { useFetch } from "../api/useFetch";
import { useI18n, type Key } from "../i18n";
import type { Specialty } from "../lib/specialties";
import { Notice } from "./ui";

interface Result { specialty: string; suggestions: Unit[]; chosen?: { fit: "match" | "general" | "mismatch"; function: string | null } }

/** Advice only: lists the units that fit the person's specialty and warns when the chosen unit is for another trade. Never blocks. */
export function UnitSuggestions({ specialty, unitId, onPick }: { specialty: Specialty | ""; unitId: string; onPick: (unit: Unit) => void }) {
  const { t, name } = useI18n();
  const res = useFetch<Result>(specialty ? "/organization/units/suggest/" : null, { specialty, unit: unitId || undefined });
  if (!specialty) return null;
  const label = t(`spec.${specialty}` as Key);
  const d = res.data;
  const fit = unitId ? d?.chosen?.fit : undefined;
  return (
    <div className="mb-075">
      {fit === "mismatch" && <Notice>{t("sug.mismatch", { specialty: label })}</Notice>}
      {fit === "general" && specialty !== "infantry" && <Notice>{t("sug.general", { specialty: label })}</Notice>}
      {fit === "match" && <p className="muted small">{t("sug.match", { specialty: label })}</p>}
      {d && d.suggestions.length === 0 && <p className="muted small">{t("sug.none", { specialty: label })}</p>}
      {d && d.suggestions.length > 0 && (
        <>
          <p className="muted small">{t("sug.title", { specialty: label })}</p>
          <div className="row" style={{ flexWrap: "wrap" }}>
            {d.suggestions.map((u) => (
              <button key={u.id} type="button" className={u.id === unitId ? "" : "secondary"} aria-pressed={u.id === unitId} onClick={() => onPick(u)}>
                {name(u)} · {u.code}
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
