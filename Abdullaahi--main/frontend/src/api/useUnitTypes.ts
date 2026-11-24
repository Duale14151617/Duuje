import { useMemo } from "react";
import type { Designation, UnitType } from "./types";
import { useFetch } from "./useFetch";

/** Template catalogues (unit types and specialist designations), loaded once per page that needs them. */
export function useUnitTypes() {
  const types = useFetch<UnitType[]>("/organization/unit-types/");
  const designations = useFetch<Designation[]>("/organization/designations/");
  const typeById = useMemo(() => new Map((types.data ?? []).map((x) => [x.id, x])), [types.data]);
  const designationById = useMemo(() => new Map((designations.data ?? []).map((x) => [x.id, x])), [designations.data]);
  return { types, designations, typeById, designationById };
}
