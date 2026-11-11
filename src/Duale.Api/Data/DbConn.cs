using Npgsql;
namespace Duale.Api.Data;

public static class DbConn
{
    // Accepts a normal Npgsql connection string, or the postgres:// URI that hosts such as Render provide.
    public static string Resolve(string? raw)
    {
        if (string.IsNullOrWhiteSpace(raw)) throw new InvalidOperationException("ConnectionStrings:Default is required.");
        if (!raw.StartsWith("postgres://", StringComparison.OrdinalIgnoreCase) && !raw.StartsWith("postgresql://", StringComparison.OrdinalIgnoreCase)) return raw;
        var u = new Uri(raw);
        var ui = u.UserInfo.Split(':', 2);
        var b = new NpgsqlConnectionStringBuilder
        {
            Host = u.Host, Port = u.Port > 0 ? u.Port : 5432, Database = Uri.UnescapeDataString(u.AbsolutePath.TrimStart('/')),
            Username = Uri.UnescapeDataString(ui[0]), Password = ui.Length > 1 ? Uri.UnescapeDataString(ui[1]) : null,
            SslMode = u.Query.Contains("sslmode=require", StringComparison.OrdinalIgnoreCase) ? SslMode.Require : SslMode.Prefer
        };
        return b.ConnectionString;
    }
}
