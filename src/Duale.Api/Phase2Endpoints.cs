using System.Data;
using System.Security.Claims;
using Duale.Api.Auth;
using Duale.Api.Data;
using Duale.Api.Domain;
using Duale.Api.Services;
using Microsoft.EntityFrameworkCore;
using static Duale.Api.Endpoints;
namespace Duale.Api;

public record InviteReq(string? TechnicianEmail, string? Type, DateTimeOffset? ValidFrom, DateTimeOffset? ValidTo);
public record RelActionReq(string? Action);
public record RespondReq(bool Accept, string? Reason);
public record WindowReq(DateTimeOffset StartsAt, DateTimeOffset EndsAt);
public record CustomerReq(string? Name, string? Phone, string? Email, string? ContactPreference);
public record LocationReq(string? Label, string? Address, double? Latitude, double? Longitude, string? AccessInstructions, Guid? ServiceAreaId = null);
public record JobReq(Guid CustomerId, Guid LocationId, Guid TradeId, string? Description, string? Priority, DateTimeOffset ScheduledStart, DateTimeOffset ScheduledEnd, List<Guid>? RequiredSkillIds, int? WarrantyDays = null);
public record RescheduleReq(DateTimeOffset ScheduledStart, DateTimeOffset ScheduledEnd, string? Reason);
public record ReasonReq(string? Reason);
public record OfferReq(Guid TechnicianId);
public record ReassignReq(Guid TechnicianId, string? Reason);

public static class Phase2Endpoints
{
    internal static IResult NotApproved() => Results.Conflict(new { error = "Company must be approved first." });
    internal static Task<bool> IsApproved(AppDbContext db, Guid companyId, CancellationToken ct) =>
        db.Companies.AnyAsync(c => c.Id == companyId && c.Verification == VerificationStatus.Approved, ct);
    static async Task<Technician?> Me(AppDbContext db, ClaimsPrincipal p, CancellationToken ct)
    {
        var uid = Uid(p);
        return await db.Technicians.FirstOrDefaultAsync(t => t.UserId == uid, ct);
    }
    // Company id is always part of the lookup, so an id from another tenant is simply "not found".
    internal static Task<Job?> LoadJob(AppDbContext db, Guid companyId, Guid jobId, CancellationToken ct) =>
        db.Jobs.FirstOrDefaultAsync(j => j.Id == jobId && j.CompanyId == companyId, ct);
    internal static Task<JobAssignment?> ActiveAssignment(AppDbContext db, Guid jobId, CancellationToken ct) =>
        db.Assignments.FirstOrDefaultAsync(a => a.JobId == jobId && (a.Status == AssignmentStatus.Offered || a.Status == AssignmentStatus.Accepted), ct);
    static Task<bool> HasOpenAssignments(AppDbContext db, Guid technicianId, Guid companyId, CancellationToken ct) =>
        (from a in db.Assignments
         join j in db.Jobs on a.JobId equals j.Id
         where a.TechnicianId == technicianId && j.CompanyId == companyId
               && (a.Status == AssignmentStatus.Offered || a.Status == AssignmentStatus.Accepted)
         select a.Id).AnyAsync(ct);
    internal static string NewReference() => $"J-{DateTime.UtcNow:yyMMdd}-{Guid.NewGuid().ToString("N")[..6].ToUpperInvariant()}";
    static bool IsConcurrencyFailure(Exception ex) => ex is DbUpdateException || ex.GetType().Name == "PostgresException";

