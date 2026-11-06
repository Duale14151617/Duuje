export type Lang = "en" | "so";
export interface Named { name_en: string; name_so: string }
export interface UnitBrief extends Named { id: string; code: string; level: string; unit_type?: string | null }
export interface BranchBrief extends Named { id: string; code: string }
export interface RoleBrief extends Named { id: string; code: string; is_privileged: boolean }
export interface Assignment {
  id: string; role: RoleBrief; org_unit: UnitBrief; branch: BranchBrief | null;
  valid_from: string | null; valid_until: string | null; revoked_at: string | null; created_at: string;
}
export interface Me {
  id: string; username: string; full_name: string; preferred_language: Lang; mfa_enabled: boolean;
  requires_mfa: boolean; restrictions: string[]; permissions: string[]; assignments: Assignment[];
  features: { personnel_export: boolean; report_export: boolean; integrations: boolean };
  /** The personnel record this login belongs to, if one is linked. */
  personnel_id?: string | null;
}
export interface Page<T> { count: number; next: string | null; previous: string | null; results: T[] }
export interface Unit extends Named {
  id: string; code: string; level: string; parent: string | null; branch: string | null;
  unit_type: string | null; designations: string[];
  strength_exception_min: number | null; strength_exception_max: number | null; strength_exception_note: string;
  depth: number; active: boolean; version: number;
}
export interface UnitType extends Named {
  id: string; code: string; tier: number; parent_type: string | null; standard_per_parent: number | null;
  reference_min: number | null; reference_max: number | null; description_en: string; description_so: string;
  active: boolean; version: number;
}
export interface Designation extends Named {
  id: string; code: string; description_en: string; description_so: string; active: boolean; version: number;
}
export interface DesignationRule {
  id: string; parent_type: string; child_type: string; designation: string; active: boolean; note: string; version: number;
}
export type StrengthStatus = "no_reference" | "unknown" | "below" | "within" | "above";
export interface StructureRow extends Named {
  id: string; code: string; level: string; active: boolean; parent: string | null; unit_type: string;
  designations: string[]; reference_min: number | null; reference_max: number | null; has_exception: boolean;
  strength_exception_note: string; actual_strength: number | null; strength_status: StrengthStatus;
}
export interface Finding {
  code: "child_count" | "non_standard_parent" | "missing_designated_unit";
  unit: { id: string; code: string; name_en: string; name_so: string };
  type?: string; expected?: number; actual?: number; parent_type?: string; child_type?: string; designation?: string;
}
export interface Branch extends Named { id: string; code: string; active: boolean; version: number }
export interface Rank extends Named {
  id: string; branch: string; category: "enlisted" | "warrant" | "officer" | "unspecified"; code: string; sort_order: number;
  approval_status: "draft" | "approved"; approved_at: string | null; active: boolean; version: number;
}
export interface UserRow {
  id: string; username: string; full_name: string; email: string; preferred_language: Lang; is_active: boolean;
  mfa_enabled: boolean; must_change_password: boolean; last_login: string | null; version: number;
}
export interface Role extends Named { id: string; code: string; is_privileged: boolean; requires_branch: boolean;
  allowed_scope_levels: string[]; permissions: string[] }
export interface AuditEvent {
  id: string; occurred_at: string; actor_username: string; action: string; entity_type: string;
  entity_id: string; outcome: "success" | "failure" | "denied"; correlation_id: string;
}
/** Headcount of one region; `code` is null for the row that groups units outside any region (headquarters). */
export interface RegionHeadcount { code: string | null; name_en: string; name_so: string; total: number; active: number }
/** One calendar day of audit activity; `issues` (failed or denied) is a subset of `events`. */
export interface DayActivity { date: string; events: number; issues: number }
export interface Dashboard {
  scope?: { units_in_scope: number; regions_in_scope: number; branch_commands_in_scope: number };
  ranks?: { draft: number; approved: number };
  accounts?: { active: number; disabled: number; privileged_without_mfa: number };
  audit?: { events_24h: number; failed_logins_24h: number; denied_24h: number; daily?: DayActivity[] };
  personnel?: { total: number; active: number; by_region?: RegionHeadcount[] };
  reports?: { my_open: number; awaiting_review?: number };
  logistics?: { low_stock: number; assets_attention: number };
  training?: { in_progress: number; enrolled: number };
  fleet?: FleetAnalytics;
  equipment?: EquipmentSummary;
}

