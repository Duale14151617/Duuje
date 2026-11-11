using System.Threading.RateLimiting;
using Duale.Api;
using Duale.Api.Auth;
using Duale.Api.Data;
using Duale.Api.Domain;
using Microsoft.AspNetCore.Authentication.JwtBearer;
using Microsoft.AspNetCore.Identity;
using Microsoft.EntityFrameworkCore;
using Microsoft.IdentityModel.Tokens;

if (args.Contains("--healthcheck"))
{
    using var http = new HttpClient { Timeout = TimeSpan.FromSeconds(4) };
    try { Environment.Exit((await http.GetAsync("http://localhost:8080/health/ready")).IsSuccessStatusCode ? 0 : 1); } catch { Environment.Exit(1); }
}
var builder = WebApplication.CreateBuilder(args);
var cfg = builder.Configuration;

var jwtKey = cfg["Jwt:Key"] ?? throw new InvalidOperationException("Jwt:Key is required (set via environment/secret store, never in source).");
if (System.Text.Encoding.UTF8.GetBytes(jwtKey).Length < 32) throw new InvalidOperationException("Jwt:Key must be at least 32 bytes.");

builder.Services.AddDbContext<AppDbContext>(o => o.UseNpgsql(DbConn.Resolve(cfg.GetConnectionString("Default"))));
builder.Services.AddScoped<AccessService>();
builder.Services.AddScoped<Duale.Api.Services.MatchingService>();
builder.Services.AddSingleton<IPasswordHasher<User>, PasswordHasher<User>>();
builder.Services.AddSingleton<TokenService>();
Duale.Api.Services.SecretBox.Validate(cfg);
builder.Services.AddSingleton<Duale.Api.Services.SecretBox>();
builder.Services.AddSingleton<Duale.Api.Services.MfaTokens>();
builder.Services.AddScoped<Duale.Api.Services.MfaService>();
builder.Services.AddSingleton<Duale.Api.Services.SignedLinks>();
builder.Services.AddSingleton<Duale.Api.Services.IFileStore, Duale.Api.Services.LocalFileStore>();
if (!string.IsNullOrEmpty(cfg["Scanner:ClamAv:Host"])) builder.Services.AddSingleton<Duale.Api.Services.IUploadScanner, Duale.Api.Services.ClamAvScanner>();
else if (builder.Environment.IsProduction() && cfg["Scanner:AllowNoop"] != "true")
    throw new InvalidOperationException("Production needs an upload scanner: set Scanner__ClamAv__Host (or Scanner__AllowNoop=true to accept the risk explicitly).");
else builder.Services.AddSingleton<Duale.Api.Services.IUploadScanner, Duale.Api.Services.NoopUploadScanner>();
builder.Services.AddScoped<Duale.Api.Services.RetentionService>();
builder.Services.AddScoped<Duale.Api.Services.IntegrityService>();
builder.WebHost.ConfigureKestrel(k => { k.AddServerHeader = false; k.Limits.MaxRequestBodySize = 12 * 1024 * 1024; });
if (cfg["Security:TrustProxy"] == "true")
    builder.Services.Configure<Microsoft.AspNetCore.Builder.ForwardedHeadersOptions>(o =>
    { o.ForwardedHeaders = Microsoft.AspNetCore.HttpOverrides.ForwardedHeaders.XForwardedFor | Microsoft.AspNetCore.HttpOverrides.ForwardedHeaders.XForwardedProto; o.KnownNetworks.Clear(); o.KnownProxies.Clear(); });
