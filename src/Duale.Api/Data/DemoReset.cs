using Microsoft.EntityFrameworkCore;
namespace Duale.Api.Data;

// One-shot demo cleanup, for when you cannot reach the database directly (for example, only a phone).
// Set Demo__KeepEmail (the account to keep) and Demo__ResetToken (any new text) in the host's environment and redeploy.
// It removes every other account and all demo data once per token: the token is remembered, so a restart never repeats it.
// Remove both variables afterwards. To run it again later, use a different token.
public static class DemoReset
{
    public static async Task RunIfRequestedAsync(AppDbContext db, IConfiguration cfg, ILogger log)
    {
        var token = cfg["Demo:ResetToken"]?.Trim();
        var keep = cfg["Demo:KeepEmail"]?.Trim().ToLowerInvariant();
        if (string.IsNullOrEmpty(token) || string.IsNullOrEmpty(keep) || !db.Database.IsNpgsql()) return;

        await db.Database.ExecuteSqlRawAsync("CREATE TABLE IF NOT EXISTS \"DemoResets\" (\"Token\" text PRIMARY KEY, \"RanAt\" timestamptz NOT NULL DEFAULT now())");
        var done = await db.Database.SqlQuery<int>($"SELECT count(*)::int AS \"Value\" FROM \"DemoResets\" WHERE \"Token\" = {token}").SingleAsync();
        if (done > 0) return;

        if (!await db.Users.AnyAsync(u => u.Email == keep))
        {
            log.LogWarning("Demo reset skipped: no account with the email in Demo__KeepEmail exists. Nothing was changed.");
            return;
        }

        await using var tx = await db.Database.BeginTransactionAsync();
        await db.Database.ExecuteSqlInterpolatedAsync($"CREATE TEMP TABLE keep_users ON COMMIT DROP AS SELECT * FROM \"Users\" WHERE \"Email\" = {keep}");
        await db.Database.ExecuteSqlRawAsync("CREATE TEMP TABLE keep_roles ON COMMIT DROP AS SELECT * FROM \"PlatformRoleAssignments\" WHERE \"UserId\" IN (SELECT \"Id\" FROM keep_users)");
        await db.Database.ExecuteSqlRawAsync(@"
DO $$
DECLARE t text;
BEGIN
  SELECT string_agg(format('%I', tablename), ', ') INTO t FROM pg_tables
  WHERE schemaname = 'public'
    AND tablename NOT IN ('Roles', 'Permissions', 'RolePermissions', 'Trades', 'Skills', 'ServiceAreas', '__EFMigrationsHistory', 'DemoResets');
  EXECUTE 'TRUNCATE TABLE ' || t;
END $$");
        await db.Database.ExecuteSqlRawAsync("INSERT INTO \"Users\" SELECT * FROM keep_users");
        await db.Database.ExecuteSqlRawAsync("INSERT INTO \"PlatformRoleAssignments\" SELECT * FROM keep_roles");
        await db.Database.ExecuteSqlInterpolatedAsync($"INSERT INTO \"DemoResets\" (\"Token\") VALUES ({token})");
        await tx.CommitAsync();
        log.LogWarning("Demo reset done: every account except the one in Demo__KeepEmail was removed. Remove Demo__ResetToken and Demo__KeepEmail from the environment.");
    }
}