export interface NamedRef { code: string; name_en: string; name_so: string }
export interface MoneyByCurrency { currency: string; total: string }
export interface FleetAnalytics {
  total: number; decommissioned: number;
  by_group: { code: string; count: number }[];
  by_model?: { code: string; name: string; count: number }[]; without_reference_model?: number;
  by_category: (NamedRef & { count: number; group: string })[];
  by_condition: Record<string, number>;
  by_status: Record<string, number>;
  under_maintenance: number; awaiting_inspection: number; requiring_inspection: number; overdue_maintenance: number;
  available: number; unavailable: number; available_pct: number; without_driver: number; inspection_window_days: number;
  expenditure: { visible: boolean; by_currency: (MoneyByCurrency & { repair: string; service: string; inspection: string; by_month: { month: string; total: string }[] })[] };
}
export interface PpeCategoryTotals extends NamedRef { in_store: number; held: number; damaged: number; lost: number; retired: number }
export interface PpeSummary {
  lines: number; in_store: number; with_personnel: number; holders: number; holding_pairs: number;
  damaged: number; lost: number; retired: number; below_reorder: number;
  by_category: PpeCategoryTotals[];
  inspection: { window_days: number; inspected: number; never_inspected: number; due: number; overdue: number; by_condition: Record<string, number> };
  procurement: { visible: boolean; by_currency: (MoneyByCurrency & { quantity: number })[] };
}
export interface EquipmentSummary {
  assets: number; by_status: Record<string, number>; by_condition: Record<string, number>;
  inspection_due: number; inspection_overdue: number; awaiting_replacement: number; replaced: number;
  acquisition: { visible: boolean; by_currency: (MoneyByCurrency & { assets: number })[] };
  pending_approvals: { categories: number };
  ppe: PpeSummary;
}

export interface RankBrief { id: string; code: string; name_en: string; name_so: string; approval_status: string }
export type PersonnelStatus = "active" | "on_leave" | "suspended" | "jailed" | "died" | "retired" | "discharged";
export interface PersonBrief {
  id: string; full_name: string; service_number: string | null; rank: Pick<RankBrief, "id" | "code" | "name_en" | "name_so">;
}
export interface Person {
  id: string; service_number: string | null; full_name: string; phone: string; branch: BranchBrief;
  org_unit: UnitBrief; rank: RankBrief; status: PersonnelStatus; version: number;
  department?: DepartmentBrief | null;
  /** Reporting line. Present on the detail screen only for people who may read this person's unit. */
  supervisor_id?: string | null;
  supervisor?: PersonBrief | { id: string; restricted: true } | null;
  subordinates?: PersonBrief[];
  /** Managers only. */
  account_username?: string | null;
}
export interface ReportingLinesReport {
  total: number; valid: number; can_commit?: boolean; updated?: number; rows?: { row: number; errors: string[] }[];
}
export interface HistoryEntry {
  id: string; field: "rank" | "org_unit" | "status"; old_label: string; new_label: string;
  effective_date: string; reason: string; recorded_at: string; recorded_by_username: string;
}
export interface ImportPreview {
  batch_id: string; total: number; valid: number; can_commit: boolean; rows: { row: number; errors: string[] }[];
}

