/** Specialties a new person can be given so the system can suggest the unit that fits. Codes match the server (placement_hints.py). */
export const SPECIALTIES = ["infantry", "medical", "transport", "communications", "finance", "supply", "operations", "administration"] as const;
export type Specialty = (typeof SPECIALTIES)[number];
