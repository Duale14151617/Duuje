using System.Security.Claims;
using System.Security.Cryptography;
using Duale.Api.Auth;
using Duale.Api.Data;
using Duale.Api.Domain;
using Duale.Api.Services;
using Microsoft.EntityFrameworkCore;
using static Duale.Api.Endpoints;
using static Duale.Api.Phase2Endpoints;
namespace Duale.Api;

public record StatusReq(string? Status, DateTimeOffset? ClientTime);
public record ScopeReq(string? Description);
public record ReportReq(string? Summary, decimal? HoursWorked);
public record ReviewReq(string? Decision, string? Note);
public record ComplaintReq(string? Description);
public record ResolveReq(string? Resolution);
public record CallbackReq(DateTimeOffset ScheduledStart, DateTimeOffset ScheduledEnd, string? Responsibility, string? Notes, Guid? ComplaintId);

public static class Phase3Endpoints
{
    static readonly string[] EvidenceKinds = ["before", "progress", "after", "other"];
    static readonly string[] Responsibilities = ["technician", "company", "customer", "undetermined"];
    static readonly JobStatus[] FieldStates = [JobStatus.Accepted, JobStatus.EnRoute, JobStatus.Arrived, JobStatus.InProgress, JobStatus.AwaitingReview, JobStatus.ReturnedForCorrection];

    // The technician's own accepted assignment, or nothing. Other technicians' ids are simply "not found".
    static async Task<(Technician T, JobAssignment A, Job J)?> Mine(AppDbContext db, ClaimsPrincipal p, Guid aid, CancellationToken ct)
    {
        var uid = Uid(p);
        var row = await (from t in db.Technicians
                         join a in db.Assignments on t.Id equals a.TechnicianId
                         join j in db.Jobs on a.JobId equals j.Id
                         where t.UserId == uid && a.Id == aid
                         select new { t, a, j }).FirstOrDefaultAsync(ct);
        return row is null ? null : (row.t, row.a, row.j);
    }

    static object EvDto(JobEvidence e) => new { e.Id, e.Kind, e.FileName, e.ContentType, e.SizeBytes, e.UploadedAt };

    // Several permissions may open the same door (e.g. dispatchers and supervisors can both raise a complaint).
    static async Task<Access> AnyOf(AccessService access, Guid uid, Guid companyId, CancellationToken ct, params string[] perms)
    {
        var best = Access.NotMember;
        foreach (var perm in perms)
        {
            var a = await access.Company(uid, companyId, perm, ct);
            if (a == Access.Allowed) return a;
            if (a == Access.Forbidden) best = a;
        }
        return best;
    }