export interface ReportType extends Named {
  id: string; code: string; kind: "report" | "request"; figure_keys: string[]; separation_of_duties?: boolean;
  active?: boolean; version?: number;
}
export type SubmissionStatus = "draft" | "submitted" | "under_review" | "approved" | "rejected" | "returned" | "amended";
export interface SubmissionRow {
  id: string; report_type: ReportType; org_unit: UnitBrief; title: string; period_start: string; period_end: string;
  status: SubmissionStatus; version: number; current_revision: number; submitter_username: string;
  submitted_at: string | null; decided_at: string | null; updated_at: string;
}
export interface Capabilities { edit: boolean; submit: boolean; start_review: boolean; decide: boolean; amend: boolean }
export interface SubmissionDetail extends SubmissionRow {
  body: string; figures: Record<string, number>; capabilities: Capabilities; approved_revision_no: number | null;
  revisions: { revision_no: number; title: string; body: string; figures: Record<string, number>;
               submitted_by_username: string; created_at: string }[];
  actions: { id: string; revision_no: number; action: string; from_status: string; to_status: string;
             actor_username: string; comment: string; created_at: string }[];
}
export interface SummaryBucket { submissions: number; totals: Record<string, number> }
export interface Summary {
  consolidated: SummaryBucket; figure_keys: string[];
  regions: (SummaryBucket & { region: { id: string; code: string } & Named })[];
}
export interface NotificationItem {
  id: string; kind: string; created_at: string; read_at: string | null;
  submission: { id: string; title: string; status: string } | null;
}

export interface InvCategory extends Named {
  id: string; code: string; kind: "stock" | "asset"; restricted: boolean; approval_status: "draft" | "approved";
  active: boolean; version: number;
}
export interface CategoryBrief extends Named { id: string; code: string; kind: string; restricted: boolean }
export interface StockLine {
  id: string; category: CategoryBrief; org_unit: UnitBrief; uom: string; quantity: number; reorder_level: number;
  below_reorder: boolean; version: number;
}
export interface StockTxn {
  id: string; kind: string; delta: number; balance_after: number; reason: string;
  counterpart_unit: UnitBrief | null; actor_username: string; created_at: string;
}
export type AssetStatus = "in_stock" | "issued" | "maintenance" | "missing" | "lost" | "retired";
export interface Asset {
  id: string; category: CategoryBrief; org_unit: UnitBrief; identifier: string; description: string; status: AssetStatus;
  issued_to_unit: UnitBrief | null; custodian_username: string | null; version: number;
  manufacturer: string; model: string; condition: "new" | "good" | "fair" | "poor" | "unserviceable";
  /** Null when the user may not see prices. */
  acquisition_cost: string | null; currency: string; acquired_on: string | null; procurement_ref: string;
  last_inspected_on: string | null; next_inspection_due: string | null; replaced_by: string | null;
}
export interface AssetEvt {
  id: string; kind: string; from_status: string; to_status: string; from_unit: UnitBrief | null;
  to_unit: UnitBrief | null; note: string; actor_username: string; created_at: string;
}
export interface ReconLine {
  id: string; kind: "stock" | "asset"; label: string; expected_quantity: number | null;
  counted_quantity: number | null; found: boolean | null;
}
export interface Recon {
  id: string; org_unit: UnitBrief; status: "open" | "completed" | "cancelled"; includes_restricted: boolean;
  started_by_username: string | null; started_at: string; completed_at: string | null; version: number; lines?: ReconLine[];
}
export interface LogisticsSummary {
  rows: { category: CategoryBrief; region: Named & { id: string | null; code: string }; stock_lines: number;
          quantity: number; below_reorder: number; assets: Record<string, number> }[];
}
export interface Course extends Named { id: string; code: string; duration_days: number | null; active: boolean; version: number }
export interface PersonBrief { id: string; full_name: string; org_unit: UnitBrief }
export type TrainingStatus = "enrolled" | "in_progress" | "completed" | "failed" | "withdrawn";
export interface TrainingRec {
  id: string; personnel: PersonBrief; course: { id: string; code: string } & Named; status: TrainingStatus;
  start_date: string; end_date: string | null; completed_on: string | null; notes: string;
  created_by_username: string; version: number;
}
export interface TrainingSummary {
  rows: { course: { id: string; code: string } & Named; region: Named & { id: string | null; code: string };
          counts: Record<string, number>; total: number }[];
}

