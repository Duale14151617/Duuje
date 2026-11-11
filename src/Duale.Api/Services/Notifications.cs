using Duale.Api.Data;
using Duale.Api.Domain;
using Microsoft.EntityFrameworkCore;
namespace Duale.Api.Services;

public record DeliveryMessage(string Channel, string Address, string Title, string Body, string DeliveryId);
public record SendResult(bool Ok, string? ProviderMessageId = null, string? Error = null, bool Permanent = false);

// Provider integrations (email, SMS, ...) are not chosen yet, so none is registered by default. A provider must treat
// DeliveryId as an idempotency key: the worker is at-least-once and may call twice after a crash.
public interface INotificationProvider
{
    string Channel { get; }
    Task<SendResult> SendAsync(DeliveryMessage message, CancellationToken ct);
}

public record DispatchResult(int FannedOut, int Sent, int Retried, int Dead);

public class NotificationDispatcher(AppDbContext db, IEnumerable<INotificationProvider> providers, IConfiguration cfg)
{
    int MaxAttempts => int.TryParse(cfg["Notifications:MaxAttempts"], out var v) && v > 0 ? v : 6;
    int BackoffSeconds => int.TryParse(cfg["Notifications:BackoffSeconds"], out var v) && v > 0 ? v : 30;
    public IReadOnlySet<string> Channels => providers.Select(p => p.Channel).ToHashSet();

    public async Task<DispatchResult> RunOnceAsync(DateTime now, CancellationToken ct)
    {
        var fanned = await FanOutAsync(now, ct);
        int sent = 0, retried = 0, dead = 0;
        var due = await db.Deliveries.Where(d => d.Status == "Pending" && d.NextAttemptAt <= now).OrderBy(d => d.NextAttemptAt).Take(100).ToListAsync(ct);
        foreach (var d in due)
        {
            var n = await db.Notifications.FirstAsync(x => x.Id == d.NotificationId, ct);
            var provider = providers.FirstOrDefault(p => p.Channel == d.Channel);
            var address = await AddressAsync(d, ct);
            SendResult result;
            if (address is null) result = new SendResult(false, null, "The recipient has no address for this channel.", true);
            else if (provider is null) result = new SendResult(false, null, "No provider is configured for this channel.");
            else
            {
                try { result = await provider.SendAsync(new DeliveryMessage(d.Channel, address, n.Title, n.Body, d.Id.ToString()), ct); }
                catch (Exception ex) when (ex is not OperationCanceledException) { result = new SendResult(false, null, ex.GetType().Name + ": " + ex.Message); }
            }
            d.Attempts++;
            if (result.Ok) { d.Status = "Sent"; d.SentAt = now; d.ProviderMessageId = result.ProviderMessageId; d.LastError = null; sent++; }
            else
            {
                d.LastError = Truncate(result.Error);
                if (result.Permanent || d.Attempts >= MaxAttempts) { d.Status = "Dead"; dead++; }
                else { d.NextAttemptAt = now.AddSeconds(Math.Min(BackoffSeconds * Math.Pow(2, d.Attempts - 1), 6 * 3600)); retried++; }
            }
            await db.SaveChangesAsync(ct);   // one save per delivery: a crash repeats at most one send (providers dedupe on DeliveryId)
        }
        return new DispatchResult(fanned, sent, retried, dead);
    }

    async Task<int> FanOutAsync(DateTime now, CancellationToken ct)
    {
        var channels = Channels.ToList();
        var pending = await db.Notifications.Where(n => n.FannedOutAt == null).OrderBy(n => n.CreatedAt).Take(200).ToListAsync(ct);
        var count = 0;
        foreach (var n in pending)
        {
            if (channels.Count > 0)
            {
                var enabled = await db.NotificationPreferences.Where(p => p.UserId == n.UserId && p.Enabled && channels.Contains(p.Channel)).Select(p => p.Channel).ToListAsync(ct);
                foreach (var ch in enabled) { db.Deliveries.Add(new NotificationDelivery { NotificationId = n.Id, UserId = n.UserId, Channel = ch, NextAttemptAt = now }); count++; }
            }
            n.FannedOutAt = now;
        }
        if (pending.Count > 0) await db.SaveChangesAsync(ct);
        return count;
    }

    async Task<string?> AddressAsync(NotificationDelivery d, CancellationToken ct) => d.Channel switch
    {
        "email" => await db.Users.Where(u => u.Id == d.UserId).Select(u => u.Email).FirstOrDefaultAsync(ct),
        "sms" => await db.Technicians.Where(t => t.UserId == d.UserId).Select(t => t.Phone).FirstOrDefaultAsync(ct),
        _ => null
    };
    static string? Truncate(string? s) => s is null ? null : s.Length > 500 ? s[..500] : s;
}

// Time-based reminders. Each reminder carries a dedupe key, so running the job again (or on two instances) never repeats one.
public class ReminderService(AppDbContext db, IConfiguration cfg)
{
    int Int(string key, int def) => int.TryParse(cfg[key], out var v) && v > 0 ? v : def;

