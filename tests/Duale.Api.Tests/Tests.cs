using System.Net;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using Duale.Api.Data;
using Duale.Api.Domain;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.Data.Sqlite;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;

namespace Duale.Api.Tests;

public class CapturingDelivery : Duale.Api.Services.IRecoveryDelivery
{
    public System.Collections.Concurrent.ConcurrentDictionary<string, string> Tokens { get; } = new();
    public Task SendAsync(string email, string token, DateTime expiresAt, CancellationToken ct) { Tokens[email] = token; return Task.CompletedTask; }
}

public class CapturingVerification : Duale.Api.Services.IVerificationDelivery
{
    public System.Collections.Concurrent.ConcurrentDictionary<string, string> Codes { get; } = new();   // key: "email:<address>" or "sms:<number>"
    public bool CanSend(string channel) => true;
    public Task SendAsync(string channel, string target, string code, DateTime expiresAt, CancellationToken ct) { Codes[$"{channel}:{target}"] = code; return Task.CompletedTask; }
}

public class ApiFactory : WebApplicationFactory<Program>
{
    const string Password = "correct-horse-battery";
    public const string CallbackSecret = "test-callback-secret-0123456789abcdef";
    readonly SqliteConnection _conn = new("DataSource=:memory:");
    int _n;
    public CapturingDelivery Delivery { get; } = new();
    public CapturingVerification Verification { get; } = new();

    public ApiFactory()
    {
        _conn.Open();
        Environment.SetEnvironmentVariable("Jwt__Key", "test-signing-key-test-signing-key-0123456789");
        Environment.SetEnvironmentVariable("RateLimit__AuthPerMinute", "100000");
        Environment.SetEnvironmentVariable("Mfa__Key", Convert.ToBase64String(new byte[32].Select((_, i) => (byte)(i + 1)).ToArray()));
        Environment.SetEnvironmentVariable("Worker__Enabled", "false");
        Environment.SetEnvironmentVariable("Finance__CallbackSecret", CallbackSecret);
        Environment.SetEnvironmentVariable("Files__Root", Path.Combine(Path.GetTempPath(), "duale-test-files-" + Guid.NewGuid().ToString("N")));
    }

    protected override void ConfigureWebHost(IWebHostBuilder b)
    {
    // Invitations require a verified phone in production. Most tests invite freshly made technicians, so they run with the rule off;
    // Phase8Tests turns it on for the test that checks it.
    b.UseSetting("Verification:RequirePhoneForInvites", "false");
    b.ConfigureServices(s =>
    {
        s.Remove(s.Single(d => d.ServiceType == typeof(DbContextOptions<AppDbContext>)));
        s.AddDbContext<AppDbContext>(o => o.UseSqlite(_conn));
        s.Remove(s.Single(d => d.ServiceType == typeof(Duale.Api.Services.IRecoveryDelivery)));
        s.AddSingleton(Delivery);
        s.AddSingleton<Duale.Api.Services.IRecoveryDelivery>(Delivery);
        s.Remove(s.Single(d => d.ServiceType == typeof(Duale.Api.Services.IVerificationDelivery)));
        s.AddSingleton<Duale.Api.Services.IVerificationDelivery>(Verification);
    });
    }

    public async Task<(HttpClient Client, string Email)> UserAsync(string? platformRole = null)
    {
        var email = $"user{Interlocked.Increment(ref _n)}@example.com";
        var c = CreateClient();
        using (var s = Services.CreateScope()) s.ServiceProvider.GetRequiredService<AppDbContext>().Database.EnsureCreated();
        (await c.PostAsJsonAsync("/auth/register", new { email, password = Password, displayName = "Test User" })).EnsureSuccessStatusCode();
        if (platformRole != null)
        {
            using var s = Services.CreateScope();
            var db = s.ServiceProvider.GetRequiredService<AppDbContext>();
            var u = await db.Users.FirstAsync(x => x.Email == email);
            db.PlatformRoleAssignments.Add(new PlatformRoleAssignment { UserId = u.Id, RoleCode = platformRole });
            await db.SaveChangesAsync();
        }
        var r = await c.PostAsJsonAsync("/auth/login", new { email, password = Password });
        r.EnsureSuccessStatusCode();
        var tok = (await r.Content.ReadFromJsonAsync<TokenRes>())!.Token;
        c.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue("Bearer", tok);
        return (c, email);
    }

    public async Task<Guid> CreateCompanyAsync(HttpClient owner)
    {
        var r = await owner.PostAsJsonAsync("/companies", new { displayName = "Acme Plumbing", businessCategory = "Plumbing supplier", contactEmail = "ops@acme.example" });
        r.EnsureSuccessStatusCode();
        return (await r.Content.ReadFromJsonAsync<IdRes>())!.Id;
    }

    public async Task ApproveAsync(Guid companyId)
    {
        var (admin, _) = await UserAsync("platform_admin");
        (await admin.PostAsJsonAsync($"/platform/companies/{companyId}/decision", new { decision = "approve" })).EnsureSuccessStatusCode();
    }

    public record TokenRes(string Token, int ExpiresInSeconds);
    public record IdRes(Guid Id);
    protected override void Dispose(bool disposing) { base.Dispose(disposing); _conn.Dispose(); }
}

