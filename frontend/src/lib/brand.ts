// Emblems and institution names shown by the app. Puntland Defence Forces is the only deployment here, so these are fixed values;
// the pages that print a letterhead or a verification page read them from here.
export interface Emblem { img: string; name: string; name_so?: string; alt: string }

/** The institution's name in the interface language (falls back to English when no Somali name is set). */
export const emblemName = (e: Emblem, lang: string): string => (lang === "so" && e.name_so) || e.name;

export const brand: { primary: Emblem; oversight: Emblem } = {
  primary: { img: "/defence-force.jpg", name: "Puntland Defence Force", alt: "Puntland Defence Force emblem" },
  oversight: { img: "/ministry.jpg", name: "Ministry of Security Puntland", alt: "Ministry of Security Puntland emblem" },
};
