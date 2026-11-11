namespace Duale.Api.Domain;

// Spec: "use an outbox pattern for reliable event delivery". A row is written in the same transaction as the change it
// describes; the worker publishes it to whatever IOutboxPublisher implementations are registered (none are chosen yet).
// Delivery is at-least-once: consumers must de-duplicate on Id. Payload must never contain secrets or documents.
public class OutboxEvent
{
    public Guid Id { get; set; } = Guid.NewGuid();
    public string Type { get; set; } = "";               // e.g. job.offered, job.approved, finance.payment_confirmed
    public string AggregateType { get; set; } = "";
    public string AggregateId { get; set; } = "";
    public Guid? CompanyId { get; set; }
    public string Payload { get; set; } = "{}";
    public string Status { get; set; } = "Pending";      // Pending | Published | Dead
    public int Attempts { get; set; }
    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
    public DateTime NextAttemptAt { get; set; } = DateTime.UtcNow;
    public DateTime? PublishedAt { get; set; }
    public string? LastError { get; set; }
}

// A record that a company holds a platform subscription for a period. The revenue model (subscription vs per-job fee)
// is an undecided business matter, so this stores what finance staff record and applies NO pricing or billing rules.
public class PlatformSubscription : IVersioned
{
    public Guid Id { get; set; } = Guid.NewGuid();
    public Guid CompanyId { get; set; }
    public string PlanLabel { get; set; } = "";          // free text; the plan catalogue is a business decision
    public decimal Amount { get; set; }                  // 0 allowed (e.g. a trial)
    public string Currency { get; set; } = "";
    public DateOnly PeriodStart { get; set; }
    public DateOnly PeriodEnd { get; set; }              // inclusive
    public string Status { get; set; } = "Active";       // Active | Cancelled
    public string? Note { get; set; }
    public string? CancelReason { get; set; }
    public Guid CreatedBy { get; set; }
    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
    public Guid? CancelledBy { get; set; }
    public DateTime? CancelledAt { get; set; }
    public int Seq { get; set; }
}

// Metadata about an external provider integration (email, SMS, payment, storage, identity). It never holds a secret:
// SecretRef is only the NAME of the entry in the secrets store / environment. Enabling an account does not by itself add
// provider code; a matching provider implementation must be registered in Program.cs.
public class IntegrationAccount
{
    public Guid Id { get; set; } = Guid.NewGuid();
    public string Kind { get; set; } = "";               // email | sms | payment | storage | identity
    public string Provider { get; set; } = "";
    public string DisplayName { get; set; } = "";
    public string? SecretRef { get; set; }
    public string Status { get; set; } = "Disabled";     // Disabled | Enabled
    public string? Note { get; set; }
    public Guid CreatedBy { get; set; }
    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
    public Guid? UpdatedBy { get; set; }
    public DateTime? UpdatedAt { get; set; }
}
