// Emblem and institution name shown by the app (printed documents, ID cards, the verification page).
export interface Emblem { img: string; name: string; name_so?: string; alt: string }

/** The institution's name in the interface language (falls back to English when no Somali name is set). */
export const emblemName = (e: Emblem, lang: string): string => (lang === "so" && e.name_so) || e.name;

export const brand: { primary: Emblem } = {
  primary: { img: "/defence-force.jpg", name: "Puntland Defence Forces", name_so: "Ciidamada Difaaca Puntland", alt: "Puntland Defence Forces emblem" },
};