    public static void Map(RouteGroupBuilder api)
    {
        // ======== Technician <-> company relationships ========
        api.MapPost("/companies/{id:guid}/relationships", async Task<IResult> (Guid id, InviteReq r, ClaimsPrincipal p, AppDbContext db, AccessService access, IConfiguration cfg, HttpContext http, CancellationToken ct) =>
        {
            var uid = Uid(p);
            if (Deny(await access.Company(uid, id, "relationship.manage", ct)) is { } d) return d;
            if (!await IsApproved(db, id, ct)) return NotApproved();
            if (!Enum.TryParse<RelationshipType>(r.Type, true, out var type)) return Bad("type must be Employed or Independent.");
            var email = (r.TechnicianEmail ?? "").Trim().ToLowerInvariant();
            var tech = await (from u in db.Users join t in db.Technicians on u.Id equals t.UserId
                              where u.Email == email && u.Status == AccountStatus.Active select t).FirstOrDefaultAsync(ct);
            if (tech is null) return Results.NotFound(new { error = "No technician profile for that email." });
            // Required by default: a technician must have a verified phone number before a company can invite them.
            // Escape hatch: set Verification__RequirePhoneForInvites=false (e.g. while no SMS provider can deliver codes yet).
            if (cfg["Verification:RequirePhoneForInvites"] != "false" && tech.PhoneVerifiedAt is null)
                return Results.Conflict(new { error = "This technician has not verified their phone number yet. Ask them to verify it in their profile, then invite them again." });
            var skills = await db.TechnicianSkills.Where(s => s.TechnicianId == tech.Id).ToListAsync(ct);
            if (!skills.Any(s => s.IsEligible(DateOnly.FromDateTime(DateTime.UtcNow))))
                return Results.Conflict(new { error = "Technician has no verified skills yet." });
            var from = r.ValidFrom?.UtcDateTime ?? DateTime.UtcNow;
            DateTime? to = r.ValidTo?.UtcDateTime;
            if (to is not null && to <= from) return Bad("validTo must be after validFrom.");

            var rel = await db.Relationships.FirstOrDefaultAsync(x => x.TechnicianId == tech.Id && x.CompanyId == id, ct);
            if (rel is not null && (rel.Status == RelationshipStatus.Invited || rel.Status == RelationshipStatus.Active || rel.Status == RelationshipStatus.Suspended))
                return Results.Conflict(new { error = $"A relationship already exists ({rel.Status})." });
            if (rel is null) { rel = new TechnicianCompanyRelationship { TechnicianId = tech.Id, CompanyId = id }; db.Relationships.Add(rel); }
            rel.Type = type; rel.Status = RelationshipStatus.Invited; rel.ValidFrom = from; rel.ValidTo = to; rel.InvitedBy = uid; rel.UpdatedAt = DateTime.UtcNow;
            JobFlow.Notify(db, tech.UserId, id, "relationship.invited", "Invitation to work with a company", "A company invited you to work with them. Review it in your relationships.");
            db.Audit(http, uid, "relationship.invited", "relationship", rel.Id.ToString(), id, new { technicianId = tech.Id, type = type.ToString() });
            await db.SaveChangesAsync(ct);
            return Results.Created($"/companies/{id}/relationships", new { id = rel.Id, status = rel.Status.ToString() });
        });

        api.MapGet("/companies/{id:guid}/relationships", async Task<IResult> (Guid id, ClaimsPrincipal p, AppDbContext db, AccessService access, CancellationToken ct) =>
        {
            if (Deny(await access.Company(Uid(p), id, "relationship.read", ct)) is { } d) return d;
            var rows = await (from r in db.Relationships join t in db.Technicians on r.TechnicianId equals t.Id
                              where r.CompanyId == id orderby t.DisplayName
                              select new { r.Id, r.TechnicianId, technician = t.DisplayName, r.Type, r.Status, r.ValidFrom, r.ValidTo, phoneVerified = t.PhoneVerifiedAt != null,
                                           rating = db.JobRatings.Where(q => q.TechnicianId == t.Id).Average(q => (double?)q.Stars), ratingCount = db.JobRatings.Count(q => q.TechnicianId == t.Id) }).ToListAsync(ct);
            return Results.Ok(rows.Select(x => new { x.Id, x.TechnicianId, x.technician, type = x.Type.ToString(), status = x.Status.ToString(), x.ValidFrom, x.ValidTo, x.phoneVerified, rating = x.rating == null ? (double?)null : Math.Round(x.rating.Value, 2), x.ratingCount }));
        });

        api.MapPost("/companies/{id:guid}/relationships/{relId:guid}/action", async Task<IResult> (Guid id, Guid relId, RelActionReq r, ClaimsPrincipal p, AppDbContext db, AccessService access, HttpContext http, CancellationToken ct) =>
        {
            var uid = Uid(p);
            if (Deny(await access.Company(uid, id, "relationship.manage", ct)) is { } d) return d;
            var rel = await db.Relationships.FirstOrDefaultAsync(x => x.Id == relId && x.CompanyId == id, ct);
            if (rel is null) return Results.NotFound();
            RelationshipStatus next;
            switch (r.Action)
            {
                case "suspend" when rel.Status == RelationshipStatus.Active: next = RelationshipStatus.Suspended; break;
                case "reactivate" when rel.Status == RelationshipStatus.Suspended: next = RelationshipStatus.Active; break;
                case "end" when rel.Status is RelationshipStatus.Invited or RelationshipStatus.Active or RelationshipStatus.Suspended: next = RelationshipStatus.Ended; break;
                case "suspend" or "reactivate" or "end": return Results.Conflict(new { error = $"Cannot {r.Action} a relationship that is {rel.Status}." });
                default: return Bad("action must be suspend, reactivate or end.");
            }
            if (next == RelationshipStatus.Ended && await HasOpenAssignments(db, rel.TechnicianId, id, ct))
                return Results.Conflict(new { error = "Withdraw or reassign the technician's open jobs first." });
            rel.Status = next; rel.UpdatedAt = DateTime.UtcNow;
            var tech = await db.Technicians.FirstAsync(t => t.Id == rel.TechnicianId, ct);
            JobFlow.Notify(db, tech.UserId, id, "relationship." + next.ToString().ToLowerInvariant(), "Company relationship updated", $"A company relationship is now {next}.");
            db.Audit(http, uid, "relationship." + r.Action, "relationship", rel.Id.ToString(), id);
            await db.SaveChangesAsync(ct);
            return Results.Ok(new { id = rel.Id, status = rel.Status.ToString() });
        });

        api.MapGet("/technicians/me/relationships", async Task<IResult> (ClaimsPrincipal p, AppDbContext db, CancellationToken ct) =>
        {
            var t = await Me(db, p, ct); if (t is null) return Results.NotFound();
            var rows = await (from r in db.Relationships join c in db.Companies on r.CompanyId equals c.Id
                              where r.TechnicianId == t.Id select new { r.Id, company = c.DisplayName, r.Type, r.Status, r.ValidFrom, r.ValidTo }).ToListAsync(ct);
            return Results.Ok(rows.Select(x => new { x.Id, x.company, type = x.Type.ToString(), status = x.Status.ToString(), x.ValidFrom, x.ValidTo }));
        });

        api.MapPost("/technicians/me/relationships/{relId:guid}/respond", async Task<IResult> (Guid relId, RespondReq r, ClaimsPrincipal p, AppDbContext db, HttpContext http, CancellationToken ct) =>
        {
            var t = await Me(db, p, ct); if (t is null) return Results.NotFound();
            var rel = await db.Relationships.FirstOrDefaultAsync(x => x.Id == relId && x.TechnicianId == t.Id, ct);
            if (rel is null) return Results.NotFound();
            if (rel.Status != RelationshipStatus.Invited) return Results.Conflict(new { error = $"Invitation is {rel.Status}." });
            rel.Status = r.Accept ? RelationshipStatus.Active : RelationshipStatus.Declined; rel.UpdatedAt = DateTime.UtcNow;
            JobFlow.Notify(db, rel.InvitedBy, rel.CompanyId, "relationship.responded", "Technician responded", $"{t.DisplayName} {(r.Accept ? "accepted" : "declined")} your invitation.");
            db.Audit(http, Uid(p), r.Accept ? "relationship.accepted" : "relationship.declined", "relationship", rel.Id.ToString(), rel.CompanyId);
            await db.SaveChangesAsync(ct);
            return Results.Ok(new { id = rel.Id, status = rel.Status.ToString() });
        });

        api.MapPost("/technicians/me/relationships/{relId:guid}/end", async Task<IResult> (Guid relId, ClaimsPrincipal p, AppDbContext db, HttpContext http, CancellationToken ct) =>
        {
            var t = await Me(db, p, ct); if (t is null) return Results.NotFound();
            var rel = await db.Relationships.FirstOrDefaultAsync(x => x.Id == relId && x.TechnicianId == t.Id, ct);
            if (rel is null) return Results.NotFound();
            if (rel.Status is not (RelationshipStatus.Active or RelationshipStatus.Suspended)) return Results.Conflict(new { error = $"Relationship is {rel.Status}." });
            if (await HasOpenAssignments(db, t.Id, rel.CompanyId, ct)) return Results.Conflict(new { error = "Resolve your open jobs with this company first." });
            rel.Status = RelationshipStatus.Ended; rel.UpdatedAt = DateTime.UtcNow;
            JobFlow.Notify(db, rel.InvitedBy, rel.CompanyId, "relationship.ended", "Technician ended relationship", $"{t.DisplayName} ended the relationship.");
            db.Audit(http, Uid(p), "relationship.ended_by_technician", "relationship", rel.Id.ToString(), rel.CompanyId);
            await db.SaveChangesAsync(ct);
            return Results.NoContent();
        });

        // ======== Availability ========
        api.MapGet("/technicians/me/availability", async Task<IResult> (ClaimsPrincipal p, AppDbContext db, CancellationToken ct) =>
        {
            var t = await Me(db, p, ct); if (t is null) return Results.NotFound();
            var now = DateTime.UtcNow;
            return Results.Ok(await db.Availability.Where(a => a.TechnicianId == t.Id && a.EndsAt > now).OrderBy(a => a.StartsAt).Select(a => new { a.Id, a.StartsAt, a.EndsAt }).ToListAsync(ct));
        });

        api.MapPost("/technicians/me/availability", async Task<IResult> (WindowReq r, ClaimsPrincipal p, AppDbContext db, HttpContext http, CancellationToken ct) =>
        {
            var t = await Me(db, p, ct); if (t is null) return Results.NotFound();
            var s = r.StartsAt.UtcDateTime; var e = r.EndsAt.UtcDateTime;
            if (e <= s || e <= DateTime.UtcNow) return Bad("endsAt must be after startsAt and in the future.");
            if (e - s > TimeSpan.FromDays(31)) return Bad("A window can be at most 31 days.");
            if (await db.Availability.AnyAsync(a => a.TechnicianId == t.Id && a.StartsAt < e && a.EndsAt > s, ct))
                return Results.Conflict(new { error = "Overlaps an existing availability window." });
            var w = new TechnicianAvailability { TechnicianId = t.Id, StartsAt = s, EndsAt = e };
            db.Availability.Add(w);
            db.Audit(http, Uid(p), "availability.added", "availability", w.Id.ToString());
            await db.SaveChangesAsync(ct);
            return Results.Created("/technicians/me/availability", new { w.Id, w.StartsAt, w.EndsAt });
        });

        api.MapDelete("/technicians/me/availability/{wid:guid}", async Task<IResult> (Guid wid, ClaimsPrincipal p, AppDbContext db, HttpContext http, CancellationToken ct) =>
        {
            var t = await Me(db, p, ct); if (t is null) return Results.NotFound();
            var w = await db.Availability.FirstOrDefaultAsync(a => a.Id == wid && a.TechnicianId == t.Id, ct);
            if (w is null) return Results.NotFound();
            db.Availability.Remove(w);
            db.Audit(http, Uid(p), "availability.removed", "availability", wid.ToString());
            await db.SaveChangesAsync(ct);
            return Results.NoContent();
        });

        // ======== Customers & locations (company scoped) ========
        api.MapPost("/companies/{id:guid}/customers", async Task<IResult> (Guid id, CustomerReq r, ClaimsPrincipal p, AppDbContext db, AccessService access, HttpContext http, CancellationToken ct) =>
        {
            var uid = Uid(p);
            if (Deny(await access.Company(uid, id, "customer.manage", ct)) is { } d) return d;
            if (string.IsNullOrWhiteSpace(r.Name) || string.IsNullOrWhiteSpace(r.Phone)) return Bad("name and phone are required.");
            var c = new Customer { CompanyId = id, Name = r.Name.Trim(), Phone = r.Phone.Trim(), Email = r.Email?.Trim(), ContactPreference = r.ContactPreference?.Trim() };
            db.Customers.Add(c);
            db.Audit(http, uid, "customer.created", "customer", c.Id.ToString(), id);
            await db.SaveChangesAsync(ct);
            return Results.Created($"/companies/{id}/customers/{c.Id}", new { c.Id, c.Name });
        });

        api.MapGet("/companies/{id:guid}/customers", async Task<IResult> (Guid id, string? q, ClaimsPrincipal p, AppDbContext db, AccessService access, CancellationToken ct) =>
        {
            if (Deny(await access.Company(Uid(p), id, "job.read", ct)) is { } d) return d;
            var query = db.Customers.Where(c => c.CompanyId == id);
            if (!string.IsNullOrWhiteSpace(q)) { var s = q.Trim(); query = query.Where(c => c.Name.Contains(s) || c.Phone.Contains(s)); }
            return Results.Ok(await query.OrderBy(c => c.Name).Take(100).Select(c => new { c.Id, c.Name, c.Phone, c.Email, c.ContactPreference }).ToListAsync(ct));
        });

        api.MapPost("/companies/{id:guid}/customers/{cid:guid}/locations", async Task<IResult> (Guid id, Guid cid, LocationReq r, ClaimsPrincipal p, AppDbContext db, AccessService access, HttpContext http, CancellationToken ct) =>
        {
            var uid = Uid(p);
            if (Deny(await access.Company(uid, id, "customer.manage", ct)) is { } d) return d;
            if (!await db.Customers.AnyAsync(c => c.Id == cid && c.CompanyId == id, ct)) return Results.NotFound();
            if (string.IsNullOrWhiteSpace(r.Label) || string.IsNullOrWhiteSpace(r.Address)) return Bad("label and address are required.");
            if (r.Latitude is < -90 or > 90 || r.Longitude is < -180 or > 180) return Bad("Coordinates are out of range.");
            if (r.ServiceAreaId is { } sa && !await db.ServiceAreas.AnyAsync(a => a.Id == sa && a.Active, ct)) return Bad("Unknown serviceAreaId.");
            var l = new ServiceLocation { ServiceAreaId = r.ServiceAreaId, CompanyId = id, CustomerId = cid, Label = r.Label.Trim(), Address = r.Address.Trim(), Latitude = r.Latitude, Longitude = r.Longitude, AccessInstructions = r.AccessInstructions?.Trim() };
            db.Locations.Add(l);
            db.Audit(http, uid, "location.created", "location", l.Id.ToString(), id);
            await db.SaveChangesAsync(ct);
            return Results.Created($"/companies/{id}/customers/{cid}", new { l.Id, l.Label });
        });

        api.MapGet("/companies/{id:guid}/customers/{cid:guid}", async Task<IResult> (Guid id, Guid cid, ClaimsPrincipal p, AppDbContext db, AccessService access, CancellationToken ct) =>
        {
            if (Deny(await access.Company(Uid(p), id, "job.read", ct)) is { } d) return d;
            var c = await db.Customers.FirstOrDefaultAsync(x => x.Id == cid && x.CompanyId == id, ct);
            if (c is null) return Results.NotFound();
            var locs = await db.Locations.Where(l => l.CustomerId == cid && l.CompanyId == id).Select(l => new { l.Id, l.Label, l.Address, l.Latitude, l.Longitude, l.AccessInstructions }).ToListAsync(ct);
            var jobs = await db.Jobs.Where(j => j.CustomerId == cid && j.CompanyId == id).OrderByDescending(j => j.CreatedAt).Take(20).Select(j => new { j.Id, j.Reference, j.Status, j.ScheduledStart }).ToListAsync(ct);
            return Results.Ok(new { c.Id, c.Name, c.Phone, c.Email, c.ContactPreference, locations = locs, priorJobs = jobs.Select(j => new { j.Id, j.Reference, status = j.Status.ToString(), j.ScheduledStart }) });
        });

        // ======== Jobs ========
        api.MapPost("/companies/{id:guid}/jobs", async Task<IResult> (Guid id, JobReq r, ClaimsPrincipal p, AppDbContext db, AccessService access, HttpContext http, CancellationToken ct) =>
        {
            var uid = Uid(p);
            if (Deny(await access.Company(uid, id, "job.manage", ct)) is { } d) return d;
            if (!await IsApproved(db, id, ct)) return NotApproved();
            var start = r.ScheduledStart.UtcDateTime; var end = r.ScheduledEnd.UtcDateTime;
            if (end <= start || end <= DateTime.UtcNow) return Bad("scheduledEnd must be after scheduledStart and in the future.");
            if (end - start > TimeSpan.FromDays(7)) return Bad("A job can span at most 7 days.");
            if (string.IsNullOrWhiteSpace(r.Description) || r.Description.Length > 4000) return Bad("description is required (max 4000 characters).");
            var priority = JobPriority.Normal;
            if (r.Priority is not null && !Enum.TryParse(r.Priority, true, out priority)) return Bad("priority must be Low, Normal, High or Urgent.");
            if (!await db.Customers.AnyAsync(c => c.Id == r.CustomerId && c.CompanyId == id, ct)) return Bad("Unknown customer.");
            if (!await db.Locations.AnyAsync(l => l.Id == r.LocationId && l.CompanyId == id && l.CustomerId == r.CustomerId, ct)) return Bad("Unknown location for that customer.");
            if (!await db.Trades.AnyAsync(t => t.Id == r.TradeId && t.Active, ct)) return Bad("Unknown trade.");
            var skillIds = (r.RequiredSkillIds ?? new List<Guid>()).Distinct().ToList();
            if (await db.Skills.CountAsync(s => skillIds.Contains(s.Id) && s.TradeId == r.TradeId && s.Active, ct) != skillIds.Count)
                return Bad("Every required skill must exist and belong to the chosen trade.");

            if (r.WarrantyDays is < 0 or > 3650) return Bad("warrantyDays must be between 0 and 3650.");
            var job = new Job { WarrantyDays = r.WarrantyDays, Reference = NewReference(), CompanyId = id, CustomerId = r.CustomerId, LocationId = r.LocationId, TradeId = r.TradeId,
                Description = r.Description.Trim(), Priority = priority, ScheduledStart = start, ScheduledEnd = end, CreatedBy = uid };
            db.Jobs.Add(job);
            foreach (var s in skillIds) db.JobRequiredSkills.Add(new JobRequiredSkill { JobId = job.Id, SkillId = s });
            db.JobStatusHistory.Add(new JobStatusHistory { JobId = job.Id, FromStatus = null, ToStatus = JobStatus.Open, ActorUserId = uid, Reason = "created" });
            db.Audit(http, uid, "job.created", "job", job.Id.ToString(), id);
            await db.SaveChangesAsync(ct);
            return Results.Created($"/companies/{id}/jobs/{job.Id}", new { job.Id, job.Reference, status = job.Status.ToString() });
        });

        api.MapGet("/companies/{id:guid}/jobs", async Task<IResult> (Guid id, string? status, int? take, ClaimsPrincipal p, AppDbContext db, AccessService access, CancellationToken ct) =>
        {
            if (Deny(await access.Company(Uid(p), id, "job.read", ct)) is { } d) return d;
            var q = db.Jobs.Where(j => j.CompanyId == id);
            if (Enum.TryParse<JobStatus>(status, true, out var s)) q = q.Where(j => j.Status == s);
            var rows = await q.OrderByDescending(j => j.CreatedAt).Take(Math.Clamp(take ?? 50, 1, 200)).ToListAsync(ct);
            return Results.Ok(rows.Select(j => new { j.Id, j.Reference, status = j.Status.ToString(), priority = j.Priority.ToString(), j.ScheduledStart, j.ScheduledEnd }));
        });

        api.MapGet("/companies/{id:guid}/jobs/{jobId:guid}", async Task<IResult> (Guid id, Guid jobId, ClaimsPrincipal p, AppDbContext db, AccessService access, CancellationToken ct) =>
        {
            if (Deny(await access.Company(Uid(p), id, "job.read", ct)) is { } d) return d;
            var j = await LoadJob(db, id, jobId, ct); if (j is null) return Results.NotFound();
            var assignments = await (from a in db.Assignments join t in db.Technicians on a.TechnicianId equals t.Id
                                     where a.JobId == jobId orderby a.OfferedAt
                                     select new { a.Id, a.TechnicianId, technician = t.DisplayName, a.Status, a.OfferedAt, a.RespondedAt, a.EndedAt, a.Reason }).ToListAsync(ct);
            var history = await db.JobStatusHistory.Where(h => h.JobId == jobId).OrderBy(h => h.At).Select(h => new { h.FromStatus, h.ToStatus, h.ActorUserId, h.Reason, h.At }).ToListAsync(ct);
            var skills = await db.JobRequiredSkills.Where(s => s.JobId == jobId).Select(s => s.SkillId).ToListAsync(ct);
            return Results.Ok(new
            {
                j.Id, j.Reference, status = j.Status.ToString(), priority = j.Priority.ToString(), j.Description, j.CustomerId, j.LocationId, j.TradeId, j.ScheduledStart, j.ScheduledEnd, requiredSkillIds = skills,
                assignments = assignments.Select(a => new { a.Id, a.TechnicianId, a.technician, status = a.Status.ToString(), a.OfferedAt, a.RespondedAt, a.EndedAt, a.Reason }),
                history = history.Select(h => new { h.FromStatus, to = h.ToStatus.ToString(), h.ActorUserId, h.Reason, h.At })
            });
        });

        api.MapPost("/companies/{id:guid}/jobs/{jobId:guid}/cancel", async Task<IResult> (Guid id, Guid jobId, ReasonReq r, ClaimsPrincipal p, AppDbContext db, AccessService access, HttpContext http, CancellationToken ct) =>
        {
            var uid = Uid(p);
            if (Deny(await access.Company(uid, id, "job.manage", ct)) is { } d) return d;
            if (string.IsNullOrWhiteSpace(r.Reason)) return Bad("A reason is required.");
            var j = await LoadJob(db, id, jobId, ct); if (j is null) return Results.NotFound();
            if (!JobRules.Allowed(j.Status, JobStatus.Cancelled)) return Results.Conflict(new { error = $"A {j.Status} job cannot be cancelled." });
            var a = await ActiveAssignment(db, jobId, ct);
            if (a is not null)
            {
                a.Status = AssignmentStatus.Cancelled; a.EndedAt = DateTime.UtcNow; a.Reason = r.Reason.Trim();
                var tech = await db.Technicians.FirstAsync(t => t.Id == a.TechnicianId, ct);
                JobFlow.Notify(db, tech.UserId, id, "job.cancelled", "Job cancelled", $"Job {j.Reference} was cancelled.");
            }
            JobFlow.Move(db, j, JobStatus.Cancelled, uid, r.Reason.Trim());
            db.Audit(http, uid, "job.cancelled", "job", jobId.ToString(), id, new { reason = r.Reason.Trim() });
            await db.SaveChangesAsync(ct);
            return Results.Ok(new { j.Id, status = j.Status.ToString() });
        });

        // Rescheduling withdraws any live offer/assignment (the technician is told) and returns the job to Open for re-dispatch.
        api.MapPost("/companies/{id:guid}/jobs/{jobId:guid}/reschedule", async Task<IResult> (Guid id, Guid jobId, RescheduleReq r, ClaimsPrincipal p, AppDbContext db, AccessService access, HttpContext http, CancellationToken ct) =>
        {
            var uid = Uid(p);
            if (Deny(await access.Company(uid, id, "job.manage", ct)) is { } d) return d;
            var start = r.ScheduledStart.UtcDateTime; var end = r.ScheduledEnd.UtcDateTime;
            if (end <= start || end <= DateTime.UtcNow) return Bad("scheduledEnd must be after scheduledStart and in the future.");
            if (end - start > TimeSpan.FromDays(7)) return Bad("A job can span at most 7 days.");
            var j = await LoadJob(db, id, jobId, ct); if (j is null) return Results.NotFound();
            if (j.Status is not (JobStatus.Open or JobStatus.Offered or JobStatus.Accepted)) return Results.Conflict(new { error = $"A {j.Status} job cannot be rescheduled." });
            var a = await ActiveAssignment(db, jobId, ct);
            if (a is not null)
            {
                a.Status = AssignmentStatus.Withdrawn; a.EndedAt = DateTime.UtcNow; a.Reason = "Rescheduled";
                var tech = await db.Technicians.FirstAsync(t => t.Id == a.TechnicianId, ct);
                JobFlow.Notify(db, tech.UserId, id, "job.rescheduled", "Job rescheduled", $"Job {j.Reference} was rescheduled; your assignment was withdrawn.");
                JobFlow.Move(db, j, JobStatus.Open, uid, "Rescheduled: " + (r.Reason ?? "no reason given"));
            }
            j.ScheduledStart = start; j.ScheduledEnd = end;
            db.Audit(http, uid, "job.rescheduled", "job", jobId.ToString(), id, new { start, end });
            await db.SaveChangesAsync(ct);
            return Results.Ok(new { j.Id, status = j.Status.ToString(), j.ScheduledStart, j.ScheduledEnd });
        });

        // ======== Matching & dispatch ========
        api.MapGet("/companies/{id:guid}/jobs/{jobId:guid}/candidates", async Task<IResult> (Guid id, Guid jobId, bool? includeIneligible, ClaimsPrincipal p, AppDbContext db, AccessService access, MatchingService matching, CancellationToken ct) =>
        {
            if (Deny(await access.Company(Uid(p), id, "job.dispatch", ct)) is { } d) return d;
            var j = await LoadJob(db, id, jobId, ct); if (j is null) return Results.NotFound();
            var all = await matching.EvaluateAsync(j, null, ct);
            return Results.Ok(new { job = j.Reference, status = j.Status.ToString(), candidates = includeIneligible == true ? all : all.Where(c => c.Eligible).ToList() });
        });

        api.MapPost("/companies/{id:guid}/jobs/{jobId:guid}/offer", async Task<IResult> (Guid id, Guid jobId, OfferReq r, ClaimsPrincipal p, AppDbContext db, AccessService access, MatchingService matching, HttpContext http, CancellationToken ct) =>
        {
            var uid = Uid(p);
            if (Deny(await access.Company(uid, id, "job.dispatch", ct)) is { } d) return d;
            var j = await LoadJob(db, id, jobId, ct); if (j is null) return Results.NotFound();
            if (j.Status != JobStatus.Open) return Results.Conflict(new { error = $"Only Open jobs can be offered; this job is {j.Status}." });
            var c = (await matching.EvaluateAsync(j, r.TechnicianId, ct)).FirstOrDefault();
            if (c is null) return Results.NotFound(new { error = "That technician has no active relationship with this company." });
            if (!c.Eligible) return Results.Conflict(new { error = "Technician is not eligible for this job.", blockers = c.Blockers });
            var tech = await db.Technicians.FirstAsync(t => t.Id == r.TechnicianId, ct);
            var a = new JobAssignment { JobId = j.Id, TechnicianId = c.TechnicianId, RelationshipId = c.RelationshipId, AssignedBy = uid, ScheduledStart = j.ScheduledStart, ScheduledEnd = j.ScheduledEnd };
            db.Assignments.Add(a);
            JobFlow.Move(db, j, JobStatus.Offered, uid, $"Offered to {tech.DisplayName}");
            JobFlow.Notify(db, tech.UserId, id, "job.offered", "New job offer", $"Job {j.Reference} is waiting for your response.");
            db.Audit(http, uid, "job.offered", "job", jobId.ToString(), id, new { technicianId = tech.Id });
            Outbox.Add(db, "job.offered", "job", jobId.ToString(), id, new { technicianId = tech.Id, assignmentId = a.Id });
            try { await db.SaveChangesAsync(ct); }
            catch (DbUpdateException) { return Results.Conflict(new { error = "Another dispatcher just offered this job. Reload and retry." }); }
            return Results.Created($"/companies/{id}/jobs/{jobId}", new { assignmentId = a.Id, status = a.Status.ToString() });
        });

        api.MapPost("/companies/{id:guid}/jobs/{jobId:guid}/withdraw", async Task<IResult> (Guid id, Guid jobId, ReasonReq r, ClaimsPrincipal p, AppDbContext db, AccessService access, HttpContext http, CancellationToken ct) =>
        {
            var uid = Uid(p);
            if (Deny(await access.Company(uid, id, "job.dispatch", ct)) is { } d) return d;
            var j = await LoadJob(db, id, jobId, ct); if (j is null) return Results.NotFound();
            var a = await ActiveAssignment(db, jobId, ct);
            if (j.Status != JobStatus.Offered || a is null) return Results.Conflict(new { error = "Only a pending offer can be withdrawn." });
            a.Status = AssignmentStatus.Withdrawn; a.EndedAt = DateTime.UtcNow; a.Reason = r.Reason?.Trim();
            var tech = await db.Technicians.FirstAsync(t => t.Id == a.TechnicianId, ct);
            JobFlow.Notify(db, tech.UserId, id, "job.withdrawn", "Offer withdrawn", $"The offer for job {j.Reference} was withdrawn.");
            JobFlow.Move(db, j, JobStatus.Open, uid, "Offer withdrawn");
            db.Audit(http, uid, "job.offer_withdrawn", "job", jobId.ToString(), id);
            await db.SaveChangesAsync(ct);
            return Results.Ok(new { j.Id, status = j.Status.ToString() });
        });

        api.MapPost("/companies/{id:guid}/jobs/{jobId:guid}/reassign", async Task<IResult> (Guid id, Guid jobId, ReassignReq r, ClaimsPrincipal p, AppDbContext db, AccessService access, MatchingService matching, HttpContext http, CancellationToken ct) =>
        {
            var uid = Uid(p);
            if (Deny(await access.Company(uid, id, "job.dispatch", ct)) is { } d) return d;
            if (string.IsNullOrWhiteSpace(r.Reason)) return Bad("A reason is required.");
            var j = await LoadJob(db, id, jobId, ct); if (j is null) return Results.NotFound();
            var current = await ActiveAssignment(db, jobId, ct);
            if (current is null || j.Status is not (JobStatus.Offered or JobStatus.Accepted)) return Results.Conflict(new { error = $"A {j.Status} job cannot be reassigned." });
            if (current.TechnicianId == r.TechnicianId) return Bad("Choose a different technician.");
            var c = (await matching.EvaluateAsync(j, r.TechnicianId, ct)).FirstOrDefault();
            if (c is null) return Results.NotFound(new { error = "That technician has no active relationship with this company." });
            if (!c.Eligible) return Results.Conflict(new { error = "Technician is not eligible for this job.", blockers = c.Blockers });

            var oldTech = await db.Technicians.FirstAsync(t => t.Id == current.TechnicianId, ct);
            var newTech = await db.Technicians.FirstAsync(t => t.Id == r.TechnicianId, ct);
            await using var tx = await db.Database.BeginTransactionAsync(ct);   // both steps commit together or not at all
            current.Status = AssignmentStatus.Reassigned; current.EndedAt = DateTime.UtcNow; current.Reason = r.Reason.Trim();
            await db.SaveChangesAsync(ct);   // frees the one-live-assignment slot before the new offer is inserted
            var a = new JobAssignment { JobId = j.Id, TechnicianId = c.TechnicianId, RelationshipId = c.RelationshipId, AssignedBy = uid, ScheduledStart = j.ScheduledStart, ScheduledEnd = j.ScheduledEnd };
            db.Assignments.Add(a);
            JobFlow.Move(db, j, JobStatus.Offered, uid, $"Reassigned from {oldTech.DisplayName} to {newTech.DisplayName}: {r.Reason.Trim()}");
            JobFlow.Notify(db, oldTech.UserId, id, "job.reassigned", "Job reassigned", $"Job {j.Reference} was assigned to someone else.");
            JobFlow.Notify(db, newTech.UserId, id, "job.offered", "New job offer", $"Job {j.Reference} is waiting for your response.");
            db.Audit(http, uid, "job.reassigned", "job", jobId.ToString(), id, new { from = oldTech.Id, to = newTech.Id });
            await db.SaveChangesAsync(ct);
            await tx.CommitAsync(ct);
            return Results.Ok(new { assignmentId = a.Id, status = a.Status.ToString() });
        });

        // ======== Technician: offers and responses ========
        // Customers' details are deliberately not exposed here; Phase 3 reveals the minimum needed after acceptance.
        api.MapGet("/technicians/me/assignments", async Task<IResult> (string? status, ClaimsPrincipal p, AppDbContext db, CancellationToken ct) =>
        {
            var t = await Me(db, p, ct); if (t is null) return Results.NotFound();
            var q = from a in db.Assignments
                    join j in db.Jobs on a.JobId equals j.Id
                    join c in db.Companies on j.CompanyId equals c.Id
                    join tr in db.Trades on j.TradeId equals tr.Id
                    where a.TechnicianId == t.Id
                    select new { a, j, company = c.DisplayName, trade = tr.Name };
            if (Enum.TryParse<AssignmentStatus>(status, true, out var s)) q = q.Where(x => x.a.Status == s);
            var rows = await q.OrderByDescending(x => x.a.OfferedAt).Take(100).ToListAsync(ct);
            return Results.Ok(rows.Select(x => new
            {
                assignmentId = x.a.Id, status = x.a.Status.ToString(), x.a.OfferedAt,
                job = new { x.j.Reference, x.trade, x.j.Description, priority = x.j.Priority.ToString(), x.j.ScheduledStart, x.j.ScheduledEnd }, x.company
            }));
        });

        api.MapPost("/technicians/me/assignments/{aid:guid}/respond", async Task<IResult> (Guid aid, RespondReq r, ClaimsPrincipal p, AppDbContext db, MatchingService matching, HttpContext http, CancellationToken ct) =>
        {
            var uid = Uid(p);
            var t = await Me(db, p, ct); if (t is null) return Results.NotFound();
            try
            {
                // Serializable: two concurrent accepts for the same technician cannot both succeed.
                await using var tx = await db.Database.BeginTransactionAsync(IsolationLevel.Serializable, ct);
                var a = await db.Assignments.FirstOrDefaultAsync(x => x.Id == aid && x.TechnicianId == t.Id, ct);   // other technicians' ids are "not found"
                if (a is null) return Results.NotFound();
                if (a.Status != AssignmentStatus.Offered) return Results.Conflict(new { error = $"This offer is {a.Status}." });
                var j = await db.Jobs.FirstAsync(x => x.Id == a.JobId, ct);
                if (j.Status != JobStatus.Offered) return Results.Conflict(new { error = $"The job is {j.Status}." });

                if (r.Accept)
                {
                    var c = (await matching.EvaluateAsync(j, t.Id, ct)).FirstOrDefault();
                    if (c is null || !c.Eligible) return Results.Conflict(new { error = "You can no longer accept this job.", blockers = c?.Blockers ?? new List<string> { "Relationship is no longer active." } });
                    a.Status = AssignmentStatus.Accepted; a.RespondedAt = DateTime.UtcNow;
                    JobFlow.Move(db, j, JobStatus.Accepted, uid, null);
                    JobFlow.Notify(db, a.AssignedBy, j.CompanyId, "job.accepted", "Offer accepted", $"{t.DisplayName} accepted job {j.Reference}.");
                }
                else
                {
                    a.Status = AssignmentStatus.Declined; a.RespondedAt = DateTime.UtcNow; a.EndedAt = DateTime.UtcNow; a.Reason = r.Reason?.Trim();
                    JobFlow.Move(db, j, JobStatus.Open, uid, "Declined by technician");
                    JobFlow.Notify(db, a.AssignedBy, j.CompanyId, "job.declined", "Offer declined", $"{t.DisplayName} declined job {j.Reference}.");
                }
                db.Audit(http, uid, r.Accept ? "assignment.accepted" : "assignment.declined", "assignment", aid.ToString(), j.CompanyId);
                await db.SaveChangesAsync(ct);
                await tx.CommitAsync(ct);
                return Results.Ok(new { assignmentId = a.Id, status = a.Status.ToString(), job = j.Status.ToString() });
            }
            catch (Exception ex) when (IsConcurrencyFailure(ex))
            {
                return Results.Conflict(new { error = "This conflicts with another confirmed job. Please retry." });
            }
        });

        // ======== In-app notifications ========
        api.MapGet("/notifications", async Task<IResult> (bool? unread, ClaimsPrincipal p, AppDbContext db, CancellationToken ct) =>
        {
            var uid = Uid(p);
            var q = db.Notifications.Where(n => n.UserId == uid);
            if (unread == true) q = q.Where(n => n.ReadAt == null);
            return Results.Ok(await q.OrderByDescending(n => n.CreatedAt).Take(50).Select(n => new { n.Id, n.Kind, n.Title, n.Body, n.CreatedAt, n.ReadAt }).ToListAsync(ct));
        });

        api.MapPost("/notifications/{nid:guid}/read", async Task<IResult> (Guid nid, ClaimsPrincipal p, AppDbContext db, CancellationToken ct) =>
        {
            var uid = Uid(p);
            var n = await db.Notifications.FirstOrDefaultAsync(x => x.Id == nid && x.UserId == uid, ct);
            if (n is null) return Results.NotFound();
            n.ReadAt ??= DateTime.UtcNow;
            await db.SaveChangesAsync(ct);
            return Results.NoContent();
        });
    }
}
