using Duale.Api.Data;
namespace Duale.Api.Tests;

public class RenderTests
{
    [Fact]
    public void Postgres_uri_is_converted_to_an_npgsql_connection_string()
    {
        var cs = DbConn.Resolve("postgresql://duale_user:p%40ss%2Fword@dpg-abc123-a:5432/duale_db");
        Assert.Contains("Host=dpg-abc123-a", cs);
        Assert.Contains("Database=duale_db", cs);
        Assert.Contains("Username=duale_user", cs);
        Assert.Contains("Password=p@ss/word", cs);
    }

    [Fact]
    public void Uri_without_a_port_uses_5432_and_normal_strings_pass_through()
    {
        Assert.Contains("Port=5432", DbConn.Resolve("postgres://u:p@host/db"));
        const string plain = "Host=localhost;Database=x;Username=y;Password=z";
        Assert.Equal(plain, DbConn.Resolve(plain));
        Assert.Throws<InvalidOperationException>(() => DbConn.Resolve(" "));
    }
}
