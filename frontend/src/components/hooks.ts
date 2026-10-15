import type { Page, Unit } from "../api/types";
import { useFetch } from "../api/useFetch";

/** Branch commands and units in the caller's scope (the only places items can be held). */
export function usePlaceableUnits() {
  const r = useFetch<Page<Unit>>("/organization/units/", { page_size: 100 });
  return (r.data?.results ?? []).filter((u) => (u.level === "branch_command" || u.level === "unit") && u.active);
}
