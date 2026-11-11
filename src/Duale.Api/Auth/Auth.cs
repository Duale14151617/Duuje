using System.IdentityModel.Tokens.Jwt;
using System.Net.Mail;
using System.Text;
using Duale.Api.Data;
using Duale.Api.Domain;
using Microsoft.EntityFrameworkCore;
using Microsoft.IdentityModel.Tokens;
namespace Duale.Api.Auth;

public static class Valid
{
    public static bool Email(string e) => e.Length <= 254 && MailAddress.TryCreate(e, out var a) && a.Address == e;
}

public class TokenService(IConfiguration cfg)
{
    public static SymmetricSecurityKey Key(IConfiguration c) => new(Encoding.UTF8.GetBytes(c["Jwt:Key"]!));
    public string Issue(User u)
    {
        var claims = new[]
        {
            new System.Security.Claims.Claim("sub", u.Id.ToString()),
            new System.Security.Claims.Claim("tv", u.TokenVersion.ToString())
        };
        var t = new JwtSecurityToken(cfg["Jwt:Issuer"] ?? "duale-buildlink", cfg["Jwt:Audience"] ?? "duale-buildlink", claims,
            expires: DateTime.UtcNow.AddMinutes(30), signingCredentials: new SigningCredentials(Key(cfg), SecurityAlgorithms.HmacSha256));
        return new JwtSecurityTokenHandler().WriteToken(t);
    }
}

public enum Access { Allowed, NotMember, Forbidden }

// Every company-scoped request goes through here: membership + active company + role permission, read from the DB
// on each call (not from the token), so removals and role changes take effect immediately.
public class AccessService(AppDbContext db, IConfiguration cfg)
{
    // Which permissions need a second factor is a business decision: list them in Security:MfaRequiredPermissions
    // (e.g. "finance.refund.approve,finance.adjust,company.verify"). A user without MFA is then refused those permissions.
    async Task<bool> MfaBlocked(Guid userId, string permission, CancellationToken ct)
    {
        var list = cfg["Security:MfaRequiredPermissions"];
        if (string.IsNullOrWhiteSpace(list)) return false;
        if (!list.Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries).Contains(permission)) return false;
        return !await db.Users.AnyAsync(u => u.Id == userId && u.MfaEnabled, ct);
    }

    // Superadmin = the account whose email is set in Bootstrap:SuperAdminEmail. Full control: every platform permission, access to every
    // company, and no separation-of-duties blocks. Read from the DB on each call, like every other permission.
    public async Task<bool> IsSuper(Guid userId, CancellationToken ct)
    {
        var e = cfg["Bootstrap:SuperAdminEmail"]?.Trim().ToLowerInvariant();
        if (string.IsNullOrEmpty(e)) return false;
        return await db.Users.AnyAsync(u => u.Id == userId && u.Email == e && u.Status == AccountStatus.Active, ct);
    }

    public async Task<bool> HasPlatform(Guid userId, string permission, CancellationToken ct)
    {
        if (await IsSuper(userId, ct)) return true;
        var has = await (from a in db.PlatformRoleAssignments
                         join rp in db.RolePermissions on a.RoleCode equals rp.RoleCode
                         where a.UserId == userId && rp.PermissionCode == permission
                         select 1).AnyAsync(ct);
        return has && !await MfaBlocked(userId, permission, ct);
    }

    public async Task<Access> Company(Guid userId, Guid companyId, string permission, CancellationToken ct)
    {
        if (await IsSuper(userId, ct)) return Access.Allowed;
        var roles = await (from m in db.Memberships
                           join c in db.Companies on m.CompanyId equals c.Id
                           join mr in db.MembershipRoles on m.Id equals mr.MembershipId
                           where m.UserId == userId && m.CompanyId == companyId
                                 && m.Status == MembershipStatus.Active && c.Status == AccountStatus.Active
                           select mr.RoleCode).ToListAsync(ct);
        if (roles.Count == 0) return Access.NotMember;   // callers answer 404 so ids can't be probed across tenants
        var ok = await db.RolePermissions.AnyAsync(rp => roles.Contains(rp.RoleCode) && rp.PermissionCode == permission, ct);
        if (ok && await MfaBlocked(userId, permission, ct)) return Access.Forbidden;
        return ok ? Access.Allowed : Access.Forbidden;
    }
}
