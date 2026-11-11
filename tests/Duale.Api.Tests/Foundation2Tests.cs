using System.Net;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text;
using System.Text.Json;
using Duale.Api.Services;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
namespace Duale.Api.Tests;

public class Foundation2Tests(ApiFactory f) : IClassFixture<ApiFactory>
{
    const string Password = "correct-horse-battery";
    static readonly byte[] Pdf = Encoding.ASCII.GetBytes("%PDF-1.4\n1 0 obj<<>>endobj\n%%EOF");
    static Guid Id(JsonElement e) => e.GetProperty("id").GetGuid();
    static async Task<JsonElement> Json(HttpResponseMessage r) { r.EnsureSuccessStatusCode(); return await r.Content.ReadFromJsonAsync<JsonElement>(); }

    static MultipartFormDataContent Upload(byte[] bytes, string name = "id.pdf", string kind = "identity")
    {
        var c = new MultipartFormDataContent { { new StringContent(kind), "kind" } };
        var file = new ByteArrayContent(bytes); file.Headers.ContentType = new MediaTypeHeaderValue("application/pdf");
        c.Add(file, "file", name);
        return c;
    }

    async Task<(HttpClient Client, string Email, Guid TechId)> TechAsync()
    {
        var (c, email) = await f.UserAsync();
        return (c, email, Id(await Json(await c.PostAsJsonAsync("/technicians/me", new { displayName = "Tech" }))));
    }

    // ---------- TOTP ----------
    [Fact]
    public void Totp_matches_the_RFC6238_test_vector()
    {
        var key = Encoding.ASCII.GetBytes("12345678901234567890");
        Assert.Equal("287082", Totp.Code(key, 1));                    // T=59s, last 6 digits of 94287082
        Assert.Equal(key, Totp.FromBase32(Totp.Base32(key)));
        Assert.Null(Totp.Verify(key, "287082", DateTimeOffset.FromUnixTimeSeconds(59), lastStep: 1));   // replay of an accepted step
        Assert.Equal(1L, Totp.Verify(key, "287082", DateTimeOffset.FromUnixTimeSeconds(59), lastStep: 0));
    }

    [Fact]
    public void Signed_links_expire_and_cannot_be_tampered_with()
    {
        var links = new SignedLinks(new ConfigurationBuilder().AddInMemoryCollection(new Dictionary<string, string?> { ["Jwt:Key"] = "k".PadRight(40, 'k'), ["Files:LinkSeconds"] = "60" }).Build());
        var doc = Guid.NewGuid(); var user = Guid.NewGuid(); var now = DateTimeOffset.UtcNow;
        var t = links.Create(doc, user, now);
        var v = links.Validate(t, now.AddSeconds(30));
        Assert.Equal(doc, v!.Value.DocId); Assert.Equal(user, v.Value.UserId);
        Assert.Null(links.Validate(t, now.AddSeconds(61)));
        Assert.Null(links.Validate(t[..^2] + "xx", now));
    }

    // ---------- Branches ----------
    [Fact]
    public async Task Branches_are_tenant_scoped_and_need_branch_manage()
    {
        var (a, _) = await f.UserAsync(); var (b, _) = await f.UserAsync();
        var ca = await f.CreateCompanyAsync(a); var cb = await f.CreateCompanyAsync(b);
        await f.ApproveAsync(ca); await f.ApproveAsync(cb);
        var branch = Id(await Json(await a.PostAsJsonAsync($"/companies/{ca}/branches", new { name = "Garowe HQ", address = "Main St" })));
        Assert.Equal(HttpStatusCode.Conflict, (await a.PostAsJsonAsync($"/companies/{ca}/branches", new { name = "Garowe HQ" })).StatusCode);

        Assert.Equal(HttpStatusCode.NotFound, (await b.GetAsync($"/companies/{ca}/branches")).StatusCode);                     // not a member
        Assert.Equal(HttpStatusCode.NotFound, (await b.PutAsJsonAsync($"/companies/{cb}/branches/{branch}", new { name = "x" })).StatusCode); // foreign branch id

        var (disp, dispEmail) = await f.UserAsync();
        (await a.PostAsJsonAsync($"/companies/{ca}/members", new { email = dispEmail, roleCode = "dispatcher" })).EnsureSuccessStatusCode();
        Assert.Equal(HttpStatusCode.OK, (await disp.GetAsync($"/companies/{ca}/branches")).StatusCode);
        Assert.Equal(HttpStatusCode.Forbidden, (await disp.PostAsJsonAsync($"/companies/{ca}/branches", new { name = "Second" })).StatusCode);
    }

