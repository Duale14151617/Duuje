using System.Security.Claims;
using Duale.Api.Auth;
using Duale.Api.Data;
using Duale.Api.Domain;
using Duale.Api.Services;
using Microsoft.EntityFrameworkCore;
using static Duale.Api.Endpoints;
using static Duale.Api.Phase2Endpoints;
namespace Duale.Api;

public record PreferenceReq(string? Channel, bool Enabled);

public static class Phase5Endpoints
{
    const int RowCap = 20000;   // reports aggregate in memory (decimal-safe on every provider); past this, move them to SQL views

    static (DateTime From, DateTime To) Window(DateTime? since, DateTime? until) =>
        (since ?? DateTime.UtcNow.AddDays(-30), until ?? DateTime.UtcNow.AddDays(1));

    public static void Map(RouteGroupBuilder api)
    {
        // ======== Operational reports (company-scoped; company id is part of every query) ========
        api.MapGet("/companies/{id:guid}/reports/jobs", async Task<IResult> (Guid id, DateTime? since, DateTime? until, ClaimsPrincipal p, AppDbContext db, AccessService access, CancellationToken ct) =>
        {
            if (Deny(await access.Company(Uid(p), id, "report.read", ct)) is { } d) return d;
            var (f, t) = Window(since, until);
            var jobs = await db.Jobs.Where(j => j.CompanyId == id && j.CreatedAt >= f && j.CreatedAt < t).Take(RowCap).ToListAsync(ct);
            var ids = jobs.Select(j => j.Id).ToList();
            var assignments = await db.Assignments.Where(a => ids.Contains(a.JobId)).ToListAsync(ct);
            var complaints = await db.JobComplaints.Where(c => c.CompanyId == id && c.CreatedAt >= f && c.CreatedAt < t).ToListAsync(ct);
            var callbacks = await db.JobRelationships.CountAsync(r => ids.Contains(r.ParentJobId), ct);
            var done = jobs.Where(j => j.CompletedAt != null).Select(j => (j.CompletedAt!.Value - j.CreatedAt).TotalHours).ToList();
            var offered = assignments.Count;
            var accepted = assignments.Count(a => a.RespondedAt != null && a.Status != AssignmentStatus.Declined);
            var declined = assignments.Count(a => a.Status == AssignmentStatus.Declined);
            return Results.Ok(new
            {
                period = new { from = f, to = t }, total = jobs.Count,
                byStatus = jobs.GroupBy(j => j.Status).ToDictionary(g => g.Key.ToString(), g => g.Count()),
                byPriority = jobs.GroupBy(j => j.Priority).ToDictionary(g => g.Key.ToString(), g => g.Count()),
                byDay = jobs.GroupBy(j => j.CreatedAt.Date).OrderBy(g => g.Key).Select(g => new { day = g.Key.ToString("yyyy-MM-dd"), count = g.Count() }),
                cancelled = jobs.Count(j => j.Status == JobStatus.Cancelled),
                cancellationRate = jobs.Count == 0 ? 0 : Math.Round((double)jobs.Count(j => j.Status == JobStatus.Cancelled) / jobs.Count, 4),
                completed = done.Count, avgHoursToComplete = done.Count == 0 ? (double?)null : Math.Round(done.Average(), 2),
                offers = new { offered, accepted, declined, acceptanceRate = offered == 0 ? (double?)null : Math.Round((double)accepted / offered, 4) },
                complaints = new { total = complaints.Count, open = complaints.Count(c => c.Status == "Open") },
                callbacks, truncated = jobs.Count == RowCap
            });
        });

        api.MapGet("/companies/{id:guid}/reports/technicians", async Task<IResult> (Guid id, DateTime? since, DateTime? until, ClaimsPrincipal p, AppDbContext db, AccessService access, CancellationToken ct) =>
        {
            if (Deny(await access.Company(Uid(p), id, "report.read", ct)) is { } d) return d;
            var (f, t) = Window(since, until);
            var techs = await (from r in db.Relationships join tc in db.Technicians on r.TechnicianId equals tc.Id where r.CompanyId == id && r.Status == RelationshipStatus.Active select new { tc.Id, tc.DisplayName, type = r.Type.ToString() }).ToListAsync(ct);
            var ids = techs.Select(x => x.Id).ToList();
            var rows = await (from a in db.Assignments join j in db.Jobs on a.JobId equals j.Id
                              where j.CompanyId == id && ids.Contains(a.TechnicianId) && a.OfferedAt >= f && a.OfferedAt < t
                              select new { a.TechnicianId, a.Status, a.ScheduledStart, a.ScheduledEnd, JobStatus = j.Status }).ToListAsync(ct);
            var windows = await db.Availability.Where(w => ids.Contains(w.TechnicianId) && w.EndsAt > f && w.StartsAt < t).ToListAsync(ct);
            var result = techs.Select(x =>
            {
                var mine = rows.Where(r => r.TechnicianId == x.Id).ToList();
                var worked = mine.Where(r => r.Status == AssignmentStatus.Accepted && r.JobStatus != JobStatus.Cancelled).Sum(r => (r.ScheduledEnd - r.ScheduledStart).TotalHours);
                var available = windows.Where(w => w.TechnicianId == x.Id).Sum(w => (Min(w.EndsAt, t) - Max(w.StartsAt, f)).TotalHours);
                return new
                {
                    technicianId = x.Id, name = x.DisplayName, relationship = x.type,
                    offered = mine.Count, accepted = mine.Count(r => r.Status == AssignmentStatus.Accepted), declined = mine.Count(r => r.Status == AssignmentStatus.Declined),
                    completed = mine.Count(r => r.Status == AssignmentStatus.Accepted && r.JobStatus == JobStatus.Completed),
                    scheduledHours = Math.Round(worked, 2), availableHours = Math.Round(available, 2),
                    utilization = available <= 0 ? (double?)null : Math.Round(Math.Min(1, worked / available), 4)
                };
            }).OrderByDescending(x => x.scheduledHours);
            return Results.Ok(new { period = new { from = f, to = t }, technicians = result });
        });

        // Finance report: one block per currency (currencies are never added together); each figure lists the source records it came from.
        api.MapGet("/companies/{id:guid}/reports/finance", async Task<IResult> (Guid id, DateTime? since, DateTime? until, ClaimsPrincipal p, AppDbContext db, AccessService access, CancellationToken ct) =>
        {
            if (Deny(await access.Company(Uid(p), id, "finance.read", ct)) is { } d) return d;
            var (f, t) = Window(since, until);
            var invoices = await db.Invoices.Where(x => x.CompanyId == id && x.IssuedAt >= f && x.IssuedAt < t).Take(RowCap).ToListAsync(ct);
            var payments = await db.Payments.Where(x => x.CompanyId == id && x.InitiatedAt >= f && x.InitiatedAt < t).Take(RowCap).ToListAsync(ct);
            var payables = await db.Payables.Where(x => x.CompanyId == id && x.CreatedAt >= f && x.CreatedAt < t).Take(RowCap).ToListAsync(ct);
            var fees = await db.PlatformFees.Where(x => x.CompanyId == id && x.CreatedAt >= f && x.CreatedAt < t).ToListAsync(ct);
            var refunds = await db.Refunds.Where(x => x.CompanyId == id && x.RequestedAt >= f && x.RequestedAt < t).ToListAsync(ct);
            var openDisputes = await db.Disputes.Where(x => x.CompanyId == id && x.Status == "Open" && x.PayableId != null).Select(x => x.PayableId!.Value).ToListAsync(ct);
            var currencies = invoices.Select(x => x.Currency).Concat(payments.Select(x => x.Currency)).Concat(payables.Select(x => x.Currency)).Concat(fees.Select(x => x.Currency)).Distinct().OrderBy(x => x).ToList();
            static List<Guid> Ids(IEnumerable<Guid> g) => g.Take(100).ToList();

            var blocks = currencies.Select(cur =>
            {
                var inv = invoices.Where(x => x.Currency == cur && x.Status != "Void").ToList();
                var pay = payments.Where(x => x.Currency == cur).ToList();
                var collections = pay.Where(x => x.Kind == "customer_collection").ToList();
                var payouts = pay.Where(x => x.Kind == "technician_payout").ToList();
                var direct = pay.Where(x => x.Kind == "direct_customer_to_technician").ToList();
                var refundPays = pay.Where(x => x.Kind == "refund").ToList();
                var pb = payables.Where(x => x.Currency == cur && x.Status != "Cancelled").ToList();
                var companyPb = pb.Where(x => x.PayerType == "company").ToList();
                var directPb = pb.Where(x => x.PayerType == "customer").ToList();
                decimal Sum(IEnumerable<PaymentRecord> q, PaymentStatus s) => q.Where(x => x.Status == s).Sum(x => x.Amount);
                var collected = Sum(collections, PaymentStatus.Confirmed);
                var paidOut = Sum(payouts, PaymentStatus.Confirmed);
                var directPaid = Sum(direct, PaymentStatus.Confirmed);
                var disputedPb = pb.Where(x => openDisputes.Contains(x.Id)).ToList();
                return new
                {
                    currency = cur,
                    receivables = new { invoiced = inv.Sum(x => x.Total), collected, pendingCollections = Sum(collections, PaymentStatus.Initiated), outstanding = inv.Sum(x => x.Total) - collected, sources = new { invoices = Ids(inv.Select(x => x.Id)), payments = Ids(collections.Select(x => x.Id)) } },
                    technicianPayables = new { accrued = companyPb.Sum(x => x.Amount), approved = companyPb.Where(x => x.Status == "Approved").Sum(x => x.Amount), paid = paidOut, pendingPayouts = Sum(payouts, PaymentStatus.Initiated), outstanding = companyPb.Where(x => x.Status == "Approved").Sum(x => x.Amount) - paidOut, sources = new { payables = Ids(companyPb.Select(x => x.Id)), payments = Ids(payouts.Select(x => x.Id)) } },
                    directPayments = new { agreed = directPb.Sum(x => x.Amount), confirmed = directPaid, selfReportedUnverified = direct.Where(x => x.Status == PaymentStatus.Confirmed && !x.Verified).Sum(x => x.Amount), outstanding = directPb.Sum(x => x.Amount) - directPaid, sources = new { payables = Ids(directPb.Select(x => x.Id)), payments = Ids(direct.Select(x => x.Id)) } },
                    refunds = new { requested = refunds.Where(x => x.Currency == cur && x.Status == "Requested").Sum(x => x.Amount), approved = refunds.Where(x => x.Currency == cur && x.Status == "Approved").Sum(x => x.Amount), paid = Sum(refundPays, PaymentStatus.Confirmed), sources = new { refunds = Ids(refunds.Where(x => x.Currency == cur).Select(x => x.Id)) } },
                    paymentsByStatus = pay.GroupBy(x => x.Status).ToDictionary(g => g.Key.ToString(), g => new { count = g.Count(), amount = g.Sum(x => x.Amount) }),
                    disputed = new { count = disputedPb.Count, amount = disputedPb.Sum(x => x.Amount), sources = new { payables = Ids(disputedPb.Select(x => x.Id)) } },
                    platformFees = new { accrued = fees.Where(x => x.Currency == cur && x.Status == "Accrued").Sum(x => x.Amount), settled = fees.Where(x => x.Currency == cur && x.Status == "Settled").Sum(x => x.Amount), waived = fees.Where(x => x.Currency == cur && x.Status == "Waived").Sum(x => x.Amount), sources = new { fees = Ids(fees.Where(x => x.Currency == cur).Select(x => x.Id)) } },
                    unreconciled = new { count = pay.Count(x => x.Status == PaymentStatus.Confirmed && !x.Reconciled), amount = pay.Where(x => x.Status == PaymentStatus.Confirmed && !x.Reconciled).Sum(x => x.Amount) }
                };
            }).ToList();
            return Results.Ok(new { period = new { from = f, to = t }, currencies = blocks, truncated = invoices.Count == RowCap || payments.Count == RowCap || payables.Count == RowCap });
        });

        // ======== Notification preferences and read-all ========
        api.MapGet("/notifications/preferences", async Task<IResult> (ClaimsPrincipal p, AppDbContext db, NotificationDispatcher dispatcher, CancellationToken ct) =>
        {
            var uid = Uid(p);
            var prefs = await db.NotificationPreferences.Where(x => x.UserId == uid).ToListAsync(ct);
            return Results.Ok(new { availableChannels = dispatcher.Channels.OrderBy(x => x), preferences = prefs.Select(x => new { x.Channel, x.Enabled }) });
        });

        api.MapPut("/notifications/preferences", async Task<IResult> (PreferenceReq r, ClaimsPrincipal p, AppDbContext db, NotificationDispatcher dispatcher, CancellationToken ct) =>
        {
            var uid = Uid(p);
            var ch = (r.Channel ?? "").Trim().ToLowerInvariant();
            if (r.Enabled && !dispatcher.Channels.Contains(ch)) return Results.Conflict(new { error = $"No delivery provider is configured for '{ch}', so it cannot be enabled yet." });
            if (!r.Enabled && ch is not ("email" or "sms")) return Bad("channel must be email or sms.");
            var row = await db.NotificationPreferences.FirstOrDefaultAsync(x => x.UserId == uid && x.Channel == ch, ct);
            if (row is null) db.NotificationPreferences.Add(new NotificationPreference { UserId = uid, Channel = ch, Enabled = r.Enabled });
            else { row.Enabled = r.Enabled; row.UpdatedAt = DateTime.UtcNow; }
            await db.SaveChangesAsync(ct);
            return Results.NoContent();
        });

        api.MapPost("/notifications/read-all", async Task<IResult> (ClaimsPrincipal p, AppDbContext db, CancellationToken ct) =>
        {
            var uid = Uid(p);
            var unread = await db.Notifications.Where(n => n.UserId == uid && n.ReadAt == null).ToListAsync(ct);
            foreach (var n in unread) n.ReadAt = DateTime.UtcNow;
            await db.SaveChangesAsync(ct);
            return Results.Ok(new { marked = unread.Count });
        });

        // ======== Platform oversight ========
        api.MapGet("/platform/overview", async Task<IResult> (ClaimsPrincipal p, AppDbContext db, AccessService access, CancellationToken ct) =>
        {
            if (!await access.HasPlatform(Uid(p), "platform.oversight", ct)) return Forbidden();
            var companies = await db.Companies.GroupBy(c => c.Verification).Select(g => new { g.Key, n = g.Count() }).ToListAsync(ct);
            var activeCompanies = await db.Companies.CountAsync(c => c.Status == AccountStatus.Active, ct);
            var technicians = await db.Technicians.CountAsync(ct);
            var pendingDocs = await db.TechnicianDocuments.CountAsync(x => x.Status == VerificationStatus.Pending, ct);
            var pendingSkills = await db.TechnicianSkills.CountAsync(x => x.Verification == VerificationStatus.Pending, ct);
            var jobs = await db.Jobs.GroupBy(j => j.Status).Select(g => new { g.Key, n = g.Count() }).ToListAsync(ct);
            var deliveries = await db.Deliveries.GroupBy(x => x.Status).Select(g => new { g.Key, n = g.Count() }).ToListAsync(ct);
            var oldest = await db.Deliveries.Where(x => x.Status == "Pending").MinAsync(x => (DateTime?)x.NextAttemptAt, ct);
            var openDisputes = await db.Disputes.CountAsync(x => x.Status == "Open", ct);
            var outbox = await db.OutboxEvents.GroupBy(x => x.Status).Select(g => new { g.Key, n = g.Count() }).ToListAsync(ct);
            return Results.Ok(new
            {
                outbox = outbox.ToDictionary(x => x.Key, x => x.n),
                companies = new { byVerification = companies.ToDictionary(x => x.Key.ToString(), x => x.n), active = activeCompanies },
                technicians = new { total = technicians },
                verificationQueues = new { companies = companies.Where(x => x.Key == VerificationStatus.Pending).Select(x => x.n).FirstOrDefault(), technicianDocuments = pendingDocs, technicianSkills = pendingSkills },
                jobsByStatus = jobs.ToDictionary(x => x.Key.ToString(), x => x.n),
                notificationQueue = new { byStatus = deliveries.ToDictionary(x => x.Key, x => x.n), oldestPendingAttemptAt = oldest },
                openDisputes
            });
        });

        api.MapGet("/platform/notifications/deliveries", async Task<IResult> (string? status, ClaimsPrincipal p, AppDbContext db, AccessService access, CancellationToken ct) =>
        {
            if (!await access.HasPlatform(Uid(p), "platform.oversight", ct)) return Forbidden();
            var q = db.Deliveries.AsQueryable();
            if (status is not null) q = q.Where(x => x.Status == status);
            // No message bodies: oversight sees delivery health, not people's notifications.
            return Results.Ok(await q.OrderByDescending(x => x.CreatedAt).Take(100).Select(x => new { x.Id, x.Channel, x.Status, x.Attempts, x.NextAttemptAt, x.LastError, x.CreatedAt, x.SentAt }).ToListAsync(ct));
        });

        api.MapPost("/platform/notifications/deliveries/{did:guid}/retry", async Task<IResult> (Guid did, ClaimsPrincipal p, AppDbContext db, AccessService access, HttpContext http, CancellationToken ct) =>
        {
            var uid = Uid(p);
            if (!await access.HasPlatform(uid, "platform.oversight", ct)) return Forbidden();
            var x = await db.Deliveries.FirstOrDefaultAsync(y => y.Id == did, ct); if (x is null) return Results.NotFound();
            if (x.Status != "Dead") return Results.Conflict(new { error = $"Only dead deliveries can be retried; this one is {x.Status}." });
            x.Status = "Pending"; x.Attempts = 0; x.NextAttemptAt = DateTime.UtcNow; x.LastError = null;
            db.Audit(http, uid, "notification.delivery_retried", "notification_delivery", x.Id.ToString());
            await db.SaveChangesAsync(ct);
            return Results.Ok(new { x.Id, x.Status });
        });
    }

    static DateTime Min(DateTime a, DateTime b) => a < b ? a : b;
    static DateTime Max(DateTime a, DateTime b) => a > b ? a : b;
}
