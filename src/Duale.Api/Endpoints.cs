using System.Security.Claims;
using Duale.Api.Auth;
using Duale.Api.Data;
using Duale.Api.Domain;
using Microsoft.AspNetCore.Identity;
using Microsoft.EntityFrameworkCore;
namespace Duale.Api;

public record RegisterReq(string? Email, string? Password, string? DisplayName);
public record LoginReq(string? Email, string? Password);
public record CompanyReq(string? DisplayName, string? BusinessCategory, string? RegistrationRef, string? ContactEmail, string? ContactPhone);
public record AddMemberReq(string? Email, string? RoleCode);
public record DecisionReq(string? Decision, string? Note, DateOnly? ExpiresOn);
public record NameReq(string? Name);
public record TechnicianReq(string? DisplayName, string? Phone);
public record SkillsReq(List<Guid>? SkillIds);

public static class Endpoints
{
    internal static Guid Uid(ClaimsPrincipal p) => Guid.Parse(p.FindFirstValue("sub")!);
    internal static IResult Bad(string m) => Results.BadRequest(new { error = m });
    internal static IResult Forbidden() => Results.StatusCode(403);
    internal static IResult? Deny(Access a) => a switch { Access.NotMember => Results.NotFound(), Access.Forbidden => Forbidden(), _ => null };
    internal static object Dto(Company c) => new { c.Id, c.DisplayName, c.BusinessCategory, c.RegistrationRef, c.ContactEmail, c.ContactPhone, verification = c.Verification.ToString(), c.VerificationNote, status = c.Status.ToString() };