    [Fact]
    public async Task Branch_members_must_belong_to_the_same_company()
    {
        var (a, _) = await f.UserAsync(); var (b, _) = await f.UserAsync();
        var ca = await f.CreateCompanyAsync(a); var cb = await f.CreateCompanyAsync(b);
        await f.ApproveAsync(ca); await f.ApproveAsync(cb);
        var branch = Id(await Json(await a.PostAsJsonAsync($"/companies/{ca}/branches", new { name = "HQ" })));
        var foreign = (await (await b.GetAsync($"/companies/{cb}/members")).Content.ReadFromJsonAsync<JsonElement>()).EnumerateArray().First().GetProperty("id").GetGuid();
        var own = (await (await a.GetAsync($"/companies/{ca}/members")).Content.ReadFromJsonAsync<JsonElement>()).EnumerateArray().First().GetProperty("id").GetGuid();
        Assert.Equal(HttpStatusCode.BadRequest, (await a.PutAsJsonAsync($"/companies/{ca}/branches/{branch}/members", new { membershipIds = new[] { foreign } })).StatusCode);
        Assert.Equal(HttpStatusCode.NoContent, (await a.PutAsJsonAsync($"/companies/{ca}/branches/{branch}/members", new { membershipIds = new[] { own } })).StatusCode);
    }

    // ---------- Technician documents ----------
    [Fact]
    public async Task Upload_accepts_real_pdf_and_rejects_disguised_files()
    {
        var (t, _, _) = await TechAsync();
        Assert.Equal(HttpStatusCode.Created, (await t.PostAsync("/technicians/me/documents", Upload(Pdf))).StatusCode);
        Assert.Equal(HttpStatusCode.BadRequest, (await t.PostAsync("/technicians/me/documents", Upload(Encoding.ASCII.GetBytes("<script>alert(1)</script>"), "evil.pdf"))).StatusCode);
        Assert.Equal(HttpStatusCode.BadRequest, (await t.PostAsync("/technicians/me/documents", Upload(Pdf, kind: "selfie"))).StatusCode);
    }

    [Fact]
    public async Task Documents_are_private_to_owner_and_platform_reviewers()
    {
        var (owner, _, _) = await TechAsync(); var (other, _, _) = await TechAsync();
        var doc = Id(await Json(await owner.PostAsync("/technicians/me/documents", Upload(Pdf))));

        Assert.Equal(HttpStatusCode.NotFound, (await other.PostAsync($"/technicians/me/documents/{doc}/link", null)).StatusCode);   // IDOR
        Assert.Equal(HttpStatusCode.Forbidden, (await other.GetAsync("/platform/technician-documents")).StatusCode);

        var link = (await Json(await owner.PostAsync($"/technicians/me/documents/{doc}/link", null))).GetProperty("url").GetString()!;
        var file = await owner.GetAsync(link);
        Assert.Equal(HttpStatusCode.OK, file.StatusCode);
        Assert.Equal(Pdf, await file.Content.ReadAsByteArrayAsync());
        Assert.Equal(HttpStatusCode.NotFound, (await other.GetAsync(link)).StatusCode);   // a leaked link is useless to someone else

        var (reviewer, _) = await f.UserAsync("verification_officer");
        var queue = await Json(await reviewer.GetAsync("/platform/technician-documents?status=Pending"));
        Assert.Contains(queue.EnumerateArray(), d => Id(d) == doc);
        Assert.Equal(HttpStatusCode.NoContent, (await reviewer.PostAsJsonAsync($"/platform/technician-documents/{doc}/decision", new { decision = "approve" })).StatusCode);
        Assert.Equal(HttpStatusCode.Conflict, (await reviewer.PostAsJsonAsync($"/platform/technician-documents/{doc}/decision", new { decision = "reject" })).StatusCode);
    }

    [Fact]
    public async Task Reviewers_cannot_review_their_own_documents()
    {
        var (c, email) = await f.UserAsync("verification_officer");
        (await c.PostAsJsonAsync("/technicians/me", new { displayName = "Self" })).EnsureSuccessStatusCode();
        var doc = Id(await Json(await c.PostAsync("/technicians/me/documents", Upload(Pdf))));
        Assert.Equal(HttpStatusCode.Forbidden, (await c.PostAsJsonAsync($"/platform/technician-documents/{doc}/decision", new { decision = "approve" })).StatusCode);
    }

