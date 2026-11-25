import type { PdfContent } from "../components/ExportPdfButton";

/** Printable custody documents, built in the browser from the record the person can already see. The paper original stays the legal copy;
 *  these are reprints of what the register holds. Printing is audited on the server (POST /detention/{id}/print/). */
type T = (key: never, vars?: Record<string, string | number>) => string;
interface Named { name_en: string; name_so: string }
export interface DocRecord {
  register_no: string; detainee_name: string; detainee_alias: string; sex: string; age_years: number | null; id_ref: string; address: string;
  org_unit: Named | null; booked_at: string; arrest_place: string; arresting_officer_name: string; reason: string; authority_ref: string;
  case_ref: string; charge: string; facility: Named | null; cell: string; property_held: string; health_note: string; status: string;
  ended_at: string | null; outcome: string; destination: string; outcome_ref: string; outcome_note: string; held_hours: number;
  events: { occurred_at: string; kind: string; text: string; by: string }[];
  hearings: { purpose: string; hearing_at: string | null; court: string; ordered_by: string; remand_until: string | null; status: string }[];
}
const stamp = (s: string | null) => (s ? s.slice(0, 16).replace("T", " ") : "—");
const BLANK = "______________________________";

export function custodyRecordDoc(d: DocRecord, t: T, name: (n: Named) => string): PdfContent {
  const L = (k: string) => t(k as never);
  const kv = (rows: [string, string][]) => ({ columns: [{ header: L("doc.field"), width: 1 }, { header: L("doc.value"), width: 2 }], rows: rows.filter((r) => r[1]) });
  return {
    title: `${L("doc.custodyRecord")} ${d.register_no}`, subtitle: L("doc.copyNote"),
    sections: [
      kv([[L("det.name"), [d.detainee_name, d.detainee_alias].filter(Boolean).join(" / ")], [L("det.sex"), d.sex === "unknown" ? "" : L(`det.sex.${d.sex}`)],
        [L("det.age"), d.age_years != null ? String(d.age_years) : ""], [L("det.idRef"), d.id_ref], [L("det.address"), d.address],
        [L("det.station"), d.org_unit ? name(d.org_unit) : ""], [L("det.booked"), stamp(d.booked_at)], [L("det.arrestPlace"), d.arrest_place],
        [L("det.officer"), d.arresting_officer_name], [L("det.reason"), d.reason], [L("det.authority"), d.authority_ref], [L("det.caseRef"), d.case_ref],
        [L("det.charge"), d.charge], [L("det.facility"), [d.facility ? name(d.facility) : "", d.cell].filter(Boolean).join(" · ")],
        [L("det.property"), d.property_held], [L("det.health"), d.health_note], [L("det.state"), L(`det.status.${d.status}`)],
        ...(d.ended_at ? [[L("det.outcome"), `${L(`det.outcome.${d.outcome}`)}${d.destination ? ` → ${d.destination}` : ""}${d.outcome_ref ? ` (${d.outcome_ref})` : ""} · ${stamp(d.ended_at)}`] as [string, string]] : [])]),
      ...(d.hearings.length ? [{ heading: L("det.court"), columns: [{ header: L("det.hearingPurpose"), width: 1 }, { header: L("det.hearingAt"), width: 1 }, { header: L("det.court"), width: 1 },
        { header: L("det.orderedBy"), width: 1 }, { header: L("det.remandUntil"), width: 1 }, { header: L("det.state"), width: 1 }],
        rows: d.hearings.map((h) => [L(`det.purpose.${h.purpose}`), stamp(h.hearing_at), h.court, h.ordered_by, h.remand_until ?? "", L(`det.hearing.${h.status}`)]) }] : []),
      { heading: L("det.log"), columns: [{ header: L("doc.time"), width: 1 }, { header: L("det.eventKind"), width: 1 }, { header: L("det.eventText"), width: 3 }, { header: L("doc.by"), width: 1 }],
        rows: d.events.map((e) => [stamp(e.occurred_at), L(`det.event.${e.kind}`), e.text, e.by]) },
    ],
  };
}

export function propertyReceiptDoc(d: DocRecord, t: T, name: (n: Named) => string): PdfContent {
  const L = (k: string) => t(k as never);
  return {
    title: `${L("doc.propertyReceipt")} ${d.register_no}`, subtitle: L("doc.copyNote"),
    sections: [
      { columns: [{ header: L("doc.field"), width: 1 }, { header: L("doc.value"), width: 2 }], rows: [
        [L("det.name"), d.detainee_name], [L("det.station"), d.org_unit ? name(d.org_unit) : ""], [L("det.booked"), stamp(d.booked_at)],
        [L("det.property"), d.property_held || L("doc.propertyNone")]] },
      { heading: L("doc.signatures"), columns: [{ header: "", width: 1 }, { header: "", width: 2 }], rows: [
        [L("doc.signDetainee"), BLANK], [L("doc.signOfficer"), BLANK], [L("doc.date"), BLANK]] },
    ],
  };
}

export function releaseNoteDoc(d: DocRecord, t: T, name: (n: Named) => string): PdfContent {
  const L = (k: string) => t(k as never);
  return {
    title: `${L("doc.releaseNote")} ${d.register_no}`, subtitle: L("doc.copyNote"),
    sections: [
      { columns: [{ header: L("doc.field"), width: 1 }, { header: L("doc.value"), width: 2 }], rows: ([
        [L("det.name"), d.detainee_name], [L("det.idRef"), d.id_ref], [L("det.station"), d.org_unit ? name(d.org_unit) : ""], [L("det.booked"), stamp(d.booked_at)],
        [L("det.outcome"), d.outcome ? L(`det.outcome.${d.outcome}`) : ""], [L("det.destination"), d.destination], [L("det.outcomeRef"), d.outcome_ref],
        [L("det.outcomeNote"), d.outcome_note], [L("doc.leftAt"), stamp(d.ended_at)], [L("det.held"), `${d.held_hours} h`], [L("det.property"), d.property_held]] as [string, string][]).filter((r) => r[1]) },
      { heading: L("doc.signatures"), columns: [{ header: "", width: 1 }, { header: "", width: 2 }], rows: [
        [L("doc.signOfficer"), BLANK], [L("doc.signReceiver"), BLANK], [L("doc.date"), BLANK]] },
    ],
  };
}