    public async Task<int> RunOnceAsync(DateTime now, CancellationToken ct)
    {
        var created = 0;
        async Task Once(string key, Guid userId, Guid? companyId, string kind, string title, string body)
        {
            var full = $"{key}:{userId:N}";
            if (await db.Notifications.AnyAsync(n => n.DedupeKey == full, ct) || db.Notifications.Local.Any(n => n.DedupeKey == full)) return;
            db.Notifications.Add(new Notification { UserId = userId, CompanyId = companyId, Kind = kind, Title = title, Body = body, DedupeKey = full });
            created++;
        }

        // 1. Technician: an accepted job is about to start.
        var leadHours = Int("Reminders:JobLeadHours", 2);
        var soon = await (from a in db.Assignments join j in db.Jobs on a.JobId equals j.Id join t in db.Technicians on a.TechnicianId equals t.Id
                          where a.Status == AssignmentStatus.Accepted && j.Status == JobStatus.Accepted && j.ScheduledStart > now && j.ScheduledStart <= now.AddHours(leadHours)
                          select new { a.Id, j.Reference, j.ScheduledStart, j.CompanyId, t.UserId }).ToListAsync(ct);
        foreach (var s in soon) await Once($"job-start:{s.Id}", s.UserId, s.CompanyId, "reminder.job_start", "Job starting soon", $"Job {s.Reference} starts at {s.ScheduledStart:u}.");

        // 2. Technician: an approved skill is about to expire.
        var days = Int("Reminders:SkillExpiryDays", 14);
        var today = DateOnly.FromDateTime(now);
        var limit = today.AddDays(days);
        var expiring = await (from ts in db.TechnicianSkills join t in db.Technicians on ts.TechnicianId equals t.Id join s in db.Skills on ts.SkillId equals s.Id
                              where ts.Verification == VerificationStatus.Approved && ts.ExpiresOn != null && ts.ExpiresOn >= today && ts.ExpiresOn <= limit
                              select new { ts.TechnicianId, ts.SkillId, ts.ExpiresOn, t.UserId, s.Name }).ToListAsync(ct);
        foreach (var e in expiring) await Once($"skill-exp:{e.TechnicianId:N}:{e.SkillId:N}:{e.ExpiresOn:yyyyMMdd}", e.UserId, null, "reminder.skill_expiry", "Qualification expiring", $"Your verification for {e.Name} expires on {e.ExpiresOn:yyyy-MM-dd}.");

        // 3. Reviewers: work has been waiting for review too long.
        var reviewHours = Int("Reminders:ReviewHours", 24);
        var waiting = await db.Jobs.Where(j => j.Status == JobStatus.AwaitingReview).ToListAsync(ct);
        foreach (var j in waiting)
        {
            var since = await db.JobStatusHistory.Where(h => h.JobId == j.Id && h.ToStatus == JobStatus.AwaitingReview).MaxAsync(h => (DateTime?)h.At, ct);
            if (since is null || since.Value > now.AddHours(-reviewHours)) continue;
            foreach (var u in await Notifier.HolderIdsAsync(db, j.CompanyId, "job.review", ct))
                await Once($"review-wait:{j.Id:N}", u, j.CompanyId, "reminder.review_waiting", "Review overdue", $"Job {j.Reference} has been waiting for review for over {reviewHours} hours.");
        }

        // 4. Finance: an approved company payable has no payment yet.
        var payDays = Int("Reminders:PayableDays", 3);
        var payables = await db.Payables.Where(p => p.Status == "Approved" && p.PayerType == "company" && p.ApprovedAt != null && p.ApprovedAt <= now.AddDays(-payDays)).ToListAsync(ct);
        foreach (var p in payables)
        {
            var pays = await db.Payments.Where(x => x.PayableId == p.Id).ToListAsync(ct);
            if (FinanceMath.Settle(p.Amount, pays).State is "Paid" or "Settled") continue;
            foreach (var u in await Notifier.HolderIdsAsync(db, p.CompanyId, "finance.payment", ct))
                await Once($"payable-due:{p.Id:N}", u, p.CompanyId, "reminder.payable_unpaid", "Technician payment outstanding", $"A payable of {p.Amount} {p.Currency} has been approved for over {payDays} days and is not fully paid.");
        }
        if (created > 0) await db.SaveChangesAsync(ct);
        return created;
    }
}

// Runs fan-out, delivery with retries and reminders on a timer. Disabled in tests (Worker:Enabled=false) which call the services directly.
public class MaintenanceWorker(IServiceScopeFactory scopes, IConfiguration cfg, ILogger<MaintenanceWorker> log) : BackgroundService
{
    protected override async Task ExecuteAsync(CancellationToken stop)
    {
        var interval = TimeSpan.FromSeconds(int.TryParse(cfg["Worker:IntervalSeconds"], out var s) && s > 0 ? s : 30);
        while (!stop.IsCancellationRequested)
        {
            try
            {
                using var scope = scopes.CreateScope();
                await scope.ServiceProvider.GetRequiredService<ReminderService>().RunOnceAsync(DateTime.UtcNow, stop);
                await scope.ServiceProvider.GetRequiredService<NotificationDispatcher>().RunOnceAsync(DateTime.UtcNow, stop);
                await scope.ServiceProvider.GetRequiredService<OutboxDispatcher>().RunOnceAsync(DateTime.UtcNow, stop);
                if (DateTime.UtcNow.Minute == 0) await scope.ServiceProvider.GetRequiredService<RetentionService>().PurgeAsync(DateTime.UtcNow, stop);   // roughly hourly
            }
            catch (Exception ex) when (ex is not OperationCanceledException) { log.LogError(ex, "Maintenance cycle failed; will retry next interval."); }
            try { await Task.Delay(interval, stop); } catch (OperationCanceledException) { }
        }
    }
}
