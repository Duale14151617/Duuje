import { useI18n, type Key } from "../i18n";
import { brand, emblemName, type Emblem } from "../lib/brand";

// Official names as printed on each emblem. Change a name here if the approved wording differs.
const institutions = (): (Emblem & { note: Key })[] => [
  { ...brand.primary, note: "inst.defence" },
  { ...brand.oversight, note: "inst.ministry" },
];

export function Institutions() {
  const { t } = useI18n();
  return (
    <>
      <h1>{t("nav.institutions")}</h1>
      <InstitutionsStrip />
    </>
  );
}

/** Emblems of the institutions the HQ references; shown at the foot of the Organization page. */
export function InstitutionsStrip() {
  const { t, lang } = useI18n();
  return (
    <>
      <p className="muted">{t("inst.intro")}</p>
      <div style={{ display: "grid", gap: "1rem", gridTemplateColumns: "repeat(auto-fit, minmax(14rem, 1fr))" }}>
        {institutions().map((i) => (
          <section className="panel text-center" key={i.name}>
            <img src={i.img} alt={i.alt} width={128} height={128} style={{ borderRadius: 8 }} />
            <h2>{emblemName(i, lang)}</h2>
            <p className="muted">{t(i.note)}</p>
          </section>
        ))}
      </div>
    </>
  );
}
