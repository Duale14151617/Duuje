/** Shapes and helpers shared by the Payroll tabs (payments, arrears, pay decisions). Only what the server already returns. */

export const tone = (s: string) =>
  ["approved", "paid", "reconciled", "verified"].includes(s) ? "approved"
    : ["rejected", "cancelled", "failed", "discrepancy"].includes(s) ? "bad" : "draft";

export interface Allocation { id: string; amount: string; currency: string; status: string; basis_kind: string }
export interface BeneficiaryLite { id: string; full_name: string; tier: number; state: string; allocations: Allocation[] }
export interface CaseLite { id: string; personnel: string; personnel_name: string; service_number: string | null; status: string; beneficiaries: BeneficiaryLite[] }
export interface Claim {
  id: string; personnel: string; personnel_name: string; service_number: string | null; periods: string[]; source_lines: string[]; amount: string; currency: string;
  evidence_ref: string; note: string; status: string; paid: string; outstanding: string | null; recorded_by: string; verified_by: string | null; approved_by: string | null; decision_note: string;
}
export interface PaySummary { payments_unreconciled: number; payments_with_discrepancy: number; arrears_awaiting_decision: number; pay_decisions_awaiting_approval: number; flagged_suspended_or_jailed: number }

/** Money left to pay, as a plain 2-decimal string (never negative). */
export const left = (total: string | null | undefined, paid: string): string => Math.max(0, Number(total ?? 0) - Number(paid || 0)).toFixed(2);
