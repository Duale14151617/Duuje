/** One mapping from a record's status code to a colour tone, so the same state looks the same in every module. */
export type Tone = "ok" | "warn" | "bad" | "info" | "neutral";

const TONES: Record<string, Tone> = {
  // personnel
  active: "ok", on_leave: "warn", suspended: "bad", jailed: "bad", died: "bad", retired: "neutral", discharged: "neutral",
  // approvals and report workflow
  draft: "warn", approved: "ok", submitted: "info", under_review: "warn", rejected: "bad", returned: "warn", amended: "info",
  pending: "warn", denied: "warn", executed: "ok", cancelled: "neutral", withdrawn: "neutral",
  // equipment
  in_stock: "ok", issued: "info", maintenance: "warn", missing: "bad", lost: "bad",
  // training
  enrolled: "neutral", in_progress: "info", completed: "ok", failed: "bad",
  // audit outcome
  success: "ok", failure: "bad",
  // generic
  inactive: "neutral", disabled: "neutral", open: "info", closed: "neutral", overdue: "bad",
};

export function statusTone(status: string | null | undefined): Tone {
  return (status && TONES[status]) || "neutral";
}
