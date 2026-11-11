namespace Duale.Api.Domain;

public class NotificationPreference
{
    public Guid UserId { get; set; }
    public string Channel { get; set; } = "";            // email | sms (only channels with a configured provider can be enabled)
    public bool Enabled { get; set; }
    public DateTime UpdatedAt { get; set; } = DateTime.UtcNow;
}

// The persistent delivery queue. The in-app Notification row is the event (committed with the change that caused it);
// deliveries are created from it by the worker, one per (notification, channel), and retried with backoff.
public class NotificationDelivery
{
    public Guid Id { get; set; } = Guid.NewGuid();
    public Guid NotificationId { get; set; }
    public Guid UserId { get; set; }
    public string Channel { get; set; } = "";
    public string Status { get; set; } = "Pending";      // Pending | Sent | Dead
    public int Attempts { get; set; }
    public DateTime NextAttemptAt { get; set; } = DateTime.UtcNow;
    public string? LastError { get; set; }
    public string? ProviderMessageId { get; set; }
    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
    public DateTime? SentAt { get; set; }
}