    // ---------- Service areas ----------
    [Fact]
    public async Task Service_areas_are_platform_managed_and_technicians_choose_from_them()
    {
        var (admin, _) = await f.UserAsync("platform_admin");
        var (t, _, _) = await TechAsync();
        Assert.Equal(HttpStatusCode.Forbidden, (await t.PostAsJsonAsync("/platform/service-areas", new { name = "Nowhere" })).StatusCode);
        var area = Id(await Json(await admin.PostAsJsonAsync("/platform/service-areas", new { name = "Garowe " + Guid.NewGuid().ToString("N")[..4] })));
        Assert.Equal(HttpStatusCode.BadRequest, (await t.PutAsJsonAsync("/technicians/me/service-areas", new { serviceAreaIds = new[] { Guid.NewGuid() } })).StatusCode);
        Assert.Equal(HttpStatusCode.NoContent, (await t.PutAsJsonAsync("/technicians/me/service-areas", new { serviceAreaIds = new[] { area } })).StatusCode);
        Assert.Single((await Json(await t.GetAsync("/technicians/me/service-areas"))).EnumerateArray());
    }

    // ---------- MFA ----------
    async Task<(HttpClient Client, string Email, string Secret, string[] Recovery)> MfaUserAsync()
    {
        var (c, email) = await f.UserAsync();
        var secret = (await Json(await c.PostAsync("/auth/mfa/setup", null))).GetProperty("secret").GetString()!;
        var code = Totp.Code(Totp.FromBase32(secret), Totp.Step(DateTimeOffset.UtcNow));
        var res = await Json(await c.PostAsJsonAsync("/auth/mfa/enable", new { code }));
        return (c, email, secret, res.GetProperty("recoveryCodes").EnumerateArray().Select(x => x.GetString()!).ToArray());
    }
    static string NextCode(string secret) => Totp.Code(Totp.FromBase32(secret), Totp.Step(DateTimeOffset.UtcNow) + 1);

    [Fact]
    public async Task Login_with_MFA_needs_the_second_factor_and_codes_cannot_be_replayed()
    {
        var (_, email, secret, _) = await MfaUserAsync();
        var anon = f.CreateClient();
        var login = await Json(await anon.PostAsJsonAsync("/auth/login", new { email, password = Password }));
        Assert.True(login.GetProperty("mfaRequired").GetBoolean());
        Assert.False(login.TryGetProperty("token", out _));
        var mfaToken = login.GetProperty("mfaToken").GetString();

        // the intermediate token must not work as an access token
        anon.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue("Bearer", mfaToken);
        Assert.Equal(HttpStatusCode.Unauthorized, (await anon.GetAsync("/technicians/me")).StatusCode);

        var code = NextCode(secret);
        var ok = await f.CreateClient().PostAsJsonAsync("/auth/mfa/verify", new { mfaToken, code });
        Assert.Equal(HttpStatusCode.OK, ok.StatusCode);
        Assert.Equal(HttpStatusCode.Unauthorized, (await f.CreateClient().PostAsJsonAsync("/auth/mfa/verify", new { mfaToken, code })).StatusCode);   // replay
    }

    [Fact]
    public async Task Recovery_codes_work_once_and_repeated_failures_lock_the_factor()
    {
        var (_, email, secret, recovery) = await MfaUserAsync();
        var anon = f.CreateClient();
        async Task<string> Token() => (await Json(await anon.PostAsJsonAsync("/auth/login", new { email, password = Password }))).GetProperty("mfaToken").GetString()!;

        Assert.Equal(HttpStatusCode.OK, (await anon.PostAsJsonAsync("/auth/mfa/verify", new { mfaToken = await Token(), code = recovery[0] })).StatusCode);
        Assert.Equal(HttpStatusCode.Unauthorized, (await anon.PostAsJsonAsync("/auth/mfa/verify", new { mfaToken = await Token(), code = recovery[0] })).StatusCode);

        for (var i = 0; i < 5; i++) await anon.PostAsJsonAsync("/auth/mfa/verify", new { mfaToken = await Token(), code = "000000" });
        Assert.Equal(HttpStatusCode.Unauthorized, (await anon.PostAsJsonAsync("/auth/mfa/verify", new { mfaToken = await Token(), code = recovery[1] })).StatusCode);   // locked even with a valid code
    }