if (builder.Environment.IsDevelopment()) builder.Services.AddSingleton<Duale.Api.Services.IRecoveryDelivery, Duale.Api.Services.ConsoleRecoveryDelivery>();
else builder.Services.AddSingleton<Duale.Api.Services.IRecoveryDelivery, Duale.Api.Services.NotConfiguredRecoveryDelivery>();
if (!string.IsNullOrEmpty(cfg["Brevo:ApiKey"])) builder.Services.AddSingleton<Duale.Api.Services.INotificationProvider, Duale.Api.Services.BrevoEmailProvider>();
else if (!string.IsNullOrEmpty(cfg["Smtp:Host"])) builder.Services.AddSingleton<Duale.Api.Services.INotificationProvider, Duale.Api.Services.SmtpEmailProvider>();
builder.Services.AddScoped<Duale.Api.Services.IVerificationDelivery, Duale.Api.Services.VerificationDelivery>();
builder.Services.AddScoped<Duale.Api.Services.NotificationDispatcher>();
builder.Services.AddScoped<Duale.Api.Services.ReminderService>();
builder.Services.AddScoped<Duale.Api.Services.OutboxDispatcher>();   // no IOutboxPublisher is registered: consumers are not chosen yet
// No INotificationProvider is registered: email/SMS providers are not chosen yet. Register one per channel here once selected.
if (cfg["Worker:Enabled"] != "false") builder.Services.AddHostedService<Duale.Api.Services.MaintenanceWorker>();
builder.Services.AddProblemDetails();

builder.Services.AddAuthentication(JwtBearerDefaults.AuthenticationScheme).AddJwtBearer(o =>
{
    o.MapInboundClaims = false;
    o.TokenValidationParameters = new TokenValidationParameters
    {
        ValidIssuer = cfg["Jwt:Issuer"] ?? "duale-buildlink",
        ValidAudience = cfg["Jwt:Audience"] ?? "duale-buildlink",
        IssuerSigningKey = TokenService.Key(cfg),
        ClockSkew = TimeSpan.FromSeconds(30)
    };
    o.Events = new JwtBearerEvents
    {
        // Reject tokens for suspended users or after "logout everywhere" (TokenVersion bump).
        OnTokenValidated = async ctx =>
        {
            var db = ctx.HttpContext.RequestServices.GetRequiredService<AppDbContext>();
            var id = Guid.Parse(ctx.Principal!.FindFirst("sub")!.Value);
            var tv = int.Parse(ctx.Principal.FindFirst("tv")?.Value ?? "-1");
            var ok = await db.Users.AnyAsync(u => u.Id == id && u.Status == AccountStatus.Active && u.TokenVersion == tv);
            if (!ok) ctx.Fail("Session is no longer valid.");
        }
    };
});
builder.Services.AddAuthorization();

var apiPerMinute = int.TryParse(cfg["RateLimit:ApiPerMinute"], out var apm) ? apm : 600;
var authPerMinute = int.TryParse(cfg["RateLimit:AuthPerMinute"], out var n) ? n : 10;
builder.Services.AddRateLimiter(o =>
{
    o.RejectionStatusCode = 429;
    // Every request is limited per signed-in user (or per client address when anonymous), on top of the stricter "auth" policy.
    o.GlobalLimiter = PartitionedRateLimiter.Create<HttpContext, string>(ctx =>
        RateLimitPartition.GetFixedWindowLimiter(ctx.User.FindFirst("sub")?.Value ?? ("ip:" + (ctx.Connection.RemoteIpAddress?.ToString() ?? "unknown")),
            _ => new FixedWindowRateLimiterOptions { PermitLimit = apiPerMinute, Window = TimeSpan.FromMinutes(1) }));
    o.AddPolicy("auth", ctx => RateLimitPartition.GetFixedWindowLimiter(
        ctx.Connection.RemoteIpAddress?.ToString() ?? "unknown",
        _ => new FixedWindowRateLimiterOptions { PermitLimit = authPerMinute, Window = TimeSpan.FromMinutes(1) }));
});

