// Emblems and institution names shown by the app. Puntland Police is the default; main.tsx reads /api/v1/profile/ once at
// start-up, before the first render, so every page reads these values directly.
export interface Emblem { img: string; name: string; name_so?: string; alt: string }

/** The institution's name in the interface language (falls back to English when no Somali name is set). */
export const emblemName = (e: Emblem, lang: string): string => (lang === "so" && e.name_so) || e.name;

export const brand: { primary: Emblem; oversight: Emblem } = {
  primary: { img: "/police-emblem.jpg", name: "Puntland Police", alt: "Puntland Police emblem" },
  oversight: { img: "/judiciary.jpg", name: "Puntland Court of Armed Forces", name_so: "Maxkamada Ciidamada Qalabka Sida ee Puntland", alt: "Puntland Court of Armed Forces emblem" },
};

export function setPoliceBrand(): void {
  brand.primary = { img: "/police-emblem.jpg", name: "Puntland Police", alt: "Puntland Police emblem" };
  brand.oversight = { img: "/judiciary.jpg", name: "Puntland Court of Armed Forces", name_so: "Maxkamada Ciidamada Qalabka Sida ee Puntland", alt: "Puntland Court of Armed Forces emblem" };
}
