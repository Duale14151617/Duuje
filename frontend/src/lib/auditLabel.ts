/** Turns a raw audit action such as "attendance.read_summary" into plain words ("Viewed attendance summary").
 *  The raw name stays available (tooltip / audit log) for anyone who needs the exact code. */
const EXACT: Record<string, string> = {
  "auth.login": "Signed in",
  "auth.password_reset": "Password reset",
  "access.denied": "Access denied",
  "personnel.create": "Added a person",
  "personnel.transfer": "Transferred a person",
  "personnel.export": "Exported personnel",
  "audit.read": "Viewed the audit log",
};

const VERBS: Record<string, string> = {
  read: "Viewed", view: "Viewed", list: "Listed", create: "Created", update: "Updated", approve: "Approved",
  issue: "Issued", receive: "Received", register: "Registered", export: "Exported", import: "Imported",
  download: "Downloaded", propose: "Proposed", disable: "Disabled", revise: "Revised", swap: "Swapped",
  authorize: "Authorised", reveal: "Revealed", confirm: "Confirmed", reported: "Reported",
};

const words = (s: string) => s.split("_").filter(Boolean);

export function auditLabel(action: string): string {
  if (!action) return "-";
  const exact = EXACT[action];
  if (exact) return exact;
  const [domain, ...rest] = action.split(".");
  const tail = words(rest.join("_"));
  if (!domain || tail.length === 0) return words(domain || action).join(" ").replace(/^./, (c) => c.toUpperCase());
  const verb = VERBS[tail[0]];
  const d = words(domain).join(" ");
  const out = verb ? [verb, d, ...tail.slice(1)].join(" ") : [d, ...tail].join(" ");
  return out.charAt(0).toUpperCase() + out.slice(1);
}
