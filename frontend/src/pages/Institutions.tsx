import { useI18n, type Key } from "../i18n";

// Official names as printed on each emblem. Change a name here if the approved wording differs.
const INSTITUTIONS: { img: string; name: string; alt: string; note: Key }[] = [
  { img: "/defence-force.jpg", name: "Puntland Defence Force", alt: "Puntland Defence Force emblem", note: "inst.defence" },
  { img: "/ministry.jpg", name: "Ministry of Security Puntland", alt: "Ministry of Security Puntland emblem", note: "inst.ministry" },
];

export function Institutions() {
  const { t } = useI18n();
  return (
    <>
      <h1>{t("nav.institutions")}</h1>
      <p className="muted">{t("inst.intro")}</p>
      <div style={{ display: "grid", gap: "1rem", gridTemplateColumns: "repeat(auto-fit, minmax(14rem, 1fr))" }}>
        {INSTITUTIONS.map((i) => (
          <section className="panel" key={i.name} style={{ textAlign: "center" }}>
            <img src={i.img} alt={i.alt} width={128} height={128} style={{ borderRadius: 8 }} />
            <h2>{i.name}</h2>
            <p className="muted">{t(i.note)}</p>
          </section>
        ))}
      </div>
    </>
  );
}
