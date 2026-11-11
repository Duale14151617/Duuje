using Duale.Api.Data;
using Duale.Api.Domain;
using Microsoft.EntityFrameworkCore;
namespace Duale.Api.Services;

public static class Notifier
{
    public static void Notify(AppDbContext db, Guid userId, Guid? companyId, string kind, string title, string body) =>
        db.Notifications.Add(new Notification { UserId = userId, CompanyId = companyId, Kind = kind, Title = title, Body = body });

    // Everyone in the company whose role grants the permission (e.g. all reviewers).
    public static async Task<List<Guid>> HolderIdsAsync(AppDbContext db, Guid companyId, string permission, CancellationToken ct) =>
        await (from m in db.Memberships
                           join mr in db.MembershipRoles on m.Id equals mr.MembershipId
                           join rp in db.RolePermissions on mr.RoleCode equals rp.RoleCode
                           where m.CompanyId == companyId && m.Status == MembershipStatus.Active && rp.PermissionCode == permission
                           select m.UserId).Distinct().ToListAsync(ct);

    public static async Task NotifyHoldersAsync(AppDbContext db, Guid companyId, string permission, string kind, string title, string body, CancellationToken ct, Guid? except = null)
    {
        var users = await HolderIdsAsync(db, companyId, permission, ct);
        foreach (var u in users.Where(u => u != except)) Notify(db, u, companyId, kind, title, body);
    }
}