    [Fact]
    public async Task Support_can_reset_MFA_but_not_for_themselves()
    {
        var (_, email, _, _) = await MfaUserAsync();
        var (admin, adminEmail) = await f.UserAsync("platform_admin");
        Guid UserId(string e) { using var s = f.Services.CreateScope(); return s.ServiceProvider.GetRequiredService<Duale.Api.Data.AppDbContext>().Users.Single(u => u.Email == e).Id; }
        Assert.Equal(HttpStatusCode.Forbidden, (await admin.PostAsync($"/platform/users/{UserId(adminEmail)}/mfa-reset", null)).StatusCode);
        Assert.Equal(HttpStatusCode.NoContent, (await admin.PostAsync($"/platform/users/{UserId(email)}/mfa-reset", null)).StatusCode);
        var login = await Json(await f.CreateClient().PostAsJsonAsync("/auth/login", new { email, password = Password }));
        Assert.True(login.TryGetProperty("token", out _));
        var (plain, _) = await f.UserAsync();
        Assert.Equal(HttpStatusCode.Forbidden, (await plain.PostAsync($"/platform/users/{UserId(email)}/mfa-reset", null)).StatusCode);
    }

    // ---------- Account recovery ----------
    [Fact]
    public async Task Recovery_resets_the_password_once_and_ends_old_sessions()
    {
        var (old, email) = await f.UserAsync();
        var anon = f.CreateClient();
        Assert.Equal(HttpStatusCode.NoContent, (await anon.PostAsJsonAsync("/auth/recovery/request", new { email = "nobody@example.com" })).StatusCode);   // no account enumeration
        Assert.False(f.Delivery.Tokens.ContainsKey("nobody@example.com"));

        Assert.Equal(HttpStatusCode.NoContent, (await anon.PostAsJsonAsync("/auth/recovery/request", new { email })).StatusCode);
        var token = f.Delivery.Tokens[email];
        Assert.Equal(HttpStatusCode.BadRequest, (await anon.PostAsJsonAsync("/auth/recovery/reset", new { token, newPassword = "short" })).StatusCode);
        Assert.Equal(HttpStatusCode.NoContent, (await anon.PostAsJsonAsync("/auth/recovery/reset", new { token, newPassword = "a-brand-new-passphrase" })).StatusCode);
        Assert.Equal(HttpStatusCode.BadRequest, (await anon.PostAsJsonAsync("/auth/recovery/reset", new { token, newPassword = "another-new-passphrase" })).StatusCode);   // single use

        Assert.Equal(HttpStatusCode.Unauthorized, (await anon.PostAsJsonAsync("/auth/login", new { email, password = Password })).StatusCode);
        Assert.Equal(HttpStatusCode.OK, (await anon.PostAsJsonAsync("/auth/login", new { email, password = "a-brand-new-passphrase" })).StatusCode);
        Assert.Equal(HttpStatusCode.Unauthorized, (await old.GetAsync("/notifications")).StatusCode);   // old session revoked
    }

    [Fact]
    public async Task Recovery_does_not_bypass_MFA()
    {
        var (_, email, secret, _) = await MfaUserAsync();
        var anon = f.CreateClient();
        await anon.PostAsJsonAsync("/auth/recovery/request", new { email });
        var token = f.Delivery.Tokens[email];
        Assert.Equal(HttpStatusCode.Unauthorized, (await anon.PostAsJsonAsync("/auth/recovery/reset", new { token, newPassword = "a-brand-new-passphrase" })).StatusCode);
        Assert.Equal(HttpStatusCode.NoContent, (await anon.PostAsJsonAsync("/auth/recovery/reset", new { token, newPassword = "a-brand-new-passphrase", code = NextCode(secret) })).StatusCode);
    }

    [Fact]
    public async Task Me_lists_own_companies_and_platform_abilities_only()
    {
        var (a, _) = await f.UserAsync(); var (b, _) = await f.UserAsync("verification_officer");
        var ca = await f.CreateCompanyAsync(a);
        var meA = await Json(await a.GetAsync("/me"));
        Assert.Equal(ca, Id(meA.GetProperty("companies")[0]));
        Assert.False(meA.GetProperty("platform").GetProperty("companyVerify").GetBoolean());
        var meB = await Json(await b.GetAsync("/me"));
        Assert.Empty(meB.GetProperty("companies").EnumerateArray());
        Assert.True(meB.GetProperty("platform").GetProperty("companyVerify").GetBoolean());
    }
}