// ---- 2.0 ----
export interface DistRow { count: number | null; [k: string]: unknown }
export interface Dist<R extends DistRow = DistRow> { total: number | null; rows: R[]; suppressed: boolean }
export interface NamedRow extends DistRow, Named { code: string }
export interface AnalyticsIndex { sections: string[] }
export interface PersonnelAnalytics {
  by_status: Dist<DistRow & { status: string }>; by_rank: Dist<NamedRow>; by_branch: Dist<NamedRow>;
  by_child_unit: Dist<DistRow & { unit: UnitBrief }>; changes_by_month: Dist<DistRow & { month: string; field: string }>;
}
export interface ReportsAnalytics {
  approved_by_type: Dist<NamedRow>; approved_by_month: Dist<DistRow & { month: string }>;
  pipeline?: { by_status: Dist<DistRow & { status: string }>; turnaround_hours: { median: number | null; mean: number | null } };
}
export interface LogisticsAnalytics {
  stock_by_category: Dist<NamedRow>; low_stock_lines: number | null; assets_by_status: Dist<DistRow & { status: string }>;
}
export interface TrainingAnalytics {
  by_course: Dist<NamedRow & { completion_rate: number | null }>; completions_by_month: Dist<DistRow & { month: string }>;
}
export interface TreeNode extends Named { id: string; code: string; level: string; unit_type: string | null; active: boolean; children: TreeNode[] }
export interface IntegrationClient {
  id: string; name: string; description: string; key_prefix: string; scopes: string[]; org_unit: string; org_unit_code: string;
  expires_at: string; status: "active" | "key_revoked" | "key_expired"; revoked_at: string | null; last_used_at: string | null;
  created_by_username: string; version: number; created_at: string; key?: string;
}
export interface IntegrationCall { id: string; at: string; endpoint: string; status_code: number; outcome: string; ip_address: string | null }

export interface StructureOp { op: "create" | "update"; code: string; fields?: Record<string, unknown>; [k: string]: unknown }
export interface StructureProblem { code: string; type?: string; count?: number; units?: number }
export interface StructureChange {
  id: string; title: string; rationale: string; operations: StructureOp[]; status: "draft" | "submitted" | "approved" | "rejected";
  impact: { errors?: StructureProblem[]; affected_units?: number; created?: string[]; updated?: string[] };
  proposed_by_username: string; decided_by_username: string; decision_note: string; submitted_at: string | null;
  decided_at: string | null; version: number; created_at: string;
}

export interface DisciplinaryEntry {
  id: string; category: string; incident_date: string | null; summary: string; outcome: string; voided: boolean;
  corrects: string | null; superseded: boolean; recorded_at: string; recorded_by_username: string;
}
export interface PersonnelDocument {
  id: string; title: string; note: string; category: string; content_type: string; size_bytes: number;
  uploaded_at: string; uploaded_by_username: string;
}
export interface CombinedReport {
  generated_at: string; excludes_restricted_units: boolean;
  totals: { total: number; serving: number };
  branches: (Named & { id: string; code: string; total: number; serving: number; units: number;
    by_status: Record<string, number>; by_rank_category: Record<string, number> })[];
  regions: { region: Named & { id: string; code: string }; serving_by_branch: Record<string, number>; serving: number }[];
  /** One point per recorded day, oldest first. Empty until the first day is recorded. */
  trend?: { date: string; total: number; serving: number }[];
}

export interface DeathEvidence { id: string; title: string; category: string; size_bytes: number }
export interface DeathRecordOut {
  id: string; state: "reported" | "confirmed" | "withdrawn"; date_of_death: string; note: string;
  reported_at: string; reported_by: string; confirmed_at: string | null; confirmed_by: string;
  withdrawn_at: string | null; withdrawn_by: string; withdrawn_reason: string;
  /** Only for officers who may report or confirm deaths. */
  evidence?: DeathEvidence[];
}

