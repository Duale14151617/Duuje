using System.Security.Claims;
using System.Text.RegularExpressions;
using Duale.Api.Auth;
using Duale.Api.Data;
using Duale.Api.Domain;
using Duale.Api.Services;
using Microsoft.EntityFrameworkCore;
using static Duale.Api.Endpoints;
namespace Duale.Api;

public record SubscriptionReq(string? PlanLabel, decimal Amount, string? Currency, DateOnly PeriodStart, DateOnly PeriodEnd, string? Note);
public record IntegrationReq(string? Kind, string? Provider, string? DisplayName, string? SecretRef, string? Note);
public record IntegrationStatusReq(bool Enabled);

public static class Phase7Endpoints
{
    static IResult Err(int code, string m) => Results.Json(new { error = m }, statusCode: code);
    static readonly string[] Kinds = ["email", "sms", "payment", "storage", "identity"];
    static readonly Regex SecretName = new("^[A-Za-z0-9_.:-]{1,100}$", RegexOptions.Compiled);

    static async Task<IResult> Guard(Func<Task<IResult>> action)
    {
        try { return await action(); }
        catch (DbUpdateException) { return Err(409, "Another change to this record happened at the same time, or it duplicates an existing record. Reload and retry."); }
    }

    static object SubDto(PlatformSubscription s) => new { s.Id, s.CompanyId, s.PlanLabel, s.Amount, s.Currency, s.PeriodStart, s.PeriodEnd, s.Status, s.Note, s.CancelReason, s.CreatedAt, s.CancelledAt };

