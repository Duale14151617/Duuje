namespace Duale.Api.Domain;

public enum TermsStatus { Draft, Approved, Superseded }
public enum PaymentStatus { Initiated, Confirmed, Failed, Reversed }

// Rows that guard concurrent money movement carry a token: two requests touching the same invoice, payable or refund
// at once cannot both succeed (the second SaveChanges fails and the caller retries against fresh state).
public interface IVersioned { int Seq { get; set; } }

// Versioned and never edited once approved; a change is a new version.
public class JobFinancialTerms
{
    public Guid Id { get; set; } = Guid.NewGuid();
    public Guid CompanyId { get; set; }
    public Guid JobId { get; set; }
    public int Version { get; set; }
    public string Currency { get; set; } = "";
    public decimal CustomerCharge { get; set; }
    public decimal TechnicianCompensation { get; set; }
    public decimal PlatformFee { get; set; }            // amount only; the platform revenue model is a business decision
    public string PayerType { get; set; } = "company";   // who pays the technician: company | customer (direct)
    public TermsStatus Status { get; set; } = TermsStatus.Draft;
    public string? Note { get; set; }
    public Guid ProposedBy { get; set; }
    public DateTime ProposedAt { get; set; } = DateTime.UtcNow;
    public Guid? ApprovedBy { get; set; }
    public DateTime? ApprovedAt { get; set; }
}

public class Invoice : IVersioned
{
    public Guid Id { get; set; } = Guid.NewGuid();
    public Guid CompanyId { get; set; }
    public Guid JobId { get; set; }
    public Guid CustomerId { get; set; }
    public Guid TermsId { get; set; }
    public string Number { get; set; } = "";
    public string Currency { get; set; } = "";
    public decimal Total { get; set; }
    public string Status { get; set; } = "Issued";       // Issued | Void
    public Guid IssuedBy { get; set; }
    public DateTime IssuedAt { get; set; } = DateTime.UtcNow;
    public Guid? VoidedBy { get; set; }
    public DateTime? VoidedAt { get; set; }
    public string? VoidReason { get; set; }
    public int Seq { get; set; }
}

public class InvoiceLine
{
    public Guid Id { get; set; } = Guid.NewGuid();
    public Guid InvoiceId { get; set; }
    public string Description { get; set; } = "";
    public decimal Quantity { get; set; }
    public decimal UnitPrice { get; set; }
    public decimal Amount { get; set; }
}

// What the payer owes the technician for a job. PayerType "company" = company-paid; "customer" = direct customer-to-technician.
// Paid/settled state is derived from payment records, never stored, so it cannot drift.
public class TechnicianPayable : IVersioned
{
    public Guid Id { get; set; } = Guid.NewGuid();
    public Guid CompanyId { get; set; }
    public Guid JobId { get; set; }
    public Guid TechnicianId { get; set; }
    public Guid TermsId { get; set; }
    public string PayerType { get; set; } = "company";
    public string Currency { get; set; } = "";
    public decimal Amount { get; set; }
    public string Status { get; set; } = "Accrued";      // Accrued -> Approved (company-paid needs finance review) | Cancelled
    public Guid? ApprovedBy { get; set; }
    public DateTime? ApprovedAt { get; set; }
    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
    public int Seq { get; set; }
}