export interface AppointmentTypeOut { id: string; code: string; name_en: string; name_so: string; unit_type: string | null; role?: string; exclusive: boolean }
export interface AppointmentOut {
  id: string; appointment_type: { id: string; code: string; name_en: string; name_so: string };
  org_unit: { id: string; code: string; name_en: string; name_so: string };
  effective_from: string; effective_to: string | null; authority_ref: string; current: boolean; created_by: string;
  ended_at: string | null; ended_by: string; end_reason: string; has_access_link: boolean;
  department?: { id: string; code: string; name_en: string; name_so: string } | null;
}

export interface FoodSupplier { id: string; name: string; phone: string; address: string; notes: string; active: boolean; version: number }
export interface FoodBatchOut {
  id: string; org_unit_name: string; category: string; uom: string; supplier: string; batch_ref: string; quantity: number; remaining: number;
  received_on: string; expires_on: string | null; delivery_note_ref: string; order_ref: string; entered_by: string;
}
export interface FoodAllocationOut {
  id: string; status: "issued" | "delivered" | "cancelled"; quantity: number; uom: string; category: string; from_unit_name: string;
  to_unit_name: string; order_ref: string; issuing_officer: string; order_date: string; issue_note_ref: string; issued_by: string;
  issued_at: string; delivered_at: string | null; received_by_name: string; receipt_note_ref: string; cancel_reason: string; version: number;
}
export interface FoodOptions {
  categories: { id: string; code: string; name_en: string; name_so: string }[];
  stores: { id: string; org_unit: string; org_unit_name: string; category: string; category_name: string; quantity: number; uom: string; reorder_level: number }[];
}
export interface FoodWarnings {
  days: number; as_of: string;
  low_stock: { stock_line: string; org_unit: string; category: string; quantity: number; reorder_level: number; uom: string }[];
  expiring: { batch: string; org_unit: string; category: string; remaining: number; uom: string; expires_on: string; expired: boolean; batch_ref: string; supplier: string }[];
  unbatched: { stock_line: string; org_unit: string; category: string; ledger: number; batched: number }[];
}

export interface UnitOverview {
  unit: { id: string; code: string; name_en: string; name_so: string; level: string; unit_type: string | null };
  breadcrumb: { id: string; code: string; name_en: string; name_so: string }[];
  strength: { direct: number; total: number; by_status: Record<string, number> };
  children: { id: string; code: string; name_en: string; name_so: string; level: string; unit_type: string | null; direct: number; total: number }[];
  commanders: { appointment: string; type: string; type_en: string; type_so: string; unit_id: string; unit_code: string;
                holder: { id: string; full_name: string; rank: string; service_number: string | null } | null }[];
  members: { id: string; full_name: string; rank: string; service_number: string | null; status: string }[];
  counts_complete: boolean;
}

export type ChangeKind = "transfer" | "appointment_add" | "appointment_end" | "rank_change" | "status_change";
export type ChangeStatus = "pending" | "in_review" | "approved" | "rejected" | "withdrawn";
export interface ChangeRequest {
  id: string; kind: ChangeKind; status: ChangeStatus; summary: string; payload: Record<string, unknown>; unit: string;
  order_ref: string; issuing_officer: string; order_date: string; batch: string | null; proposed_by: string; created_at: string;
  review_started_at: string | null; decided_by: string; decided_at: string | null; decision_note: string;
  self_approved: boolean; version: number;
}
export interface PersonLookup {
  id: string; full_name: string; service_number: string | null; rank: string; unit: string; unit_id: string; branch_id: string; status: string;
  open_appointments: { id: string; type: string; unit: string }[];
}

export type TaskStatus = "open" | "in_progress" | "completed" | "cancelled";
export interface UnitTaskOut {
  id: string; org_unit: string; org_unit_name: string; title: string; description: string; authority_ref: string;
  assigned_on: string; due_on: string | null; status: TaskStatus; overdue: boolean;
  responsible: { id: string; full_name: string; service_number: string | null; rank: string } | null;
  completion_report: string; document_ref: string; cancel_reason: string; completed_at: string | null; created_by: string; version: number;
  events?: { kind: string; from_status: string; to_status: string; note: string; actor: string; at: string }[];
}
export interface TaskMember { id: string; full_name: string; service_number: string | null; rank: string; unit: string }