    public static void Map(RouteGroupBuilder api)
    {
        // ======== Payable cancellation (company finance; needs finance.adjust) ========
        // Only when no payment is initiated or confirmed (reverse or fail those first) and no dispute is open.
        // An approved company-paid accrual is reversed in the ledger; nothing is deleted.
        api.MapPost("/companies/{id:guid}/payables/{pid:guid}/cancel", async Task<IResult> (Guid id, Guid pid, ReasonReq r, ClaimsPrincipal p, AppDbContext db, AccessService access, HttpContext http, CancellationToken ct) =>
            await Guard(async () =>
            {
                var uid = Uid(p);
                if (Deny(await access.Company(uid, id, "finance.adjust", ct)) is { } d) return d;
                if (string.IsNullOrWhiteSpace(r.Reason) || r.Reason.Trim().Length > 500) return Bad("reason is required (max 500 characters).");
                var x = await db.Payables.FirstOrDefaultAsync(y => y.Id == pid && y.CompanyId == id, ct); if (x is null) return Results.NotFound();
                if (x.Status == "Cancelled") return Err(409, "This payable is already cancelled.");
                if (await db.Disputes.AnyAsync(y => y.PayableId == pid && y.Status == "Open", ct)) return Err(409, "This payable has an open dispute; resolve it first.");
                var live = await db.Payments.AnyAsync(y => y.PayableId == pid && (y.Status == PaymentStatus.Initiated || y.Status == PaymentStatus.Confirmed), ct);
                if (live) return Err(409, "Payments exist for this payable. Fail or reverse them before cancelling.");
                var accrued = x.Status == "Approved" && x.PayerType == "company";
                x.Status = "Cancelled"; x.Seq++;
                if (accrued) await Ledger.ReverseAsync(db, id, $"payable-accrue:{x.Id}", $"payable-cancel:{x.Id}", "payable", x.Id.ToString(), uid, ct);
                var techUser = await db.Technicians.Where(t => t.Id == x.TechnicianId).Select(t => t.UserId).FirstAsync(ct);
                Notifier.Notify(db, techUser, id, "finance.payable_cancelled", "Payment cancelled", $"A payment of {x.Amount} {x.Currency} was cancelled. Reason: {r.Reason.Trim()}");
                db.Audit(http, uid, "finance.payable_cancelled", "payable", x.Id.ToString(), id, new { x.Amount, x.Currency, reason = r.Reason.Trim(), ledgerReversed = accrued });
                Outbox.Add(db, "finance.payable_cancelled", "payable", x.Id.ToString(), id, new { x.JobId, x.Amount, x.Currency });
                await db.SaveChangesAsync(ct);
                return Results.Ok(new { x.Id, status = x.Status, ledgerReversed = accrued });
            }));

        // ======== Platform subscriptions: a record kept by platform finance. No pricing or billing logic (revenue model undecided). ========
        api.MapPost("/platform/companies/{cid:guid}/subscriptions", async Task<IResult> (Guid cid, SubscriptionReq r, ClaimsPrincipal p, AppDbContext db, AccessService access, IConfiguration cfg, HttpContext http, CancellationToken ct) =>
            await Guard(async () =>
            {
                var uid = Uid(p);
                if (!await access.HasPlatform(uid, "platform.finance", ct)) return Forbidden();
                var label = r.PlanLabel?.Trim();
                if (string.IsNullOrEmpty(label) || label.Length > 100) return Bad("planLabel is required (max 100 characters).");
                if (!Money.ValidOrZero(r.Amount)) return Bad("amount must be zero or positive with at most 4 decimals.");
                var cur = Money.Currency(cfg, r.Currency); if (cur is null) return Bad("currency is not allowed.");
                if (r.PeriodEnd < r.PeriodStart) return Bad("periodEnd must not be before periodStart.");
                if (r.PeriodEnd.DayNumber - r.PeriodStart.DayNumber > 3660) return Bad("A subscription period cannot exceed ten years.");
                if (r.Note is { Length: > 500 }) return Bad("note is too long.");
                if (!await db.Companies.AnyAsync(c => c.Id == cid, ct)) return Results.NotFound();
                var overlap = await db.Subscriptions.AnyAsync(s => s.CompanyId == cid && s.Status == "Active" && s.PeriodStart <= r.PeriodEnd && s.PeriodEnd >= r.PeriodStart, ct);
                if (overlap) return Err(409, "An active subscription already covers part of this period. Cancel it first.");
                var s = new PlatformSubscription { CompanyId = cid, PlanLabel = label, Amount = r.Amount, Currency = cur, PeriodStart = r.PeriodStart, PeriodEnd = r.PeriodEnd, Note = r.Note?.Trim(), CreatedBy = uid };
                db.Subscriptions.Add(s);
                db.Audit(http, uid, "platform.subscription_recorded", "subscription", s.Id.ToString(), cid, new { s.PlanLabel, s.Amount, s.Currency, s.PeriodStart, s.PeriodEnd });
                Outbox.Add(db, "platform.subscription_recorded", "subscription", s.Id.ToString(), cid, new { s.PlanLabel, s.PeriodStart, s.PeriodEnd });
                await db.SaveChangesAsync(ct);
                return Results.Created($"/platform/subscriptions/{s.Id}", SubDto(s));
            }));

        api.MapGet("/platform/subscriptions", async Task<IResult> (Guid? companyId, string? status, ClaimsPrincipal p, AppDbContext db, AccessService access, CancellationToken ct) =>
        {
            if (!await access.HasPlatform(Uid(p), "platform.finance", ct)) return Forbidden();
            var q = db.Subscriptions.AsQueryable();
            if (companyId is { } c) q = q.Where(s => s.CompanyId == c);
            if (status is not null) q = q.Where(s => s.Status == status);
            var rows = await q.OrderByDescending(s => s.CreatedAt).Take(200).ToListAsync(ct);
            return Results.Ok(rows.Select(SubDto));
        });

        api.MapPost("/platform/subscriptions/{sid:guid}/cancel", async Task<IResult> (Guid sid, ReasonReq r, ClaimsPrincipal p, AppDbContext db, AccessService access, HttpContext http, CancellationToken ct) =>
            await Guard(async () =>
            {
                var uid = Uid(p);
                if (!await access.HasPlatform(uid, "platform.finance", ct)) return Forbidden();
                if (string.IsNullOrWhiteSpace(r.Reason) || r.Reason.Trim().Length > 500) return Bad("reason is required (max 500 characters).");
                var s = await db.Subscriptions.FirstOrDefaultAsync(x => x.Id == sid, ct); if (s is null) return Results.NotFound();
                if (s.Status != "Active") return Err(409, $"This subscription is {s.Status}.");
                s.Status = "Cancelled"; s.CancelReason = r.Reason.Trim(); s.CancelledBy = uid; s.CancelledAt = DateTime.UtcNow; s.Seq++;
                db.Audit(http, uid, "platform.subscription_cancelled", "subscription", s.Id.ToString(), s.CompanyId, new { reason = s.CancelReason });
                Outbox.Add(db, "platform.subscription_cancelled", "subscription", s.Id.ToString(), s.CompanyId);
                await db.SaveChangesAsync(ct);
                return Results.Ok(SubDto(s));
            }));

        // A company can see its own subscription records (read only). The company id is part of the query.
        api.MapGet("/companies/{id:guid}/subscription", async Task<IResult> (Guid id, ClaimsPrincipal p, AppDbContext db, AccessService access, CancellationToken ct) =>
        {
            if (Deny(await access.Company(Uid(p), id, "company.read", ct)) is { } d) return d;
            var today = DateOnly.FromDateTime(DateTime.UtcNow);
            var rows = await db.Subscriptions.Where(s => s.CompanyId == id).OrderByDescending(s => s.PeriodStart).Take(50).ToListAsync(ct);
            var current = rows.FirstOrDefault(s => s.Status == "Active" && s.PeriodStart <= today && s.PeriodEnd >= today);
            return Results.Ok(new { current = current is null ? null : SubDto(current), history = rows.Select(SubDto) });
        });

        // ======== Integration accounts: metadata only, never secret values ========
        api.MapGet("/platform/integrations", async Task<IResult> (ClaimsPrincipal p, AppDbContext db, AccessService access, CancellationToken ct) =>
        {
            if (!await access.HasPlatform(Uid(p), "integration.manage", ct)) return Forbidden();
            var rows = await db.IntegrationAccounts.OrderBy(x => x.Kind).ThenBy(x => x.DisplayName).ToListAsync(ct);
            return Results.Ok(rows.Select(x => new { x.Id, x.Kind, x.Provider, x.DisplayName, x.SecretRef, x.Status, x.Note, x.CreatedAt, x.UpdatedAt }));
        });

        api.MapPost("/platform/integrations", async Task<IResult> (IntegrationReq r, ClaimsPrincipal p, AppDbContext db, AccessService access, HttpContext http, CancellationToken ct) =>
            await Guard(async () =>
            {
                var uid = Uid(p);
                if (!await access.HasPlatform(uid, "integration.manage", ct)) return Forbidden();
                var kind = r.Kind?.Trim().ToLowerInvariant();
                if (kind is null || !Kinds.Contains(kind)) return Bad("kind must be one of: " + string.Join(", ", Kinds));
                var provider = r.Provider?.Trim(); var name = r.DisplayName?.Trim();
                if (string.IsNullOrEmpty(provider) || provider.Length > 60) return Bad("provider is required (max 60 characters).");
                if (string.IsNullOrEmpty(name) || name.Length > 120) return Bad("displayName is required (max 120 characters).");
                var secret = string.IsNullOrWhiteSpace(r.SecretRef) ? null : r.SecretRef.Trim();
                if (secret is not null && !SecretName.IsMatch(secret)) return Bad("secretRef must be the NAME of a secret (letters, digits, _ . : -), never its value.");
                if (r.Note is { Length: > 500 }) return Bad("note is too long.");
                var a = new IntegrationAccount { Kind = kind, Provider = provider, DisplayName = name, SecretRef = secret, Note = r.Note?.Trim(), CreatedBy = uid };
                db.IntegrationAccounts.Add(a);
                db.Audit(http, uid, "platform.integration_created", "integration", a.Id.ToString(), null, new { a.Kind, a.Provider, a.DisplayName });
                await db.SaveChangesAsync(ct);
                return Results.Created($"/platform/integrations/{a.Id}", new { a.Id, a.Kind, a.Provider, a.DisplayName, a.SecretRef, a.Status });
            }));

        api.MapPost("/platform/integrations/{aid:guid}/status", async Task<IResult> (Guid aid, IntegrationStatusReq r, ClaimsPrincipal p, AppDbContext db, AccessService access, HttpContext http, CancellationToken ct) =>
        {
            var uid = Uid(p);
            if (!await access.HasPlatform(uid, "integration.manage", ct)) return Forbidden();
            var a = await db.IntegrationAccounts.FirstOrDefaultAsync(x => x.Id == aid, ct); if (a is null) return Results.NotFound();
            if (r.Enabled && a.SecretRef is null && a.Kind is "payment" or "email" or "sms") return Err(409, "Set a secretRef before enabling a provider that needs credentials.");
            a.Status = r.Enabled ? "Enabled" : "Disabled"; a.UpdatedBy = uid; a.UpdatedAt = DateTime.UtcNow;
            db.Audit(http, uid, "platform.integration_status_changed", "integration", a.Id.ToString(), null, new { a.Status });
            await db.SaveChangesAsync(ct);
            return Results.Ok(new { a.Id, a.Status });
        });

        // ======== Outbox oversight (no payloads exposed) ========
        api.MapGet("/platform/outbox", async Task<IResult> (string? status, ClaimsPrincipal p, AppDbContext db, AccessService access, CancellationToken ct) =>
        {
            if (!await access.HasPlatform(Uid(p), "platform.oversight", ct)) return Forbidden();
            var q = db.OutboxEvents.AsQueryable();
            if (status is not null) q = q.Where(x => x.Status == status);
            var rows = await q.OrderByDescending(x => x.CreatedAt).Take(200).ToListAsync(ct);
            return Results.Ok(rows.Select(x => new { x.Id, x.Type, x.AggregateType, x.AggregateId, x.CompanyId, x.Status, x.Attempts, x.NextAttemptAt, x.LastError, x.CreatedAt, x.PublishedAt }));
        });

        api.MapPost("/platform/outbox/{oid:guid}/retry", async Task<IResult> (Guid oid, ClaimsPrincipal p, AppDbContext db, AccessService access, HttpContext http, CancellationToken ct) =>
        {
            var uid = Uid(p);
            if (!await access.HasPlatform(uid, "platform.oversight", ct)) return Forbidden();
            var x = await db.OutboxEvents.FirstOrDefaultAsync(y => y.Id == oid, ct); if (x is null) return Results.NotFound();
            if (x.Status != "Dead") return Err(409, $"Only Dead events can be retried; this one is {x.Status}.");
            x.Status = "Pending"; x.Attempts = 0; x.NextAttemptAt = DateTime.UtcNow;
            db.Audit(http, uid, "platform.outbox_retried", "outbox_event", x.Id.ToString(), x.CompanyId);
            await db.SaveChangesAsync(ct);
            return Results.Ok(new { x.Id, x.Status });
        });
    }
}