var app = builder.Build();
if (cfg["Security:TrustProxy"] == "true") app.UseForwardedHeaders();
Duale.Api.Services.Hardening.Use(app);
if (cfg["Web:ServeSpa"] == "true")
{
    // Single-service hosting: the React build in wwwroot is served from the same origin (no CORS). The API is reached under /api.
    app.Use(async (ctx, next) =>
    {
        var path = ctx.Request.Path;
        var browserGet = (HttpMethods.IsGet(ctx.Request.Method) || HttpMethods.IsHead(ctx.Request.Method))
            && !path.StartsWithSegments("/api") && !path.StartsWithSegments("/health") && !path.StartsWithSegments("/metrics") && !System.IO.Path.HasExtension(path.Value);
        if (browserGet) ctx.Request.Path = "/index.html";   // client-side routes (/companies, /login, ...) all load the app shell
        await next();
    });
    app.UsePathBase("/api");
    app.UseStaticFiles();
    app.UseRouting();   // explicit, so routing sees the path after UsePathBase has stripped /api
}
app.UseExceptionHandler();
if (app.Environment.IsProduction() && cfg["Security:RequireHttps"] != "false") { app.UseHsts(); }
app.UseAuthentication();
app.UseRateLimiter();   // after authentication so the limit is per user
app.UseAuthorization();
app.MapGet("/health", () => Results.Ok(new { status = "ok" }));
Duale.Api.Services.Hardening.MapOps(app);
Endpoints.Map(app);

// Optional first-run setup: migrate and create the first platform admin from environment variables.
using (var scope = app.Services.CreateScope())
{
    var db = scope.ServiceProvider.GetRequiredService<AppDbContext>();
    if (cfg["Database:AutoMigrate"] == "true")
    {
        await db.Database.MigrateAsync();
        if (db.Database.IsNpgsql()) await Duale.Api.Data.SchemaPatches.ApplyAsync(db);   // adds tables/columns newer than the committed migrations
    }
    if (cfg["Database:AutoMigrate"] == "true") await Duale.Api.Data.DemoReset.RunIfRequestedAsync(db, cfg, app.Logger);
    var email = cfg["Bootstrap:AdminEmail"]?.Trim().ToLowerInvariant();
    var pw = cfg["Bootstrap:AdminPassword"];
    if (!string.IsNullOrEmpty(email) && !string.IsNullOrEmpty(pw) && !await db.Users.AnyAsync(u => u.Email == email))
    {
        var hasher = scope.ServiceProvider.GetRequiredService<IPasswordHasher<User>>();
        var admin = new User { Email = email, DisplayName = "Platform Administrator" };
        admin.PasswordHash = hasher.HashPassword(admin, pw);
        db.Users.Add(admin);
        db.PlatformRoleAssignments.Add(new PlatformRoleAssignment { UserId = admin.Id, RoleCode = "platform_admin" });
        await db.SaveChangesAsync();
    }
    // Superadmin: if that account already exists, make sure it holds the platform roles (new sign-ups get them in /auth/register).
    var superEmail = cfg["Bootstrap:SuperAdminEmail"]?.Trim().ToLowerInvariant();
    if (!string.IsNullOrEmpty(superEmail))
    {
        var su = await db.Users.FirstOrDefaultAsync(u => u.Email == superEmail);
        if (su is not null)
        {
            foreach (var role in new[] { "platform_admin", "platform_finance" })
                if (!await db.PlatformRoleAssignments.AnyAsync(a => a.UserId == su.Id && a.RoleCode == role))
                    db.PlatformRoleAssignments.Add(new PlatformRoleAssignment { UserId = su.Id, RoleCode = role });
            await db.SaveChangesAsync();
        }
    }
    // First run only: start the catalogue with starter skills for each trade (skipped once any skill exists).
    if (cfg["Database:AutoMigrate"] == "true" && !await db.Skills.AnyAsync())
    {
        db.Skills.AddRange(Duale.Api.Data.Seed.StarterSkills());
        await db.SaveChangesAsync();
    }
    // First run only: start the catalogue with Puntland service areas. Add or hide more later in Platform admin > Catalog.
    if (cfg["Database:AutoMigrate"] == "true" && !await db.ServiceAreas.AnyAsync())
    {
        foreach (var name in new[] { "Garowe", "Bosaso", "Galkayo", "Qardho" })
            db.ServiceAreas.Add(new ServiceArea { Name = name });
        await db.SaveChangesAsync();
    }
}
app.Run();

public partial class Program { }
