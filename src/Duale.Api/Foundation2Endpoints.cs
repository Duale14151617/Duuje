using System.Security.Claims;
using System.Security.Cryptography;
using System.Text;
using Duale.Api.Auth;
using Duale.Api.Data;
using Duale.Api.Domain;
using Duale.Api.Services;
using Microsoft.AspNetCore.Identity;
using Microsoft.EntityFrameworkCore;
using static Duale.Api.Endpoints;
namespace Duale.Api;

public record BranchReq(string? Name, string? Address);
public record BranchStatusReq(bool Active);
public record BranchMembersReq(List<Guid>? MembershipIds);
public record ServiceAreasReq(List<Guid>? ServiceAreaIds);
public record MfaVerifyReq(string? MfaToken, string? Code);
public record CodeReq(string? Code);
public record MfaDisableReq(string? Password, string? Code);
public record RecoveryRequestReq(string? Email);
public record RecoveryResetReq(string? Token, string? NewPassword, string? Code);

public static class Foundation2Endpoints
{
    static readonly string[] DocKinds = ["identity", "qualification", "other"];
    static string Sha(string s) => Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(s))).ToLowerInvariant();

    // Content type comes from the file's own bytes; the client-supplied type and extension are ignored.
    internal static string? Sniff(byte[] d)
    {
        if (d.Length >= 5 && d[0] == 0x25 && d[1] == 0x50 && d[2] == 0x44 && d[3] == 0x46 && d[4] == 0x2D) return "application/pdf";
        if (d.Length >= 3 && d[0] == 0xFF && d[1] == 0xD8 && d[2] == 0xFF) return "image/jpeg";
        if (d.Length >= 8 && d[0] == 0x89 && d[1] == 0x50 && d[2] == 0x4E && d[3] == 0x47 && d[4] == 0x0D && d[5] == 0x0A && d[6] == 0x1A && d[7] == 0x0A) return "image/png";
        return null;
    }
    static object Dto(TechnicianDocument d) => new { d.Id, d.Kind, d.FileName, d.ContentType, d.SizeBytes, status = d.Status.ToString(), d.ReviewNote, d.ExpiresOn, d.UploadedAt };

    public static void Map(WebApplication app, RouteGroupBuilder anon, RouteGroupBuilder api)
    {
        MapMe(api); MapBranches(api); MapServiceAreas(api); MapDocuments(app, api); MapMfa(anon, api); MapRecovery(anon, api);
    }

    // ======== Who am I (drives which parts of the UI are offered; the backend still authorizes every call) ========
    static void MapMe(RouteGroupBuilder api)
    {
        api.MapGet("/me", async Task<IResult> (ClaimsPrincipal p, AppDbContext db, AccessService access, CancellationToken ct) =>
        {
            var uid = Uid(p);
            var u = await db.Users.FirstAsync(x => x.Id == uid, ct);
            var companies = await (from m in db.Memberships join c in db.Companies on m.CompanyId equals c.Id
                                   where m.UserId == uid && m.Status == MembershipStatus.Active
                                   select new { c.Id, c.DisplayName, verification = c.Verification.ToString(),
                                                roles = db.MembershipRoles.Where(r => r.MembershipId == m.Id).Select(r => r.RoleCode).ToList() }).ToListAsync(ct);
            return Results.Ok(new
            {
                u.Id, u.Email, u.DisplayName, u.MfaEnabled, emailVerified = u.EmailVerifiedAt != null,
                isTechnician = await db.Technicians.AnyAsync(t => t.UserId == uid, ct),
                platform = new
                {
                    companyVerify = await access.HasPlatform(uid, "company.verify", ct),
                    technicianVerify = await access.HasPlatform(uid, "technician.verify", ct),
                    catalog = await access.HasPlatform(uid, "catalog.manage", ct),
                    support = await access.HasPlatform(uid, "user.support", ct)
                },
                companies
            });
        });
    }

    // ======== Branches ========
    static void MapBranches(RouteGroupBuilder api)
    {
        api.MapGet("/companies/{id:guid}/branches", async Task<IResult> (Guid id, ClaimsPrincipal p, AppDbContext db, AccessService access, CancellationToken ct) =>
        {
            if (Deny(await access.Company(Uid(p), id, "company.read", ct)) is { } d) return d;
            var rows = await db.Branches.Where(b => b.CompanyId == id).OrderBy(b => b.Name)
                .Select(b => new { b.Id, b.Name, b.Address, status = b.Status.ToString(), memberCount = db.BranchMemberships.Count(m => m.BranchId == b.Id) }).ToListAsync(ct);
            return Results.Ok(rows);
        });

        api.MapPost("/companies/{id:guid}/branches", async Task<IResult> (Guid id, BranchReq r, ClaimsPrincipal p, AppDbContext db, AccessService access, HttpContext http, CancellationToken ct) =>
        {
            var uid = Uid(p);
            if (Deny(await access.Company(uid, id, "branch.manage", ct)) is { } d) return d;
            if (!await db.Companies.AnyAsync(c => c.Id == id && c.Verification == VerificationStatus.Approved, ct)) return Results.Conflict(new { error = "Company must be approved first." });
            var name = (r.Name ?? "").Trim();
            if (name.Length is 0 or > 120) return Bad("name is required (max 120 characters).");
            if (await db.Branches.AnyAsync(b => b.CompanyId == id && b.Name == name, ct)) return Results.Conflict(new { error = "A branch with that name already exists." });
            var br = new Branch { CompanyId = id, Name = name, Address = r.Address?.Trim() };
            db.Branches.Add(br);
            db.Audit(http, uid, "branch.created", "branch", br.Id.ToString(), id);
            await db.SaveChangesAsync(ct);
            return Results.Created($"/companies/{id}/branches", new { br.Id, br.Name, br.Address, status = br.Status.ToString() });
        });

        api.MapPut("/companies/{id:guid}/branches/{bid:guid}", async Task<IResult> (Guid id, Guid bid, BranchReq r, ClaimsPrincipal p, AppDbContext db, AccessService access, HttpContext http, CancellationToken ct) =>
        {
            var uid = Uid(p);
            if (Deny(await access.Company(uid, id, "branch.manage", ct)) is { } d) return d;
            var br = await db.Branches.FirstOrDefaultAsync(b => b.Id == bid && b.CompanyId == id, ct);   // company id is part of the lookup
            if (br is null) return Results.NotFound();
            var name = (r.Name ?? "").Trim();
            if (name.Length is 0 or > 120) return Bad("name is required (max 120 characters).");
            if (await db.Branches.AnyAsync(b => b.CompanyId == id && b.Name == name && b.Id != bid, ct)) return Results.Conflict(new { error = "A branch with that name already exists." });
            br.Name = name; br.Address = r.Address?.Trim();
            db.Audit(http, uid, "branch.updated", "branch", bid.ToString(), id);
            await db.SaveChangesAsync(ct);
            return Results.Ok(new { br.Id, br.Name, br.Address, status = br.Status.ToString() });
        });

        // Branches are closed, never deleted, so history that refers to them stays intact.
        api.MapPost("/companies/{id:guid}/branches/{bid:guid}/status", async Task<IResult> (Guid id, Guid bid, BranchStatusReq r, ClaimsPrincipal p, AppDbContext db, AccessService access, HttpContext http, CancellationToken ct) =>
        {
            var uid = Uid(p);
            if (Deny(await access.Company(uid, id, "branch.manage", ct)) is { } d) return d;
            var br = await db.Branches.FirstOrDefaultAsync(b => b.Id == bid && b.CompanyId == id, ct);
            if (br is null) return Results.NotFound();
            br.Status = r.Active ? AccountStatus.Active : AccountStatus.Suspended;
            db.Audit(http, uid, r.Active ? "branch.reopened" : "branch.closed", "branch", bid.ToString(), id);
            await db.SaveChangesAsync(ct);
            return Results.NoContent();
        });

        api.MapPut("/companies/{id:guid}/branches/{bid:guid}/members", async Task<IResult> (Guid id, Guid bid, BranchMembersReq r, ClaimsPrincipal p, AppDbContext db, AccessService access, HttpContext http, CancellationToken ct) =>
        {
            var uid = Uid(p);
            if (Deny(await access.Company(uid, id, "branch.manage", ct)) is { } d) return d;
            if (!await db.Branches.AnyAsync(b => b.Id == bid && b.CompanyId == id && b.Status == AccountStatus.Active, ct)) return Results.NotFound();
            var wanted = (r.MembershipIds ?? new List<Guid>()).Distinct().ToList();
            // every membership must belong to THIS company and be active
            var valid = await db.Memberships.CountAsync(m => wanted.Contains(m.Id) && m.CompanyId == id && m.Status == MembershipStatus.Active, ct);
            if (valid != wanted.Count) return Bad("One or more membershipIds do not belong to this company.");
            var current = await db.BranchMemberships.Where(x => x.BranchId == bid).ToListAsync(ct);
            db.BranchMemberships.RemoveRange(current.Where(c => !wanted.Contains(c.MembershipId)));
            foreach (var m in wanted.Except(current.Select(c => c.MembershipId))) db.BranchMemberships.Add(new BranchMembership { BranchId = bid, MembershipId = m });
            db.Audit(http, uid, "branch.members_updated", "branch", bid.ToString(), id, new { count = wanted.Count });
            await db.SaveChangesAsync(ct);
            return Results.NoContent();
        });
    }

    // ======== Service areas ========
    static void MapServiceAreas(RouteGroupBuilder api)
    {
        api.MapGet("/catalog/service-areas", async Task<IResult> (AppDbContext db, CancellationToken ct) =>
            Results.Ok(await db.ServiceAreas.Where(a => a.Active).OrderBy(a => a.Name).Select(a => new { a.Id, a.Name }).ToListAsync(ct)));

        api.MapPost("/platform/service-areas", async Task<IResult> (NameReq r, ClaimsPrincipal p, AppDbContext db, AccessService access, HttpContext http, CancellationToken ct) =>
        {
            var uid = Uid(p);
            if (!await access.HasPlatform(uid, "catalog.manage", ct)) return Forbidden();
            var name = (r.Name ?? "").Trim();
            if (name.Length is 0 or > 120) return Bad("name is required (max 120 characters).");
            if (await db.ServiceAreas.AnyAsync(a => a.Name == name, ct)) return Results.Conflict(new { error = "Service area already exists." });
            var a = new ServiceArea { Name = name };
            db.ServiceAreas.Add(a);
            db.Audit(http, uid, "catalog.service_area_created", "service_area", a.Id.ToString());
            await db.SaveChangesAsync(ct);
            return Results.Created("/catalog/service-areas", new { a.Id, a.Name });
        });

        api.MapGet("/technicians/me/service-areas", async Task<IResult> (ClaimsPrincipal p, AppDbContext db, CancellationToken ct) =>
        {
            var uid = Uid(p);
            var t = await db.Technicians.FirstOrDefaultAsync(x => x.UserId == uid, ct);
            if (t is null) return Results.NotFound();
            return Results.Ok(await (from x in db.TechnicianServiceAreas join a in db.ServiceAreas on x.ServiceAreaId equals a.Id
                                     where x.TechnicianId == t.Id select new { a.Id, a.Name }).ToListAsync(ct));
        });

        api.MapPut("/technicians/me/service-areas", async Task<IResult> (ServiceAreasReq r, ClaimsPrincipal p, AppDbContext db, HttpContext http, CancellationToken ct) =>
        {
            var uid = Uid(p);
            var t = await db.Technicians.FirstOrDefaultAsync(x => x.UserId == uid, ct);
            if (t is null) return Results.NotFound();
            var wanted = (r.ServiceAreaIds ?? new List<Guid>()).Distinct().ToList();
            if (wanted.Count > 20) return Bad("At most 20 service areas.");
            if (await db.ServiceAreas.CountAsync(a => wanted.Contains(a.Id) && a.Active, ct) != wanted.Count) return Bad("One or more serviceAreaIds are unknown or inactive.");
            var current = await db.TechnicianServiceAreas.Where(x => x.TechnicianId == t.Id).ToListAsync(ct);
            db.TechnicianServiceAreas.RemoveRange(current.Where(c => !wanted.Contains(c.ServiceAreaId)));
            foreach (var a in wanted.Except(current.Select(c => c.ServiceAreaId))) db.TechnicianServiceAreas.Add(new TechnicianServiceArea { TechnicianId = t.Id, ServiceAreaId = a });
            db.Audit(http, uid, "technician.service_areas_updated", "technician", t.Id.ToString());
            await db.SaveChangesAsync(ct);
            return Results.NoContent();
        });
    }

    // ======== Technician documents ========
    static void MapDocuments(WebApplication app, RouteGroupBuilder api)
    {
        api.MapGet("/technicians/me/documents", async Task<IResult> (ClaimsPrincipal p, AppDbContext db, CancellationToken ct) =>
        {
            var uid = Uid(p);
            var t = await db.Technicians.FirstOrDefaultAsync(x => x.UserId == uid, ct);
            if (t is null) return Results.NotFound();
            var rows = await db.TechnicianDocuments.Where(d => d.TechnicianId == t.Id).OrderByDescending(d => d.UploadedAt).ToListAsync(ct);
            return Results.Ok(rows.Select(Dto));
        });

        // Bearer-token API, so antiforgery (a cookie/CSRF defence) does not apply.
        api.MapPost("/technicians/me/documents", async Task<IResult> (HttpRequest req, ClaimsPrincipal p, AppDbContext db, IFileStore store, IUploadScanner scanner, IConfiguration cfg, HttpContext http, CancellationToken ct) =>
        {
            var uid = Uid(p);
            var t = await db.Technicians.FirstOrDefaultAsync(x => x.UserId == uid, ct);
            if (t is null) return Results.NotFound();
            if (!req.HasFormContentType) return Bad("Send multipart/form-data with fields kind, file and optional expiresOn.");
            var form = await req.ReadFormAsync(ct);
            var kind = form["kind"].ToString().Trim().ToLowerInvariant();
            if (!DocKinds.Contains(kind)) return Bad("kind must be one of: " + string.Join(", ", DocKinds));
            DateOnly? expires = null;
            if (!string.IsNullOrWhiteSpace(form["expiresOn"])) { if (!DateOnly.TryParse(form["expiresOn"], out var e)) return Bad("expiresOn must be a date."); expires = e; }
            var file = form.Files.GetFile("file");
            if (file is null || file.Length == 0) return Bad("A file is required.");
            var max = long.TryParse(cfg["Files:MaxBytes"], out var m) ? m : 5_000_000;
            if (file.Length > max) return Results.StatusCode(413);
            if (await db.TechnicianDocuments.CountAsync(d => d.TechnicianId == t.Id, ct) >= 30) return Results.Conflict(new { error = "Document limit reached." });

            byte[] data;
            using (var ms = new MemoryStream()) { await file.CopyToAsync(ms, ct); data = ms.ToArray(); }
            var type = Sniff(data);
            if (type is null) return Bad("Only PDF, JPEG and PNG files are accepted.");
            if (!await scanner.IsCleanAsync(data, ct)) return Bad("The file failed the security scan.");

            var key = Guid.NewGuid().ToString("N");
            var name = Path.GetFileName(file.FileName ?? "document");
            var doc = new TechnicianDocument
            {
                TechnicianId = t.Id, Kind = kind, ExpiresOn = expires, ContentType = type, SizeBytes = data.Length, StorageKey = key,
                FileName = name.Length > 120 ? name[..120] : name, Sha256 = Convert.ToHexString(SHA256.HashData(data)).ToLowerInvariant()
            };
            await store.SaveAsync(key, data, ct);
            db.TechnicianDocuments.Add(doc);
            db.Audit(http, uid, "technician.document_uploaded", "technician_document", doc.Id.ToString(), null, new { kind, doc.SizeBytes });
            await db.SaveChangesAsync(ct);
            return Results.Created("/technicians/me/documents", Dto(doc));
        }).DisableAntiforgery();

        api.MapPost("/technicians/me/documents/{docId:guid}/link", async Task<IResult> (Guid docId, ClaimsPrincipal p, AppDbContext db, SignedLinks links, HttpContext http, CancellationToken ct) =>
        {
            var uid = Uid(p);
            var ok = await (from d in db.TechnicianDocuments join t in db.Technicians on d.TechnicianId equals t.Id
                            where d.Id == docId && t.UserId == uid select d.Id).AnyAsync(ct);   // ownership is part of the lookup
            if (!ok) return Results.NotFound();
            return Results.Ok(new { url = "/files/" + links.Create(docId, uid, DateTimeOffset.UtcNow), expiresInSeconds = links.TtlSeconds });
        });

        api.MapGet("/platform/technician-documents", async Task<IResult> (string? status, ClaimsPrincipal p, AppDbContext db, AccessService access, CancellationToken ct) =>
        {
            if (!await access.HasPlatform(Uid(p), "technician.verify", ct)) return Forbidden();
            var q = db.TechnicianDocuments.AsQueryable();
            if (Enum.TryParse<VerificationStatus>(status, true, out var s)) q = q.Where(d => d.Status == s);
            var rows = await (from d in q join t in db.Technicians on d.TechnicianId equals t.Id
                              orderby d.UploadedAt
                              select new { d.Id, d.TechnicianId, technician = t.DisplayName, d.Kind, d.FileName, d.ContentType, d.SizeBytes, status = d.Status.ToString(), d.ExpiresOn, d.UploadedAt }).Take(200).ToListAsync(ct);
            return Results.Ok(rows);
        });

        // Review queue for claimed skills (decisions go to the existing /platform/technicians/{id}/skills/{skillId}/decision).
        api.MapGet("/platform/technician-skills", async Task<IResult> (string? status, ClaimsPrincipal p, AppDbContext db, AccessService access, CancellationToken ct) =>
        {
            if (!await access.HasPlatform(Uid(p), "technician.verify", ct)) return Forbidden();
            var s = Enum.TryParse<VerificationStatus>(status, true, out var parsed) ? parsed : VerificationStatus.Pending;
            var rows = await (from ts in db.TechnicianSkills join t in db.Technicians on ts.TechnicianId equals t.Id
                              join sk in db.Skills on ts.SkillId equals sk.Id join tr in db.Trades on sk.TradeId equals tr.Id
                              where ts.Verification == s orderby t.DisplayName
                              select new { ts.TechnicianId, technician = t.DisplayName, ts.SkillId, skill = sk.Name, trade = tr.Name, ts.ExpiresOn }).Take(200).ToListAsync(ct);
            return Results.Ok(rows);
        });

        api.MapPost("/platform/technician-documents/{docId:guid}/link", async Task<IResult> (Guid docId, ClaimsPrincipal p, AppDbContext db, AccessService access, SignedLinks links, HttpContext http, CancellationToken ct) =>
        {
            var uid = Uid(p);
            if (!await access.HasPlatform(uid, "technician.verify", ct)) return Forbidden();
            if (!await db.TechnicianDocuments.AnyAsync(d => d.Id == docId, ct)) return Results.NotFound();
            return Results.Ok(new { url = "/files/" + links.Create(docId, uid, DateTimeOffset.UtcNow), expiresInSeconds = links.TtlSeconds });
        });

        api.MapPost("/platform/technician-documents/{docId:guid}/decision", async Task<IResult> (Guid docId, DecisionReq r, ClaimsPrincipal p, AppDbContext db, AccessService access, HttpContext http, CancellationToken ct) =>
        {
            var uid = Uid(p);
            if (!await access.HasPlatform(uid, "technician.verify", ct)) return Forbidden();
            var status = Verify.Map(r.Decision);
            if (status is null) return Bad("decision must be approve, reject or request_info.");
            if (r.ExpiresOn is { } e && e < DateOnly.FromDateTime(DateTime.UtcNow)) return Bad("expiresOn cannot be in the past.");
            var doc = await db.TechnicianDocuments.FirstOrDefaultAsync(d => d.Id == docId, ct);
            if (doc is null) return Results.NotFound();
            // Separation of duties: nobody reviews their own documents.
            if (await db.Technicians.AnyAsync(t => t.Id == doc.TechnicianId && t.UserId == uid, ct) && !await access.IsSuper(uid, ct)) return Forbidden();
            if (doc.Status != VerificationStatus.Pending) return Results.Conflict(new { error = $"Document is {doc.Status}; only Pending documents can be decided." });
            doc.Status = status.Value; doc.ReviewNote = r.Note?.Trim(); doc.ReviewedBy = uid; doc.ReviewedAt = DateTime.UtcNow;
            if (status == VerificationStatus.Approved && r.ExpiresOn is { } ex) doc.ExpiresOn = ex;
            var techUser = await db.Technicians.Where(t => t.Id == doc.TechnicianId).Select(t => t.UserId).FirstAsync(ct);
            JobFlow.Notify(db, techUser, null, "document.decided", "Document reviewed", $"Your {doc.Kind} document was {status.ToString()!.ToLowerInvariant()}.");
            db.Audit(http, uid, "technician.document_decided", "technician_document", docId.ToString(), null, new { decision = r.Decision });
            await db.SaveChangesAsync(ct);
            return Results.NoContent();
        });

        // The only way to read a file: a short-lived link bound to the document and the user it was issued to.
        // The bearer token is still required, so a leaked link is useless to anyone else.
        api.MapGet("/files/{token}", async Task<IResult> (string token, ClaimsPrincipal p, AppDbContext db, AccessService access, SignedLinks links, IFileStore store, HttpContext http, CancellationToken ct) =>
        {
            var uid = Uid(p);
            var v = links.Validate(token, DateTimeOffset.UtcNow);
            if (v is null || v.Value.UserId != uid) return Results.NotFound();
            var doc = await db.TechnicianDocuments.FirstOrDefaultAsync(d => d.Id == v.Value.DocId, ct);
            if (doc is null) return Results.NotFound();
            var owner = await db.Technicians.AnyAsync(t => t.Id == doc.TechnicianId && t.UserId == uid, ct);
            if (!owner && !await access.HasPlatform(uid, "technician.verify", ct)) return Results.NotFound();   // permission re-checked at read time
            var stream = await store.OpenAsync(doc.StorageKey, ct);
            if (stream is null) return Results.NotFound();
            db.Audit(http, uid, "technician.document_viewed", "technician_document", doc.Id.ToString());
            await db.SaveChangesAsync(ct);
            http.Response.Headers["Cache-Control"] = "private, no-store";
            http.Response.Headers["X-Content-Type-Options"] = "nosniff";
            return Results.File(stream, doc.ContentType, doc.FileName);
        });
    }

    // ======== MFA (TOTP) ========
    static void MapMfa(RouteGroupBuilder anon, RouteGroupBuilder api)
    {
        anon.MapPost("/mfa/verify", async Task<IResult> (MfaVerifyReq r, AppDbContext db, MfaTokens mfaTokens, MfaService mfa, TokenService tokens, HttpContext http, CancellationToken ct) =>
        {
            var uid = mfaTokens.Read(r.MfaToken);
            if (uid is null) return Results.Unauthorized();
            var u = await db.Users.FirstOrDefaultAsync(x => x.Id == uid && x.Status == AccountStatus.Active && x.MfaEnabled, ct);
            if (u is null) return Results.Unauthorized();
            var (ok, error) = await mfa.CheckAsync(u, r.Code, ct);
            if (!ok) return Results.Json(new { error }, statusCode: 401);
            return Results.Ok(new { token = tokens.Issue(u), expiresInSeconds = 1800 });
        });

        api.MapPost("/auth/mfa/setup", async Task<IResult> (ClaimsPrincipal p, AppDbContext db, SecretBox box, HttpContext http, CancellationToken ct) =>
        {
            var uid = Uid(p);
            var u = await db.Users.FirstAsync(x => x.Id == uid, ct);
            if (u.MfaEnabled) return Results.Conflict(new { error = "MFA is already enabled." });
            var secret = Totp.NewSecret();
            u.MfaSecretEnc = box.Seal(secret); u.MfaLastStep = 0;
            db.Audit(http, uid, "user.mfa_setup_started", "user", uid.ToString());
            await db.SaveChangesAsync(ct);
            var uri = $"otpauth://totp/Duale%20BuildLink:{Uri.EscapeDataString(u.Email)}?secret={secret}&issuer=Duale%20BuildLink&digits=6&period=30";
            return Results.Ok(new { secret, otpauthUri = uri });
        });

        api.MapPost("/auth/mfa/enable", async Task<IResult> (CodeReq r, ClaimsPrincipal p, AppDbContext db, SecretBox box, MfaService mfa, HttpContext http, CancellationToken ct) =>
        {
            var uid = Uid(p);
            var u = await db.Users.FirstAsync(x => x.Id == uid, ct);
            if (u.MfaEnabled || u.MfaSecretEnc is null) return Results.Conflict(new { error = "Start setup first." });
            var step = Totp.Verify(Totp.FromBase32(box.Open(u.MfaSecretEnc)), r.Code?.Trim(), DateTimeOffset.UtcNow, 0);
            if (step is null) return Bad("Invalid code.");
            u.MfaEnabled = true; u.MfaLastStep = step.Value; u.MfaFailures = 0;
            var codes = mfa.NewRecoveryCodes();
            foreach (var c in codes) db.MfaRecoveryCodes.Add(new MfaRecoveryCode { UserId = uid, CodeHash = c.Hash });
            db.Audit(http, uid, "user.mfa_enabled", "user", uid.ToString());
            await db.SaveChangesAsync(ct);
            return Results.Ok(new { recoveryCodes = codes.Select(c => c.Plain) });   // shown once; only hashes are stored
        });

        api.MapPost("/auth/mfa/disable", async Task<IResult> (MfaDisableReq r, ClaimsPrincipal p, AppDbContext db, IPasswordHasher<User> hasher, MfaService mfa, HttpContext http, CancellationToken ct) =>
        {
            var uid = Uid(p);
            var u = await db.Users.FirstAsync(x => x.Id == uid, ct);
            if (!u.MfaEnabled) return Results.Conflict(new { error = "MFA is not enabled." });
            if (hasher.VerifyHashedPassword(u, u.PasswordHash, r.Password ?? "") == PasswordVerificationResult.Failed) return Results.Json(new { error = "Invalid credentials." }, statusCode: 401);
            var (ok, error) = await mfa.CheckAsync(u, r.Code, ct);
            if (!ok) return Results.Json(new { error }, statusCode: 401);
            u.MfaEnabled = false; u.MfaSecretEnc = null; u.TokenVersion++;
            db.MfaRecoveryCodes.RemoveRange(db.MfaRecoveryCodes.Where(c => c.UserId == uid));
            db.Audit(http, uid, "user.mfa_disabled", "user", uid.ToString());
            await db.SaveChangesAsync(ct);
            return Results.NoContent();
        });
    }

    // ======== Account recovery ========
    static void MapRecovery(RouteGroupBuilder anon, RouteGroupBuilder api)
    {
        // Always 204 so the endpoint cannot be used to discover which emails are registered.
        anon.MapPost("/recovery/request", async Task<IResult> (RecoveryRequestReq r, AppDbContext db, IRecoveryDelivery delivery, HttpContext http, CancellationToken ct) =>
        {
            var email = (r.Email ?? "").Trim().ToLowerInvariant();
            var u = await db.Users.FirstOrDefaultAsync(x => x.Email == email && x.Status == AccountStatus.Active, ct);
            if (u is not null)
            {
                foreach (var old in await db.PasswordResetTokens.Where(t => t.UserId == u.Id && t.UsedAt == null).ToListAsync(ct)) old.UsedAt = DateTime.UtcNow;
                var token = Convert.ToBase64String(RandomNumberGenerator.GetBytes(32)).TrimEnd('=').Replace('+', '-').Replace('/', '_');
                var expires = DateTime.UtcNow.AddMinutes(30);
                db.PasswordResetTokens.Add(new PasswordResetToken { UserId = u.Id, TokenHash = Sha(token), ExpiresAt = expires });
                db.Audit(http, u.Id, "user.recovery_requested", "user", u.Id.ToString());
                await db.SaveChangesAsync(ct);
                await delivery.SendAsync(u.Email, token, expires, ct);
            }
            return Results.NoContent();
        });

        anon.MapPost("/recovery/reset", async Task<IResult> (RecoveryResetReq r, AppDbContext db, IPasswordHasher<User> hasher, MfaService mfa, HttpContext http, CancellationToken ct) =>
        {
            const string generic = "Invalid or expired recovery token.";
            if ((r.NewPassword?.Length ?? 0) < 12) return Bad("newPassword must be at least 12 characters.");
            if (string.IsNullOrWhiteSpace(r.Token)) return Bad(generic);
            var hash = Sha(r.Token);
            var t = await db.PasswordResetTokens.FirstOrDefaultAsync(x => x.TokenHash == hash && x.UsedAt == null && x.ExpiresAt > DateTime.UtcNow, ct);
            if (t is null) return Bad(generic);
            var u = await db.Users.FirstOrDefaultAsync(x => x.Id == t.UserId && x.Status == AccountStatus.Active, ct);
            if (u is null) return Bad(generic);
            // Recovery must not be a way around MFA: the second factor is still required.
            if (u.MfaEnabled)
            {
                var (ok, error) = await mfa.CheckAsync(u, r.Code, ct);
                if (!ok) return Results.Json(new { error }, statusCode: 401);
            }
            u.PasswordHash = hasher.HashPassword(u, r.NewPassword!);
            u.TokenVersion++;                       // every existing session ends
            t.UsedAt = DateTime.UtcNow;
            db.Audit(http, u.Id, "user.password_reset", "user", u.Id.ToString());
            await db.SaveChangesAsync(ct);
            return Results.NoContent();
        });

        // Lost device AND lost recovery codes: a platform support user resets MFA after verifying identity out of band.
        api.MapPost("/platform/users/{userId:guid}/mfa-reset", async Task<IResult> (Guid userId, ClaimsPrincipal p, AppDbContext db, AccessService access, HttpContext http, CancellationToken ct) =>
        {
            var uid = Uid(p);
            if (!await access.HasPlatform(uid, "user.support", ct)) return Forbidden();
            if (userId == uid) return Forbidden();   // no self-service bypass through the support path
            var u = await db.Users.FirstOrDefaultAsync(x => x.Id == userId, ct);
            if (u is null) return Results.NotFound();
            u.MfaEnabled = false; u.MfaSecretEnc = null; u.MfaFailures = 0; u.MfaLockedUntil = null; u.TokenVersion++;
            db.MfaRecoveryCodes.RemoveRange(db.MfaRecoveryCodes.Where(c => c.UserId == userId));
            JobFlow.Notify(db, userId, null, "security.mfa_reset", "Two-factor authentication was reset", "Support reset your two-factor authentication. Set it up again after signing in.");
            db.Audit(http, uid, "user.mfa_reset_by_support", "user", userId.ToString());
            await db.SaveChangesAsync(ct);
            return Results.NoContent();
        });
    }
}
