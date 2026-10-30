import { describe, expect, it } from "vitest";
import { auditLabel } from "./auditLabel";

describe("auditLabel", () => {
  it("uses fixed wording for common events", () => {
    expect(auditLabel("auth.login")).toBe("Signed in");
    expect(auditLabel("access.denied")).toBe("Access denied");
  });
  it("turns read/view style actions into plain sentences", () => {
    expect(auditLabel("attendance.read_summary")).toBe("Viewed attendance summary");
    expect(auditLabel("disciplinary.view")).toBe("Viewed disciplinary");
    expect(auditLabel("document.list")).toBe("Listed document");
  });
  it("falls back to readable words and never returns an empty string", () => {
    expect(auditLabel("personnel.appointment_created")).toBe("Personnel appointment created");
    expect(auditLabel("")).toBe("-");
    expect(auditLabel("weird")).toBe("Weird");
  });
});