public class PaymentRecord
{
    public Guid Id { get; set; } = Guid.NewGuid();
    public Guid CompanyId { get; set; }
    public Guid JobId { get; set; }
    public string Reference { get; set; } = "";
    public string Kind { get; set; } = "";               // customer_collection | technician_payout | direct_customer_to_technician | refund
    public Guid? InvoiceId { get; set; }
    public Guid? PayableId { get; set; }
    public Guid? RefundId { get; set; }
    public string PayerType { get; set; } = "";
    public string PayeeType { get; set; } = "";
    public string Method { get; set; } = "";
    public string Currency { get; set; } = "";
    public decimal Amount { get; set; }
    public PaymentStatus Status { get; set; } = PaymentStatus.Initiated;
    public string? ProviderRef { get; set; }
    public string? AcknowledgedBy { get; set; }          // cash: who acknowledged receipt
    public string? Note { get; set; }
    public bool Verified { get; set; }                   // true only for a signed provider confirmation; self-reported cash is false
    public Guid? RecordedBy { get; set; }
    public DateTime InitiatedAt { get; set; } = DateTime.UtcNow;
    public Guid? ConfirmedBy { get; set; }
    public DateTime? ConfirmedAt { get; set; }
    public Guid? ReversedBy { get; set; }
    public DateTime? ReversedAt { get; set; }
    public string? ReverseReason { get; set; }
    public bool Reconciled { get; set; }
    public Guid? ReconciledBy { get; set; }
    public DateTime? ReconciledAt { get; set; }
    public string? ReconcileNote { get; set; }
}

// Attempt history: append-only.
public class PaymentEvent
{
    public Guid Id { get; set; } = Guid.NewGuid();
    public Guid PaymentId { get; set; }
    public string Event { get; set; } = "";
    public Guid? ActorUserId { get; set; }
    public string? Note { get; set; }
    public DateTime At { get; set; } = DateTime.UtcNow;
}

public class Refund : IVersioned
{
    public Guid Id { get; set; } = Guid.NewGuid();
    public Guid CompanyId { get; set; }
    public Guid JobId { get; set; }
    public Guid InvoiceId { get; set; }
    public string Currency { get; set; } = "";
    public decimal Amount { get; set; }
    public string Reason { get; set; } = "";
    public string Status { get; set; } = "Requested";    // Requested | Approved | Rejected  (paid state derived from payments)
    public Guid RequestedBy { get; set; }
    public DateTime RequestedAt { get; set; } = DateTime.UtcNow;
    public Guid? DecidedBy { get; set; }
    public DateTime? DecidedAt { get; set; }
    public string? DecisionNote { get; set; }
    public int Seq { get; set; }
}

// Immutable, balanced per transaction and currency. Corrections are new rows that reverse earlier ones.
public class LedgerEntry
{
    public Guid Id { get; set; } = Guid.NewGuid();
    public Guid CompanyId { get; set; }
    public string TxnKey { get; set; } = "";             // groups the lines of one posting
    public string LineKey { get; set; } = "";            // TxnKey#n, unique: the same posting cannot be made twice
    public string AccountCode { get; set; } = "";
    public decimal Debit { get; set; }
    public decimal Credit { get; set; }
    public string Currency { get; set; } = "";
    public string SourceType { get; set; } = "";
    public string SourceId { get; set; } = "";
    public string? ReversesLineKey { get; set; }
    public Guid? ActorUserId { get; set; }
    public DateTime At { get; set; } = DateTime.UtcNow;
}

public class PlatformFeeRecord
{
    public Guid Id { get; set; } = Guid.NewGuid();
    public Guid CompanyId { get; set; }
    public Guid JobId { get; set; }
    public string Currency { get; set; } = "";
    public decimal Amount { get; set; }
    public string Status { get; set; } = "Accrued";      // Accrued | Settled | Waived
    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
    public Guid? DecidedBy { get; set; }
    public DateTime? DecidedAt { get; set; }
    public string? Note { get; set; }
}

public class Dispute
{
    public Guid Id { get; set; } = Guid.NewGuid();
    public Guid CompanyId { get; set; }
    public Guid JobId { get; set; }
    public Guid? PayableId { get; set; }
    public Guid? PaymentId { get; set; }
    public Guid RaisedBy { get; set; }
    public string Description { get; set; } = "";
    public string Status { get; set; } = "Open";         // Open | Resolved
    public string? Outcome { get; set; }                 // upheld | rejected | adjusted
    public string? Resolution { get; set; }              // any adjustment is posted separately and referenced here
    public Guid? DecidedBy { get; set; }
    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
    public DateTime? ResolvedAt { get; set; }
}