    public static void Map(RouteGroupBuilder api)
    {
        // ======== Technician: job execution ========
        // Customer details are revealed only to the accepted technician, only while the job is in the field.
        api.MapGet("/technicians/me/assignments/{aid:guid}/job", async Task<IResult> (Guid aid, ClaimsPrincipal p, AppDbContext db, CancellationToken ct) =>
        {
            var m = await Mine(db, p, aid, ct); if (m is null) return Results.NotFound();
            var (_, a, j) = m.Value;
            object? customer = null;
            if (a.Status == AssignmentStatus.Accepted && FieldStates.Contains(j.Status))
                customer = await (from c in db.Customers join l in db.Locations on c.Id equals l.CustomerId
                                  where c.Id == j.CustomerId && l.Id == j.LocationId
                                  select new { c.Name, c.Phone, location = l.Label, l.Address, l.Latitude, l.Longitude, l.AccessInstructions }).FirstOrDefaultAsync(ct);
            var trade = await db.Trades.Where(t => t.Id == j.TradeId).Select(t => t.Name).FirstAsync(ct);
            var company = await db.Companies.Where(c => c.Id == j.CompanyId).Select(c => c.DisplayName).FirstAsync(ct);
            var lastReturn = await db.JobReviews.Where(r => r.JobId == j.Id && r.Decision == "Returned").OrderByDescending(r => r.At).Select(r => r.Note).FirstOrDefaultAsync(ct);
            var evidence = await db.JobEvidence.CountAsync(e => e.JobId == j.Id, ct);
            var reports = await db.JobWorkReports.CountAsync(r => r.JobId == j.Id, ct);
            return Results.Ok(new
            {
                assignmentId = a.Id, assignment = a.Status.ToString(), job = new { j.Reference, status = j.Status.ToString(), priority = j.Priority.ToString(), trade, j.Description, j.ScheduledStart, j.ScheduledEnd },
                company, customer, returnNote = j.Status == JobStatus.ReturnedForCorrection ? lastReturn : null, evidenceCount = evidence, reportCount = reports
            });
        });

        api.MapPost("/technicians/me/assignments/{aid:guid}/status", async Task<IResult> (Guid aid, StatusReq r, ClaimsPrincipal p, AppDbContext db, HttpContext http, CancellationToken ct) =>
        {
            var uid = Uid(p);
            return await Idem.RunAsync(db, http, $"tech-status:{uid}", async () =>
            {
                var m = await Mine(db, p, aid, ct);
                if (m is null) return (404, new { error = "Not found." });
                var (t, a, j) = m.Value;
                if (!Enum.TryParse<JobStatus>(r.Status, true, out var to) || to is not (JobStatus.EnRoute or JobStatus.Arrived or JobStatus.InProgress))
                    return (400, new { error = "status must be EnRoute, Arrived or InProgress." });
                if (a.Status != AssignmentStatus.Accepted) return (409, new { error = $"This assignment is {a.Status}." });
                if (!JobRules.Allowed(j.Status, to)) return (409, new { error = $"Cannot move a {j.Status} job to {to}." });
                JobFlow.Move(db, j, to, uid, r.ClientTime is null ? null : "Recorded on device at " + r.ClientTime.Value.UtcDateTime.ToString("o"));
                JobFlow.Notify(db, a.AssignedBy, j.CompanyId, "job." + to.ToString().ToLowerInvariant(), "Job update", $"{t.DisplayName}: job {j.Reference} is now {to}.");
                db.Audit(http, uid, "job.status_" + to.ToString().ToLowerInvariant(), "job", j.Id.ToString(), j.CompanyId);
                return (200, new { status = to.ToString() });
            }, ct);
        });

        api.MapGet("/technicians/me/assignments/{aid:guid}/evidence", async Task<IResult> (Guid aid, ClaimsPrincipal p, AppDbContext db, CancellationToken ct) =>
        {
            var m = await Mine(db, p, aid, ct); if (m is null) return Results.NotFound();
            var rows = await db.JobEvidence.Where(e => e.AssignmentId == aid).OrderBy(e => e.UploadedAt).ToListAsync(ct);
            return Results.Ok(rows.Select(EvDto));
        });

        api.MapPost("/technicians/me/assignments/{aid:guid}/evidence", async Task<IResult> (Guid aid, HttpRequest req, ClaimsPrincipal p, AppDbContext db, IFileStore store, IUploadScanner scanner, IConfiguration cfg, HttpContext http, CancellationToken ct) =>
        {
            var uid = Uid(p);
            return await Idem.RunAsync(db, http, $"tech-evidence:{uid}", async () =>
            {
                var m = await Mine(db, p, aid, ct);
                if (m is null) return (404, new { error = "Not found." });
                var (_, a, j) = m.Value;
                if (a.Status != AssignmentStatus.Accepted || j.Status is not (JobStatus.Arrived or JobStatus.InProgress or JobStatus.ReturnedForCorrection))
                    return (409, new { error = "Evidence can be added once you have arrived and until the work is submitted." });
                if (!req.HasFormContentType) return (400, new { error = "Send multipart/form-data with fields kind and file." });
                var form = await req.ReadFormAsync(ct);
                var kind = form["kind"].ToString().Trim().ToLowerInvariant();
                if (!EvidenceKinds.Contains(kind)) return (400, new { error = "kind must be one of: " + string.Join(", ", EvidenceKinds) });
                var file = form.Files.GetFile("file");
                if (file is null || file.Length == 0) return (400, new { error = "A file is required." });
                var max = long.TryParse(cfg["Files:MaxBytes"], out var mx) ? mx : 5_000_000;
                if (file.Length > max) return (413, new { error = "File is too large." });
                if (await db.JobEvidence.CountAsync(e => e.JobId == j.Id, ct) >= 40) return (409, new { error = "Evidence limit reached for this job." });
                byte[] data;
                using (var ms = new MemoryStream()) { await file.CopyToAsync(ms, ct); data = ms.ToArray(); }
                var type = Foundation2Endpoints.Sniff(data);
                if (type is null) return (400, new { error = "Only PDF, JPEG and PNG files are accepted." });
                if (!await scanner.IsCleanAsync(data, ct)) return (400, new { error = "The file failed the security scan." });
                var key = Guid.NewGuid().ToString("N");
                var name = Path.GetFileName(file.FileName ?? "evidence");
                var ev = new JobEvidence { JobId = j.Id, AssignmentId = a.Id, Kind = kind, ContentType = type, SizeBytes = data.Length, StorageKey = key, UploadedBy = uid,
                    FileName = name.Length > 120 ? name[..120] : name, Sha256 = Convert.ToHexString(SHA256.HashData(data)).ToLowerInvariant() };
                await store.SaveAsync(key, data, ct);
                db.JobEvidence.Add(ev);
                db.Audit(http, uid, "job.evidence_uploaded", "job_evidence", ev.Id.ToString(), j.CompanyId, new { kind, ev.SizeBytes });
                return (201, EvDto(ev));
            }, ct);
        }).DisableAntiforgery();

        api.MapPost("/technicians/me/assignments/{aid:guid}/scope-change", async Task<IResult> (Guid aid, ScopeReq r, ClaimsPrincipal p, AppDbContext db, HttpContext http, CancellationToken ct) =>
        {
            var uid = Uid(p);
            return await Idem.RunAsync(db, http, $"tech-scope:{uid}", async () =>
            {
                var m = await Mine(db, p, aid, ct);
                if (m is null) return (404, new { error = "Not found." });
                var (t, a, j) = m.Value;
                if (a.Status != AssignmentStatus.Accepted || j.Status is not (JobStatus.Arrived or JobStatus.InProgress)) return (409, new { error = "Scope changes can be reported while you are on site." });
                if (string.IsNullOrWhiteSpace(r.Description) || r.Description.Length > 2000) return (400, new { error = "description is required (max 2000 characters)." });
                var sc = new JobScopeChange { JobId = j.Id, AssignmentId = a.Id, Description = r.Description.Trim(), RequestedBy = uid };
                db.JobScopeChanges.Add(sc);
                await Notifier.NotifyHoldersAsync(db, j.CompanyId, "job.review", "job.scope_change", "Scope change reported", $"{t.DisplayName} reported a scope change on {j.Reference}.", ct);
                db.Audit(http, uid, "job.scope_change_reported", "job", j.Id.ToString(), j.CompanyId);
                return (201, new { id = sc.Id, status = sc.Status.ToString() });
            }, ct);
        });

        api.MapPost("/technicians/me/assignments/{aid:guid}/report", async Task<IResult> (Guid aid, ReportReq r, ClaimsPrincipal p, AppDbContext db, IConfiguration cfg, HttpContext http, CancellationToken ct) =>
        {
            var uid = Uid(p);
            return await Idem.RunAsync(db, http, $"tech-report:{uid}", async () =>
            {
                var m = await Mine(db, p, aid, ct);
                if (m is null) return (404, new { error = "Not found." });
                var (t, a, j) = m.Value;
                if (a.Status != AssignmentStatus.Accepted || j.Status is not (JobStatus.InProgress or JobStatus.ReturnedForCorrection))
                    return (409, new { error = $"A {j.Status} job cannot be submitted for review." });
                if (string.IsNullOrWhiteSpace(r.Summary) || r.Summary.Length > 4000) return (400, new { error = "summary is required (max 4000 characters)." });
                if (r.HoursWorked is < 0 or > 240) return (400, new { error = "hoursWorked must be between 0 and 240." });
                var minEvidence = int.TryParse(cfg["Jobs:MinEvidence"], out var me) ? me : 1;
                var since = await db.JobReviews.Where(x => x.JobId == j.Id && x.Decision == "Returned").MaxAsync(x => (DateTime?)x.At, ct) ?? DateTime.MinValue;
                var have = await db.JobEvidence.CountAsync(e => e.JobId == j.Id && e.UploadedAt > since, ct);
                if (have < minEvidence) return (409, new { error = $"Upload at least {minEvidence} piece(s) of evidence before submitting." });
                var version = await db.JobWorkReports.CountAsync(x => x.JobId == j.Id, ct) + 1;
                db.JobWorkReports.Add(new JobWorkReport { JobId = j.Id, AssignmentId = a.Id, Version = version, Summary = r.Summary.Trim(), HoursWorked = r.HoursWorked, SubmittedBy = uid });
                JobFlow.Move(db, j, JobStatus.AwaitingReview, uid, $"Work report v{version} submitted");
                await Notifier.NotifyHoldersAsync(db, j.CompanyId, "job.review", "job.awaiting_review", "Work ready for review", $"{t.DisplayName} submitted work on {j.Reference}.", ct);
                db.Audit(http, uid, "job.report_submitted", "job", j.Id.ToString(), j.CompanyId, new { version });
                return (200, new { status = JobStatus.AwaitingReview.ToString(), version });
            }, ct);
        });

        api.MapPost("/technicians/me/assignments/{aid:guid}/evidence/{eid:guid}/link", async Task<IResult> (Guid aid, Guid eid, ClaimsPrincipal p, AppDbContext db, SignedLinks links, CancellationToken ct) =>
        {
            var m = await Mine(db, p, aid, ct); if (m is null) return Results.NotFound();
            if (!await db.JobEvidence.AnyAsync(e => e.Id == eid && e.AssignmentId == aid, ct)) return Results.NotFound();
            return Results.Ok(new { url = "/evidence-files/" + links.Create(eid, Uid(p), DateTimeOffset.UtcNow), expiresInSeconds = links.TtlSeconds });
        });

        // ======== Company: review, scope changes, complaints, callbacks ========
        api.MapGet("/companies/{id:guid}/jobs/{jobId:guid}/execution", async Task<IResult> (Guid id, Guid jobId, ClaimsPrincipal p, AppDbContext db, AccessService access, CancellationToken ct) =>
        {
            if (Deny(await access.Company(Uid(p), id, "job.read", ct)) is { } d) return d;
            var j = await LoadJob(db, id, jobId, ct); if (j is null) return Results.NotFound();
            var reports = await db.JobWorkReports.Where(x => x.JobId == jobId).OrderBy(x => x.Version).Select(x => new { x.Id, x.Version, x.Summary, x.HoursWorked, x.SubmittedAt }).ToListAsync(ct);
            var evidence = await db.JobEvidence.Where(x => x.JobId == jobId).OrderBy(x => x.UploadedAt).ToListAsync(ct);
            var scope = await db.JobScopeChanges.Where(x => x.JobId == jobId).OrderBy(x => x.CreatedAt).ToListAsync(ct);
            var reviews = await db.JobReviews.Where(x => x.JobId == jobId).OrderBy(x => x.At).Select(x => new { x.Id, x.Decision, x.Note, x.ReviewerUserId, x.At }).ToListAsync(ct);
            var complaints = await db.JobComplaints.Where(x => x.JobId == jobId).OrderBy(x => x.CreatedAt).ToListAsync(ct);
            var rels = await db.JobRelationships.Where(x => x.ParentJobId == jobId || x.ChildJobId == jobId).ToListAsync(ct);
            return Results.Ok(new
            {
                job = new { j.Id, j.Reference, status = j.Status.ToString(), j.CompletedAt, j.WarrantyDays, j.WarrantyEndsAt },
                reports, evidence = evidence.Select(EvDto),
                scopeChanges = scope.Select(x => new { x.Id, x.Description, status = x.Status.ToString(), x.DecisionNote, x.CreatedAt, x.DecidedAt }),
                reviews,
                complaints = complaints.Select(x => new { x.Id, x.Description, x.Status, x.Resolution, x.CreatedAt, x.ResolvedAt }),
                related = rels.Select(x => new { x.Id, x.Type, x.ParentJobId, x.ChildJobId, x.ReworkResponsibility, x.UnderWarranty, x.Notes })
            });
        });

        api.MapPost("/companies/{id:guid}/evidence/{eid:guid}/link", async Task<IResult> (Guid id, Guid eid, ClaimsPrincipal p, AppDbContext db, AccessService access, SignedLinks links, CancellationToken ct) =>
        {
            var uid = Uid(p);
            if (Deny(await access.Company(uid, id, "job.read", ct)) is { } d) return d;
            var ok = await (from e in db.JobEvidence join j in db.Jobs on e.JobId equals j.Id where e.Id == eid && j.CompanyId == id select e.Id).AnyAsync(ct);   // company id is part of the lookup
            if (!ok) return Results.NotFound();
            return Results.Ok(new { url = "/evidence-files/" + links.Create(eid, uid, DateTimeOffset.UtcNow), expiresInSeconds = links.TtlSeconds });
        });

        // Bearer token still required; the link is bound to the evidence and the user, and access is re-checked here.
        api.MapGet("/evidence-files/{token}", async Task<IResult> (string token, ClaimsPrincipal p, AppDbContext db, AccessService access, SignedLinks links, IFileStore store, HttpContext http, CancellationToken ct) =>
        {
            var uid = Uid(p);
            var v = links.Validate(token, DateTimeOffset.UtcNow);
            if (v is null || v.Value.UserId != uid) return Results.NotFound();
            var ev = await db.JobEvidence.FirstOrDefaultAsync(e => e.Id == v.Value.DocId, ct);
            if (ev is null) return Results.NotFound();
            var job = await db.Jobs.FirstAsync(j => j.Id == ev.JobId, ct);
            var ownTechnician = await (from a in db.Assignments join t in db.Technicians on a.TechnicianId equals t.Id
                                       where a.Id == ev.AssignmentId && t.UserId == uid select a.Id).AnyAsync(ct);
            if (!ownTechnician && await access.Company(uid, job.CompanyId, "job.read", ct) != Access.Allowed) return Results.NotFound();
            var stream = await store.OpenAsync(ev.StorageKey, ct);
            if (stream is null) return Results.NotFound();
            db.Audit(http, uid, "job.evidence_viewed", "job_evidence", ev.Id.ToString(), job.CompanyId);
            await db.SaveChangesAsync(ct);
            http.Response.Headers["Cache-Control"] = "private, no-store";
            http.Response.Headers["X-Content-Type-Options"] = "nosniff";
            return Results.File(stream, ev.ContentType, ev.FileName);
        });

        api.MapPost("/companies/{id:guid}/jobs/{jobId:guid}/scope-changes/{scId:guid}/decision", async Task<IResult> (Guid id, Guid jobId, Guid scId, DecisionReq r, ClaimsPrincipal p, AppDbContext db, AccessService access, HttpContext http, CancellationToken ct) =>
        {
            var uid = Uid(p);
            if (Deny(await access.Company(uid, id, "job.review", ct)) is { } d) return d;
            if (r.Decision is not ("approve" or "reject")) return Bad("decision must be approve or reject.");
            var j = await LoadJob(db, id, jobId, ct); if (j is null) return Results.NotFound();
            var sc = await db.JobScopeChanges.FirstOrDefaultAsync(x => x.Id == scId && x.JobId == jobId, ct);
            if (sc is null) return Results.NotFound();
            if (sc.Status != ReviewStatus.Pending) return Results.Conflict(new { error = $"Already {sc.Status}." });
            sc.Status = r.Decision == "approve" ? ReviewStatus.Approved : ReviewStatus.Rejected; sc.DecidedBy = uid; sc.DecisionNote = r.Note?.Trim(); sc.DecidedAt = DateTime.UtcNow;
            var a = await db.Assignments.FirstAsync(x => x.Id == sc.AssignmentId, ct);
            var tech = await db.Technicians.FirstAsync(t => t.Id == a.TechnicianId, ct);
            JobFlow.Notify(db, tech.UserId, id, "job.scope_decision", "Scope change " + sc.Status.ToString().ToLowerInvariant(), $"Your scope change on {j.Reference} was {sc.Status.ToString().ToLowerInvariant()}.");
            db.Audit(http, uid, "job.scope_change_decided", "job", jobId.ToString(), id, new { scId, decision = r.Decision });
            await db.SaveChangesAsync(ct);
            return Results.Ok(new { id = sc.Id, status = sc.Status.ToString() });
        });

        api.MapPost("/companies/{id:guid}/jobs/{jobId:guid}/review", async Task<IResult> (Guid id, Guid jobId, ReviewReq r, ClaimsPrincipal p, AppDbContext db, AccessService access, HttpContext http, CancellationToken ct) =>
        {
            var uid = Uid(p);
            if (Deny(await access.Company(uid, id, "job.review", ct)) is { } d) return d;
            if (r.Decision is not ("approve" or "return")) return Bad("decision must be approve or return.");
            if (r.Decision == "return" && string.IsNullOrWhiteSpace(r.Note)) return Bad("A note explaining what must be corrected is required.");
            var j = await LoadJob(db, id, jobId, ct); if (j is null) return Results.NotFound();
            if (j.Status != JobStatus.AwaitingReview) return Results.Conflict(new { error = $"A {j.Status} job is not awaiting review." });
            var a = await db.Assignments.FirstAsync(x => x.JobId == jobId && x.Status == AssignmentStatus.Accepted, ct);
            var tech = await db.Technicians.FirstAsync(t => t.Id == a.TechnicianId, ct);
            if (tech.UserId == uid && !await access.IsSuper(uid, ct)) return Forbidden();   // nobody approves their own work (superadmin excepted)
            if (r.Decision == "approve" && await db.JobScopeChanges.AnyAsync(x => x.JobId == jobId && x.Status == ReviewStatus.Pending, ct))
                return Results.Conflict(new { error = "Decide the pending scope change(s) before approving." });

            var reportId = await db.JobWorkReports.Where(x => x.JobId == jobId).OrderByDescending(x => x.Version).Select(x => (Guid?)x.Id).FirstOrDefaultAsync(ct);
            db.JobReviews.Add(new JobReview { JobId = jobId, ReportId = reportId, ReviewerUserId = uid, Decision = r.Decision == "approve" ? "Approved" : "Returned", Note = r.Note?.Trim() });
            if (r.Decision == "approve")
            {
                JobFlow.Move(db, j, JobStatus.Completed, uid, r.Note?.Trim());
                j.CompletedAt = DateTime.UtcNow;
                if (j.WarrantyDays is { } days) j.WarrantyEndsAt = j.CompletedAt.Value.AddDays(days);
                JobFlow.Notify(db, tech.UserId, id, "job.completed", "Work approved", $"Job {j.Reference} was approved.");
                await FinanceFlow.AccrueAsync(db, j, uid, ct);   // financial workflow starts here, separately from the approval itself
            }
            else
            {
                JobFlow.Move(db, j, JobStatus.ReturnedForCorrection, uid, r.Note!.Trim());
                JobFlow.Notify(db, tech.UserId, id, "job.returned", "Work returned for correction", $"Job {j.Reference}: {r.Note!.Trim()}");
            }
            db.Audit(http, uid, r.Decision == "approve" ? "job.approved" : "job.returned", "job", jobId.ToString(), id);
            Outbox.Add(db, r.Decision == "approve" ? "job.approved" : "job.returned", "job", jobId.ToString(), id, new { status = j.Status.ToString() });
            await db.SaveChangesAsync(ct);
            return Results.Ok(new { status = j.Status.ToString(), j.CompletedAt, j.WarrantyEndsAt });
        });

        api.MapPost("/companies/{id:guid}/jobs/{jobId:guid}/complaints", async Task<IResult> (Guid id, Guid jobId, ComplaintReq r, ClaimsPrincipal p, AppDbContext db, AccessService access, HttpContext http, CancellationToken ct) =>
        {
            var uid = Uid(p);
            if (Deny(await AnyOf(access, uid, id, ct, "job.review", "job.manage")) is { } d) return d;
            if (string.IsNullOrWhiteSpace(r.Description) || r.Description.Length > 2000) return Bad("description is required (max 2000 characters).");
            var j = await LoadJob(db, id, jobId, ct); if (j is null) return Results.NotFound();
            if (j.Status is JobStatus.Open or JobStatus.Offered) return Results.Conflict(new { error = "A complaint needs work that has started." });
            var c = new JobComplaint { JobId = jobId, CompanyId = id, RaisedBy = uid, Description = r.Description.Trim() };
            db.JobComplaints.Add(c);
            db.Audit(http, uid, "job.complaint_raised", "job", jobId.ToString(), id);
            await db.SaveChangesAsync(ct);
            return Results.Created($"/companies/{id}/jobs/{jobId}/execution", new { id = c.Id, status = c.Status });
        });

        api.MapPost("/companies/{id:guid}/jobs/{jobId:guid}/complaints/{cid:guid}/resolve", async Task<IResult> (Guid id, Guid jobId, Guid cid, ResolveReq r, ClaimsPrincipal p, AppDbContext db, AccessService access, HttpContext http, CancellationToken ct) =>
        {
            var uid = Uid(p);
            if (Deny(await access.Company(uid, id, "job.review", ct)) is { } d) return d;
            if (string.IsNullOrWhiteSpace(r.Resolution)) return Bad("A resolution is required.");
            var c = await db.JobComplaints.FirstOrDefaultAsync(x => x.Id == cid && x.JobId == jobId && x.CompanyId == id, ct);
            if (c is null) return Results.NotFound();
            if (c.Status != "Open") return Results.Conflict(new { error = "Already resolved." });
            c.Status = "Resolved"; c.Resolution = r.Resolution.Trim(); c.ResolvedBy = uid; c.ResolvedAt = DateTime.UtcNow;
            db.Audit(http, uid, "job.complaint_resolved", "job", jobId.ToString(), id);
            await db.SaveChangesAsync(ct);
            return Results.Ok(new { id = c.Id, status = c.Status });
        });

        // A callback is a new job linked to the finished one. Warranty terms are the business's; the job carries its own days.
        api.MapPost("/companies/{id:guid}/jobs/{jobId:guid}/callback", async Task<IResult> (Guid id, Guid jobId, CallbackReq r, ClaimsPrincipal p, AppDbContext db, AccessService access, HttpContext http, CancellationToken ct) =>
        {
            var uid = Uid(p);
            if (Deny(await AnyOf(access, uid, id, ct, "job.review", "job.manage")) is { } d) return d;
            var start = r.ScheduledStart.UtcDateTime; var end = r.ScheduledEnd.UtcDateTime;
            if (end <= start || end <= DateTime.UtcNow) return Bad("scheduledEnd must be after scheduledStart and in the future.");
            var resp = (r.Responsibility ?? "undetermined").Trim().ToLowerInvariant();
            if (!Responsibilities.Contains(resp)) return Bad("responsibility must be: " + string.Join(", ", Responsibilities));
            var parent = await LoadJob(db, id, jobId, ct); if (parent is null) return Results.NotFound();
            if (parent.Status != JobStatus.Completed) return Results.Conflict(new { error = "Only a completed job can have a callback." });
            if (r.ComplaintId is { } cid && !await db.JobComplaints.AnyAsync(x => x.Id == cid && x.JobId == jobId, ct)) return Bad("Unknown complaint for this job.");

            var underWarranty = parent.WarrantyEndsAt is { } w && DateTime.UtcNow <= w;
            var child = new Job { Reference = NewReference(), CompanyId = id, CustomerId = parent.CustomerId, LocationId = parent.LocationId, TradeId = parent.TradeId,
                Description = $"Callback for {parent.Reference}: " + (string.IsNullOrWhiteSpace(r.Notes) ? parent.Description : r.Notes.Trim()),
                Priority = JobPriority.High, ScheduledStart = start, ScheduledEnd = end, CreatedBy = uid };
            db.Jobs.Add(child);
            foreach (var s in await db.JobRequiredSkills.Where(x => x.JobId == jobId).Select(x => x.SkillId).ToListAsync(ct))
                db.JobRequiredSkills.Add(new JobRequiredSkill { JobId = child.Id, SkillId = s });
            db.JobStatusHistory.Add(new JobStatusHistory { JobId = child.Id, FromStatus = null, ToStatus = JobStatus.Open, ActorUserId = uid, Reason = $"callback of {parent.Reference}" });
            db.JobRelationships.Add(new JobRelationship { ParentJobId = jobId, ChildJobId = child.Id, ReworkResponsibility = resp, UnderWarranty = underWarranty, Notes = r.Notes?.Trim(), ComplaintId = r.ComplaintId, CreatedBy = uid });
            db.Audit(http, uid, "job.callback_created", "job", child.Id.ToString(), id, new { parent = parent.Reference, underWarranty, responsibility = resp });
            await db.SaveChangesAsync(ct);
            return Results.Created($"/companies/{id}/jobs/{child.Id}", new { id = child.Id, child.Reference, underWarranty, responsibility = resp });
        });
    }
}