// ---- organizational structure (departments, unit profiles, chart, analytics)
export interface DepartmentBrief extends Named { id: string; code: string; restricted: boolean }
export interface Department extends Named {
  id: string; code: string; description_en: string; description_so: string; restricted_roster: boolean; sort_order: number; active: boolean; version: number;
}
export interface FormationRoleRow extends Named { id: string; code: string; tier: number; formation_role: string; active: boolean; version: number }
export interface OrgPerson {
  id: string; full_name: string; service_number: string | null; status: string; rank: { id: string; code: string; name_en: string; name_so: string };
  department: DepartmentBrief | null; org_unit: UnitBrief;
}
export interface OrgOffice {
  id: string; type: string; type_en: string; type_so: string; role: string; effective_from: string; department: DepartmentBrief | null;
  holder: { id: string; full_name: string; service_number: string | null; rank: { code: string; name_en: string; name_so: string } } | null;
}
export interface OrgBucket { total: number; active: number; inactive: number }
export interface OrgUnitBrief extends Named { id: string; code: string; level: string; unit_type: string | null; formation_role: string; is_active: boolean }
export interface OrgRankRow { rank: { id: string; code: string; name_en: string; name_so: string }; sort_order: number; count: number }
export interface OrgFunction { department: DepartmentBrief | null; count: number; active: number; people: OrgPerson[] | null; roster_hidden: boolean }
export interface UnitProfile {
  unit: OrgUnitBrief & { restricted: boolean; version: number; parent: OrgUnitBrief | null };
  breadcrumb: { id: string; code: string; name_en: string; name_so: string }[];
  leadership: { commander: OrgOffice[]; deputy: OrgOffice[]; administrative: OrgOffice[]; other: OrgOffice[] };
  departments: { department: DepartmentBrief; established: boolean; head: OrgOffice | null; deputy: OrgOffice | null; staff: number; active: number; inactive: number }[];
  unassigned_department: OrgBucket & { by_status: Record<string, number> };
  medical: OrgFunction; finance: OrgFunction;
  children: (OrgUnitBrief & OrgBucket & { direct: number })[];
  stats: OrgBucket & { direct: number; by_status: Record<string, number> };
  by_rank: OrgRankRow[];
  can: { name: boolean; manage: boolean; appoint: boolean; restricted: boolean };
  counts_complete: boolean;
}
export interface DepartmentProfile {
  unit: OrgUnitBrief; department: DepartmentBrief & { description_en: string; description_so: string };
  established: boolean; head: OrgOffice | null; deputy: OrgOffice | null; stats: OrgBucket & { by_status: Record<string, number> };
  staff: OrgPerson[] | null; assigned: OrgPerson[] | null; staff_total: number; assigned_total: number; roster_hidden: boolean;
  can: { name: boolean; manage: boolean; appoint: boolean };
}
export interface ChartNode extends OrgUnitBrief, OrgBucket { children: ChartNode[] }
export interface OrgAnalytics {
  totals: OrgBucket & { by_status: Record<string, number> };
  by_formation: Record<string, (OrgUnitBrief & OrgBucket & { parent_id: string | null })[]>;
  departments: { department: DepartmentBrief; established_in: number; with_head: number; with_deputy: number; total: number; active: number; inactive: number }[];
  unassigned_department: OrgBucket;
  leadership: { units: number; with_commander: number; with_deputy: number; vacancies: (OrgUnitBrief & { missing: string[] })[]; vacancies_total: number };
  by_rank: OrgRankRow[]; counts_complete: boolean;
}
export interface UnitDepartmentRow { id: string; unit: string; department: Department; note: string; active: boolean; version: number }
export interface AppointmentTypeRow extends Named { id: string; code: string; unit_type: string | null; role: string; exclusive: boolean }
