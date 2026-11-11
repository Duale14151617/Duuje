using System.Text.Json;
using Duale.Api.Data;
using Duale.Api.Domain;
using Microsoft.EntityFrameworkCore;
namespace Duale.Api.Services;

public record OutboxMessage(Guid Id, string Type, string AggregateType, string AggregateId, Guid? CompanyId, string Payload, DateTime CreatedAt);

// Implement and register one of these per consumer (webhook, message bus, e-mail bridge...) once the integration is chosen.
// Delivery is at-least-once: use OutboxMessage.Id as the idempotency key. Throw to request a retry.
public interface IOutboxPublisher
{
    Task PublishAsync(OutboxMessage message, CancellationToken ct);
}

public static class Outbox
{
    // Adds to the current unit of work, so the event commits atomically with the change it describes (or not at all).
    public static void Add(AppDbContext db, string type, string aggregateType, string aggregateId, Guid? companyId, object? payload = null) =>
        db.OutboxEvents.Add(new OutboxEvent
        {
            Type = type, AggregateType = aggregateType, AggregateId = aggregateId, CompanyId = companyId,
            Payload = payload is null ? "{}" : JsonSerializer.Serialize(payload)
        });
}

public class OutboxDispatcher(AppDbContext db, IEnumerable<IOutboxPublisher> publishers, IConfiguration cfg, ILogger<OutboxDispatcher> log)
{
    public static TimeSpan Backoff(int attempts) => TimeSpan.FromSeconds(Math.Min(3600, 30 * Math.Pow(2, Math.Min(attempts, 10))));

    // No publisher registered = nothing is consumed yet: events stay Pending (visible in /platform/overview) rather than being
    // marked published. Once a publisher is registered the backlog drains in creation order.
    public async Task<int> RunOnceAsync(DateTime now, CancellationToken ct)
    {
        var list = publishers.ToList();
        if (list.Count == 0) return 0;
        var max = int.TryParse(cfg["Outbox:MaxAttempts"], out var m) && m > 0 ? m : 8;
        var batch = await db.OutboxEvents.Where(x => x.Status == "Pending" && x.NextAttemptAt <= now).OrderBy(x => x.CreatedAt).Take(100).ToListAsync(ct);
        var done = 0;
        foreach (var ev in batch)
        {
            var msg = new OutboxMessage(ev.Id, ev.Type, ev.AggregateType, ev.AggregateId, ev.CompanyId, ev.Payload, ev.CreatedAt);
            try
            {
                foreach (var p in list) await p.PublishAsync(msg, ct);
                ev.Status = "Published"; ev.PublishedAt = now; ev.LastError = null; done++;
            }
            catch (Exception ex) when (ex is not OperationCanceledException)
            {
                ev.Attempts++;
                ev.LastError = ex.Message.Length > 500 ? ex.Message[..500] : ex.Message;
                if (ev.Attempts >= max) ev.Status = "Dead"; else ev.NextAttemptAt = now + Backoff(ev.Attempts);
                log.LogWarning("Outbox event {Id} ({Type}) failed attempt {N}: {Err}", ev.Id, ev.Type, ev.Attempts, ev.LastError);
            }
            await db.SaveChangesAsync(ct);
        }
        return done;
    }
}