public class SecurityTests(ApiFactory f) : IClassFixture<ApiFactory>
{
    [Fact]
    public async Task Unauthenticated_requests_are_rejected()
    {
        var r = await f.CreateClient().GetAsync($"/companies/{Guid.NewGuid()}");
        Assert.Equal(HttpStatusCode.Unauthorized, r.StatusCode);
    }

    [Fact]
    public async Task Other_tenant_cannot_read_company_or_staff_even_with_a_valid_id()
    {
        var (a, _) = await f.UserAsync();
        var (b, _) = await f.UserAsync();
        var companyA = await f.CreateCompanyAsync(a);
        await f.CreateCompanyAsync(b); // B owns a different company

        Assert.Equal(HttpStatusCode.NotFound, (await b.GetAsync($"/companies/{companyA}")).StatusCode);
        Assert.Equal(HttpStatusCode.NotFound, (await b.GetAsync($"/companies/{companyA}/members")).StatusCode);
        Assert.Equal(HttpStatusCode.NotFound, (await b.GetAsync($"/companies/{companyA}/audit")).StatusCode);
        Assert.Equal(HttpStatusCode.OK, (await a.GetAsync($"/companies/{companyA}")).StatusCode);
    }

    [Fact]
    public async Task Member_without_staff_permission_is_forbidden_to_manage_staff()
    {
        var (owner, _) = await f.UserAsync();
        var (dispatcher, dispatcherEmail) = await f.UserAsync();
        var (_, thirdEmail) = await f.UserAsync();
        var company = await f.CreateCompanyAsync(owner);
        await f.ApproveAsync(company);

        (await owner.PostAsJsonAsync($"/companies/{company}/members", new { email = dispatcherEmail, roleCode = "dispatcher" })).EnsureSuccessStatusCode();
        var r = await dispatcher.PostAsJsonAsync($"/companies/{company}/members", new { email = thirdEmail, roleCode = "company_owner" });
        Assert.Equal(HttpStatusCode.Forbidden, r.StatusCode);
    }

    [Fact]
    public async Task Company_staff_endpoint_cannot_grant_platform_roles()
    {
        var (owner, ownerEmail) = await f.UserAsync();
        var company = await f.CreateCompanyAsync(owner);
        await f.ApproveAsync(company);
        var r = await owner.PostAsJsonAsync($"/companies/{company}/members", new { email = ownerEmail, roleCode = "platform_admin" });
        Assert.Equal(HttpStatusCode.BadRequest, r.StatusCode);
    }

    [Fact]
    public async Task Staff_cannot_be_added_before_company_is_approved()
    {
        var (owner, _) = await f.UserAsync();
        var (_, otherEmail) = await f.UserAsync();
        var company = await f.CreateCompanyAsync(owner);
        var r = await owner.PostAsJsonAsync($"/companies/{company}/members", new { email = otherEmail, roleCode = "dispatcher" });
        Assert.Equal(HttpStatusCode.Conflict, r.StatusCode);
    }

    [Fact]
    public async Task Platform_endpoints_require_platform_permission()
    {
        var (user, _) = await f.UserAsync();
        Assert.Equal(HttpStatusCode.Forbidden, (await user.GetAsync("/platform/companies")).StatusCode);
        Assert.Equal(HttpStatusCode.Forbidden, (await user.PostAsJsonAsync("/platform/trades", new { name = "Roofing" })).StatusCode);
    }

    [Fact]
    public async Task Reviewer_cannot_approve_a_company_they_belong_to()
    {
        var (admin, _) = await f.UserAsync("platform_admin");
        var company = await f.CreateCompanyAsync(admin);
        var r = await admin.PostAsJsonAsync($"/platform/companies/{company}/decision", new { decision = "approve" });
        Assert.Equal(HttpStatusCode.Forbidden, r.StatusCode);
    }

    [Fact]
    public async Task Logout_all_revokes_existing_tokens()
    {
        var (c, _) = await f.UserAsync();
        Assert.Equal(HttpStatusCode.NotFound, (await c.GetAsync("/technicians/me")).StatusCode); // authenticated, no profile yet
        Assert.Equal(HttpStatusCode.NoContent, (await c.PostAsync("/auth/logout-all", null)).StatusCode);
        Assert.Equal(HttpStatusCode.Unauthorized, (await c.GetAsync("/technicians/me")).StatusCode);
    }
}

public class DomainTests
{
    [Fact]
    public void Skill_is_eligible_only_when_approved_and_unexpired()
    {
        var today = new DateOnly(2026, 11, 8);
        Assert.False(new TechnicianSkill().IsEligible(today)); // Pending
        Assert.True(new TechnicianSkill { Verification = VerificationStatus.Approved }.IsEligible(today));
        Assert.True(new TechnicianSkill { Verification = VerificationStatus.Approved, ExpiresOn = today }.IsEligible(today));
        Assert.False(new TechnicianSkill { Verification = VerificationStatus.Approved, ExpiresOn = today.AddDays(-1) }.IsEligible(today));
    }

    [Fact]
    public void Company_can_only_be_decided_from_pending_and_resubmitted_from_needs_info()
    {
        var c = new Company();
        Assert.True(c.TryDecide("request_info", "need licence", out _));
        Assert.False(c.TryDecide("approve", null, out _));   // NeedsInfo is not decidable until resubmitted
        Assert.True(c.TryResubmit());
        Assert.True(c.TryDecide("approve", null, out _));
        Assert.False(c.TryResubmit());
    }
}