    public static void Map(WebApplication app)
    {
        var anon = app.MapGroup("/auth").RequireRateLimiting("auth");
        var api = app.MapGroup("").RequireAuthorization();

        // ---------- Auth ----------
        anon.MapPost("/register", async Task<IResult> (RegisterReq r, AppDbContext db, IPasswordHasher<User> hasher, IConfiguration cfg, HttpContext http, CancellationToken ct) =>
        {
            var email = (r.Email ?? "").Trim().ToLowerInvariant();
            if (!Valid.Email(email) || (r.Password?.Length ?? 0) < 12 || string.IsNullOrWhiteSpace(r.DisplayName))
                return Bad("A valid email, a display name and a password of at least 12 characters are required.");
            if (await db.Users.AnyAsync(x => x.Email == email, ct)) return Results.Conflict(new { error = "Email already registered." });
            var u = new User { Email = email, DisplayName = r.DisplayName.Trim() };
            u.PasswordHash = hasher.HashPassword(u, r.Password!);
            db.Users.Add(u);
            if (email == cfg["Bootstrap:SuperAdminEmail"]?.Trim().ToLowerInvariant())
            {
                db.PlatformRoleAssignments.Add(new PlatformRoleAssignment { UserId = u.Id, RoleCode = "platform_admin" });
                db.PlatformRoleAssignments.Add(new PlatformRoleAssignment { UserId = u.Id, RoleCode = "platform_finance" });
            }
            db.Audit(http, u.Id, "user.registered", "user", u.Id.ToString());
            try { await db.SaveChangesAsync(ct); }
            catch (DbUpdateException) { return Results.Conflict(new { error = "Email already registered." }); }
            return Results.Created($"/users/{u.Id}", new { u.Id, u.Email, u.DisplayName });
        });

        anon.MapPost("/login", async Task<IResult> (LoginReq r, AppDbContext db, IPasswordHasher<User> hasher, TokenService tokens, Duale.Api.Services.MfaTokens mfaTokens, CancellationToken ct) =>
        {
            var email = (r.Email ?? "").Trim().ToLowerInvariant();
            var u = await db.Users.FirstOrDefaultAsync(x => x.Email == email, ct);
            if (u is null || u.Status != AccountStatus.Active ||
                hasher.VerifyHashedPassword(u, u.PasswordHash, r.Password ?? "") == PasswordVerificationResult.Failed)
                return Results.Unauthorized();
            if (u.MfaEnabled) return Results.Ok(new { mfaRequired = true, mfaToken = mfaTokens.Issue(u) });
            return Results.Ok(new { token = tokens.Issue(u), expiresInSeconds = 1800 });
        });

        api.MapPost("/auth/logout-all", async Task<IResult> (ClaimsPrincipal p, AppDbContext db, HttpContext http, CancellationToken ct) =>
        {
            var uid = Uid(p);
            var u = await db.Users.FirstAsync(x => x.Id == uid, ct);
            u.TokenVersion++;
            db.Audit(http, uid, "user.sessions_revoked", "user", uid.ToString());
            await db.SaveChangesAsync(ct);
            return Results.NoContent();
        });

        // ---------- Company onboarding ----------
        api.MapPost("/companies", async Task<IResult> (CompanyReq r, ClaimsPrincipal p, AppDbContext db, HttpContext http, CancellationToken ct) =>
        {
            if (string.IsNullOrWhiteSpace(r.DisplayName) || string.IsNullOrWhiteSpace(r.BusinessCategory) || !Valid.Email((r.ContactEmail ?? "").Trim().ToLowerInvariant()))
                return Bad("displayName, businessCategory and a valid contactEmail are required.");
            var uid = Uid(p);
            var c = new Company { DisplayName = r.DisplayName.Trim(), BusinessCategory = r.BusinessCategory.Trim(), RegistrationRef = r.RegistrationRef?.Trim(), ContactEmail = r.ContactEmail!.Trim().ToLowerInvariant(), ContactPhone = r.ContactPhone?.Trim() };
            var m = new CompanyMembership { UserId = uid, CompanyId = c.Id };
            db.Companies.Add(c);
            db.Memberships.Add(m);
            db.MembershipRoles.Add(new MembershipRole { MembershipId = m.Id, RoleCode = "company_owner" });
            db.Audit(http, uid, "company.created", "company", c.Id.ToString(), c.Id);
            await db.SaveChangesAsync(ct);
            return Results.Created($"/companies/{c.Id}", Dto(c));
        });

        api.MapGet("/companies/{id:guid}", async Task<IResult> (Guid id, ClaimsPrincipal p, AppDbContext db, AccessService access, CancellationToken ct) =>
        {
            if (Deny(await access.Company(Uid(p), id, "company.read", ct)) is { } d) return d;
            return Results.Ok(Dto(await db.Companies.FirstAsync(c => c.Id == id, ct)));
        });

        api.MapPut("/companies/{id:guid}", async Task<IResult> (Guid id, CompanyReq r, ClaimsPrincipal p, AppDbContext db, AccessService access, HttpContext http, CancellationToken ct) =>
        {
            var uid = Uid(p);
            if (Deny(await access.Company(uid, id, "company.manage", ct)) is { } d) return d;
            if (string.IsNullOrWhiteSpace(r.DisplayName) || string.IsNullOrWhiteSpace(r.BusinessCategory) || !Valid.Email((r.ContactEmail ?? "").Trim().ToLowerInvariant()))
                return Bad("displayName, businessCategory and a valid contactEmail are required.");
            var c = await db.Companies.FirstAsync(x => x.Id == id, ct);
            c.DisplayName = r.DisplayName.Trim(); c.BusinessCategory = r.BusinessCategory.Trim();
            c.RegistrationRef = r.RegistrationRef?.Trim(); c.ContactEmail = r.ContactEmail!.Trim().ToLowerInvariant(); c.ContactPhone = r.ContactPhone?.Trim();
            var resubmitted = c.TryResubmit();   // answering a "request more information" puts it back in the review queue
            db.Audit(http, uid, resubmitted ? "company.resubmitted" : "company.updated", "company", id.ToString(), id);
            await db.SaveChangesAsync(ct);
            return Results.Ok(Dto(c));
        });

        // ---------- Staff ----------
        api.MapGet("/companies/{id:guid}/members", async Task<IResult> (Guid id, ClaimsPrincipal p, AppDbContext db, AccessService access, CancellationToken ct) =>
        {
            if (Deny(await access.Company(Uid(p), id, "staff.manage", ct)) is { } d) return d;
            var rows = await (from m in db.Memberships
                              join u in db.Users on m.UserId equals u.Id
                              where m.CompanyId == id && m.Status == MembershipStatus.Active
                              select new { m.Id, u.Email, u.DisplayName, Roles = db.MembershipRoles.Where(x => x.MembershipId == m.Id).Select(x => x.RoleCode).ToList() }).ToListAsync(ct);
            return Results.Ok(rows);
        });

        api.MapPost("/companies/{id:guid}/members", async Task<IResult> (Guid id, AddMemberReq r, ClaimsPrincipal p, AppDbContext db, AccessService access, HttpContext http, CancellationToken ct) =>
        {
            var uid = Uid(p);
            if (Deny(await access.Company(uid, id, "staff.manage", ct)) is { } d) return d;
            var company = await db.Companies.FirstAsync(c => c.Id == id, ct);
            if (company.Verification != VerificationStatus.Approved) return Results.Conflict(new { error = "Company must be approved before staff can be configured." });
            if (r.RoleCode is null || !Seed.CompanyRoles.Contains(r.RoleCode)) return Bad("roleCode must be a company role: " + string.Join(", ", Seed.CompanyRoles));
            var email = (r.Email ?? "").Trim().ToLowerInvariant();
            var target = await db.Users.FirstOrDefaultAsync(u => u.Email == email && u.Status == AccountStatus.Active, ct);
            if (target is null) return Results.NotFound(new { error = "No active user with that email." });

            var m = await db.Memberships.FirstOrDefaultAsync(x => x.UserId == target.Id && x.CompanyId == id, ct);
            if (m is null) { m = new CompanyMembership { UserId = target.Id, CompanyId = id }; db.Memberships.Add(m); }
            else
            {
                m.Status = MembershipStatus.Active;
                db.MembershipRoles.RemoveRange(db.MembershipRoles.Where(x => x.MembershipId == m.Id));
            }
            db.MembershipRoles.Add(new MembershipRole { MembershipId = m.Id, RoleCode = r.RoleCode });
            db.Audit(http, uid, "staff.role_granted", "membership", m.Id.ToString(), id, new { userId = target.Id, role = r.RoleCode });
            await db.SaveChangesAsync(ct);
            return Results.Ok(new { membershipId = m.Id, role = r.RoleCode });
        });

        api.MapDelete("/companies/{id:guid}/members/{membershipId:guid}", async Task<IResult> (Guid id, Guid membershipId, ClaimsPrincipal p, AppDbContext db, AccessService access, HttpContext http, CancellationToken ct) =>
        {
            var uid = Uid(p);
            if (Deny(await access.Company(uid, id, "staff.manage", ct)) is { } d) return d;
            // company id is part of the lookup: a membership id from another tenant simply isn't found
            var m = await db.Memberships.FirstOrDefaultAsync(x => x.Id == membershipId && x.CompanyId == id && x.Status == MembershipStatus.Active, ct);
            if (m is null) return Results.NotFound();
            var isOwner = await db.MembershipRoles.AnyAsync(x => x.MembershipId == m.Id && x.RoleCode == "company_owner", ct);
            if (isOwner)
            {
                var owners = await (from x in db.Memberships
                                    join r in db.MembershipRoles on x.Id equals r.MembershipId
                                    where x.CompanyId == id && x.Status == MembershipStatus.Active && r.RoleCode == "company_owner"
                                    select x.Id).CountAsync(ct);
                if (owners <= 1) return Results.Conflict(new { error = "A company must keep at least one owner." });
            }
            m.Status = MembershipStatus.Removed;
            db.Audit(http, uid, "staff.removed", "membership", m.Id.ToString(), id);
            await db.SaveChangesAsync(ct);
            return Results.NoContent();
        });

        api.MapGet("/companies/{id:guid}/audit", async Task<IResult> (Guid id, int? take, ClaimsPrincipal p, AppDbContext db, AccessService access, CancellationToken ct) =>
        {
            if (Deny(await access.Company(Uid(p), id, "audit.read", ct)) is { } d) return d;
            var rows = await db.AuditEvents.Where(a => a.CompanyId == id).OrderByDescending(a => a.OccurredAt).Take(Math.Clamp(take ?? 50, 1, 200))
                .Select(a => new { a.OccurredAt, a.ActorUserId, a.Action, a.ResourceType, a.ResourceId, a.CorrelationId }).ToListAsync(ct);
            return Results.Ok(rows);
        });

        // ---------- Platform: company verification ----------
        api.MapGet("/platform/companies", async Task<IResult> (string? status, ClaimsPrincipal p, AppDbContext db, AccessService access, CancellationToken ct) =>
        {
            if (!await access.HasPlatform(Uid(p), "company.verify", ct)) return Forbidden();
            var q = db.Companies.AsQueryable();
            if (Enum.TryParse<VerificationStatus>(status, true, out var s)) q = q.Where(c => c.Verification == s);
            var list = await q.OrderBy(c => c.CreatedAt).Take(200).ToListAsync(ct);
            return Results.Ok(list.Select(Dto));
        });

        api.MapPost("/platform/companies/{id:guid}/decision", async Task<IResult> (Guid id, DecisionReq r, ClaimsPrincipal p, AppDbContext db, AccessService access, HttpContext http, CancellationToken ct) =>
        {
            var uid = Uid(p);
            if (!await access.HasPlatform(uid, "company.verify", ct)) return Forbidden();
            if (Verify.Map(r.Decision) is null) return Bad("decision must be approve, reject or request_info.");
            var c = await db.Companies.FirstOrDefaultAsync(x => x.Id == id, ct);
            if (c is null) return Results.NotFound();
            // Separation of duties: reviewers cannot decide on a company they belong to.
            if (await db.Memberships.AnyAsync(m => m.CompanyId == id && m.UserId == uid && m.Status == MembershipStatus.Active, ct) && !await access.IsSuper(uid, ct)) return Forbidden();
            if (!c.TryDecide(r.Decision!, r.Note, out var err)) return Results.Conflict(new { error = err });
            db.Audit(http, uid, "company.verification_decided", "company", id.ToString(), id, new { decision = r.Decision });
            await db.SaveChangesAsync(ct);
            return Results.Ok(Dto(c));
        });

        // ---------- Trade & skill catalog ----------
        api.MapGet("/catalog/trades", async Task<IResult> (AppDbContext db, CancellationToken ct) =>
        {
            var trades = await db.Trades.Where(t => t.Active).OrderBy(t => t.Name).ToListAsync(ct);
            var skills = await db.Skills.Where(s => s.Active).OrderBy(s => s.Name).ToListAsync(ct);
            return Results.Ok(trades.Select(t => new { t.Id, t.Name, skills = skills.Where(s => s.TradeId == t.Id).Select(s => new { s.Id, s.Name }) }));
        });

        api.MapPost("/platform/trades", async Task<IResult> (NameReq r, ClaimsPrincipal p, AppDbContext db, AccessService access, HttpContext http, CancellationToken ct) =>
        {
            var uid = Uid(p);
            if (!await access.HasPlatform(uid, "catalog.manage", ct)) return Forbidden();
            if (string.IsNullOrWhiteSpace(r.Name)) return Bad("name is required.");
            var name = r.Name.Trim();
            if (await db.Trades.AnyAsync(t => t.Name == name, ct)) return Results.Conflict(new { error = "Trade already exists." });
            var t = new Trade { Name = name };
            db.Trades.Add(t);
            db.Audit(http, uid, "catalog.trade_created", "trade", t.Id.ToString());
            await db.SaveChangesAsync(ct);
            return Results.Created("/catalog/trades", new { t.Id, t.Name });
        });

        api.MapPost("/platform/trades/{tradeId:guid}/skills", async Task<IResult> (Guid tradeId, NameReq r, ClaimsPrincipal p, AppDbContext db, AccessService access, HttpContext http, CancellationToken ct) =>
        {
            var uid = Uid(p);
            if (!await access.HasPlatform(uid, "catalog.manage", ct)) return Forbidden();
            if (string.IsNullOrWhiteSpace(r.Name)) return Bad("name is required.");
            if (!await db.Trades.AnyAsync(t => t.Id == tradeId, ct)) return Results.NotFound();
            var name = r.Name.Trim();
            if (await db.Skills.AnyAsync(s => s.TradeId == tradeId && s.Name == name, ct)) return Results.Conflict(new { error = "Skill already exists." });
            var s = new Skill { TradeId = tradeId, Name = name };
            db.Skills.Add(s);
            db.Audit(http, uid, "catalog.skill_created", "skill", s.Id.ToString());
            await db.SaveChangesAsync(ct);
            return Results.Created("/catalog/trades", new { s.Id, s.Name });
        });

        // ---------- Technician profile & skills (self-service) ----------
        api.MapPost("/technicians/me", async Task<IResult> (TechnicianReq r, ClaimsPrincipal p, AppDbContext db, HttpContext http, CancellationToken ct) =>
        {
            var uid = Uid(p);
            if (string.IsNullOrWhiteSpace(r.DisplayName)) return Bad("displayName is required.");
            if (await db.Technicians.AnyAsync(t => t.UserId == uid, ct)) return Results.Conflict(new { error = "Technician profile already exists." });
            var t = new Technician { UserId = uid, DisplayName = r.DisplayName.Trim(), Phone = r.Phone?.Trim() };
            db.Technicians.Add(t);
            db.Audit(http, uid, "technician.created", "technician", t.Id.ToString());
            await db.SaveChangesAsync(ct);
            return Results.Created("/technicians/me", new { t.Id, t.DisplayName, t.Phone });
        });

        api.MapPut("/technicians/me", async Task<IResult> (TechnicianReq r, ClaimsPrincipal p, AppDbContext db, HttpContext http, CancellationToken ct) =>
        {
            var uid = Uid(p);
            if (string.IsNullOrWhiteSpace(r.DisplayName)) return Bad("displayName is required.");
            var t = await db.Technicians.FirstOrDefaultAsync(x => x.UserId == uid, ct);
            if (t is null) return Results.NotFound();
            var newPhone = r.Phone?.Trim();
            if (!string.Equals(t.Phone, newPhone, StringComparison.Ordinal)) t.PhoneVerifiedAt = null;   // a new number must be verified again
            t.DisplayName = r.DisplayName.Trim(); t.Phone = newPhone;
            db.Audit(http, uid, "technician.updated", "technician", t.Id.ToString());
            await db.SaveChangesAsync(ct);
            return Results.Ok(new { t.Id, t.DisplayName, t.Phone });
        });

        api.MapGet("/technicians/me", async Task<IResult> (ClaimsPrincipal p, AppDbContext db, CancellationToken ct) =>
        {
            var uid = Uid(p);
            var t = await db.Technicians.FirstOrDefaultAsync(x => x.UserId == uid, ct);
            if (t is null) return Results.NotFound();
            var rows = await (from ts in db.TechnicianSkills
                              join s in db.Skills on ts.SkillId equals s.Id
                              where ts.TechnicianId == t.Id
                              select new { s.Id, s.Name, ts.Verification, ts.ExpiresOn }).ToListAsync(ct);
            var today = DateOnly.FromDateTime(DateTime.UtcNow);
            var skills = rows.Select(x => new
            {
                x.Id, x.Name, verification = x.Verification.ToString(), x.ExpiresOn,
                eligible = new TechnicianSkill { Verification = x.Verification, ExpiresOn = x.ExpiresOn }.IsEligible(today)
            });
            return Results.Ok(new { t.Id, t.DisplayName, t.Phone, phoneVerified = t.PhoneVerifiedAt != null, skills });
        });

        // Replace the set of claimed skills. Newly claimed skills start Pending; existing reviews are preserved.
        api.MapPut("/technicians/me/skills", async Task<IResult> (SkillsReq r, ClaimsPrincipal p, AppDbContext db, HttpContext http, CancellationToken ct) =>
        {
            var uid = Uid(p);
            var t = await db.Technicians.FirstOrDefaultAsync(x => x.UserId == uid, ct);
            if (t is null) return Results.NotFound();
            var wanted = (r.SkillIds ?? new List<Guid>()).Distinct().ToList();
            var validCount = await db.Skills.CountAsync(s => wanted.Contains(s.Id) && s.Active, ct);
            if (validCount != wanted.Count) return Bad("One or more skillIds are unknown or inactive.");
            var current = await db.TechnicianSkills.Where(x => x.TechnicianId == t.Id).ToListAsync(ct);
            db.TechnicianSkills.RemoveRange(current.Where(c => !wanted.Contains(c.SkillId)));
            foreach (var id in wanted.Except(current.Select(c => c.SkillId)))
                db.TechnicianSkills.Add(new TechnicianSkill { TechnicianId = t.Id, SkillId = id });
            db.Audit(http, uid, "technician.skills_updated", "technician", t.Id.ToString());
            await db.SaveChangesAsync(ct);
            return Results.NoContent();
        });

        api.MapPost("/platform/technicians/{technicianId:guid}/skills/{skillId:guid}/decision", async Task<IResult> (Guid technicianId, Guid skillId, DecisionReq r, ClaimsPrincipal p, AppDbContext db, AccessService access, HttpContext http, CancellationToken ct) =>
        {
            var uid = Uid(p);
            if (!await access.HasPlatform(uid, "technician.verify", ct)) return Forbidden();
            var status = Verify.Map(r.Decision);
            if (status is null) return Bad("decision must be approve, reject or request_info.");
            if (r.ExpiresOn is { } e && e < DateOnly.FromDateTime(DateTime.UtcNow)) return Bad("expiresOn cannot be in the past.");
            var ts = await db.TechnicianSkills.FirstOrDefaultAsync(x => x.TechnicianId == technicianId && x.SkillId == skillId, ct);
            if (ts is null) return Results.NotFound();
            ts.Verification = status.Value;
            ts.ExpiresOn = status == VerificationStatus.Approved ? r.ExpiresOn : null;
            ts.ReviewedBy = uid; ts.ReviewedAt = DateTime.UtcNow;
            db.Audit(http, uid, "technician.skill_verification_decided", "technician_skill", $"{technicianId}/{skillId}", null, new { decision = r.Decision, expiresOn = r.ExpiresOn });
            await db.SaveChangesAsync(ct);
            return Results.NoContent();
        });

        Phase2Endpoints.Map(api);
        Phase3Endpoints.Map(api);
        Phase4Endpoints.Map(app, api);
        Phase5Endpoints.Map(api);
        Phase7Endpoints.Map(api);
        Phase8Endpoints.Map(api);
        Foundation2Endpoints.Map(app, anon, api);
    }
}
