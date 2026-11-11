using System.Net;
using System.Net.Http.Json;
namespace Duale.Api.Tests;

public class Phase8Tests(ApiFactory f) : IClassFixture<ApiFactory>
{
    readonly Kit k = new(f);

    [Fact]
    public async Task Email_verification_accepts_the_right_code_only()
    {
        var (c, email) = await f.UserAsync();
        Assert.False((await Kit.Json(await c.GetAsync("/me"))).GetProperty("emailVerified").GetBoolean());
        Assert.Equal(HttpStatusCode.NoContent, (await c.PostAsync("/me/verify/email/request", null)).StatusCode);
        var code = f.Verification.Codes[$"email:{email}"];
        var wrong = code == "000000" ? "000001" : "000000";
        Assert.Equal(HttpStatusCode.BadRequest, (await c.PostAsJsonAsync("/me/verify/email/confirm", new { code = wrong })).StatusCode);
        Assert.Equal(HttpStatusCode.NoContent, (await c.PostAsJsonAsync("/me/verify/email/confirm", new { code })).StatusCode);
        Assert.True((await Kit.Json(await c.GetAsync("/me"))).GetProperty("emailVerified").GetBoolean());
        Assert.Equal(HttpStatusCode.Conflict, (await c.PostAsync("/me/verify/email/request", null)).StatusCode);   // already verified
    }

    [Fact]
    public async Task Phone_verification_is_cleared_when_the_number_changes()
    {
        var co = await k.NewCompanyAsync();
        var tech = await k.NewTechnicianAsync(co);
        Assert.Equal(HttpStatusCode.BadRequest, (await tech.Client.PostAsync("/me/verify/phone/request", null)).StatusCode);   // no phone yet

        var phone = "+2529" + Random.Shared.Next(10000000, 99999999);
        (await tech.Client.PutAsJsonAsync("/technicians/me", new { displayName = "Tech", phone })).EnsureSuccessStatusCode();
        Assert.Equal(HttpStatusCode.NoContent, (await tech.Client.PostAsync("/me/verify/phone/request", null)).StatusCode);
        var code = f.Verification.Codes[$"sms:{phone}"];
        Assert.Equal(HttpStatusCode.NoContent, (await tech.Client.PostAsJsonAsync("/me/verify/phone/confirm", new { code })).StatusCode);
        Assert.True((await Kit.Json(await tech.Client.GetAsync("/technicians/me"))).GetProperty("phoneVerified").GetBoolean());

        (await tech.Client.PutAsJsonAsync("/technicians/me", new { displayName = "Tech", phone = phone + "1" })).EnsureSuccessStatusCode();
        Assert.False((await Kit.Json(await tech.Client.GetAsync("/technicians/me"))).GetProperty("phoneVerified").GetBoolean());
    }

    [Fact]
    public async Task A_completed_job_can_be_rated_once_and_the_technician_sees_it()
    {
        var fld = await k.CompletedJobAsync(); var co = fld.Co;
        var url = $"/companies/{co.Id}/jobs/{fld.JobId}/rating";
        Assert.Equal(HttpStatusCode.BadRequest, (await co.Supervisor.PostAsJsonAsync(url, new { stars = 6 })).StatusCode);
        Assert.Equal(HttpStatusCode.Forbidden, (await co.Dispatcher.PostAsJsonAsync(url, new { stars = 4 })).StatusCode);   // dispatchers cannot review, so they cannot rate
        Assert.Equal(HttpStatusCode.Created, (await co.Supervisor.PostAsJsonAsync(url, new { stars = 4, comment = "Neat work" })).StatusCode);
        Assert.Equal(HttpStatusCode.Conflict, (await co.Supervisor.PostAsJsonAsync(url, new { stars = 5 })).StatusCode);

        var mine = await Kit.Json(await fld.Tech.Client.GetAsync("/technicians/me/ratings"));
        Assert.Equal(1, mine.GetProperty("count").GetInt32());
        Assert.Equal(4.0, mine.GetProperty("average").GetDouble());
        Assert.True((await Kit.Json(await co.Supervisor.GetAsync(url))).GetProperty("rated").GetBoolean());
    }

    [Fact]
    public async Task A_job_that_is_not_approved_cannot_be_rated()
    {
        var fld = await k.SubmittedJobAsync();
        Assert.Equal(HttpStatusCode.Conflict, (await fld.Co.Supervisor.PostAsJsonAsync($"/companies/{fld.Co.Id}/jobs/{fld.JobId}/rating", new { stars = 5 })).StatusCode);
    }

    [Fact]
    public async Task Invites_can_require_a_verified_phone()
    {
        var co = await k.NewCompanyAsync();
        var (client, email) = await f.UserAsync();
        var tech = Kit.Id(await Kit.Json(await client.PostAsJsonAsync("/technicians/me", new { displayName = "Tech", phone = "+252900000123" })));
        (await client.PutAsJsonAsync("/technicians/me/skills", new { skillIds = new[] { co.SkillId } })).EnsureSuccessStatusCode();
        (await co.Admin.PostAsJsonAsync($"/platform/technicians/{tech}/skills/{co.SkillId}/decision", new { decision = "approve" })).EnsureSuccessStatusCode();

        using var strict = f.WithWebHostBuilder(b => b.UseSetting("Verification:RequirePhoneForInvites", "true"));
        var owner = strict.CreateClient();
        owner.DefaultRequestHeaders.Authorization = co.Owner.DefaultRequestHeaders.Authorization;
        Task<HttpResponseMessage> Invite() => owner.PostAsJsonAsync($"/companies/{co.Id}/relationships", new { technicianEmail = email, type = "Independent" });

        Assert.Equal(HttpStatusCode.Conflict, (await Invite()).StatusCode);
        (await client.PostAsync("/me/verify/phone/request", null)).EnsureSuccessStatusCode();
        var code = f.Verification.Codes["sms:+252900000123"];
        (await client.PostAsJsonAsync("/me/verify/phone/confirm", new { code })).EnsureSuccessStatusCode();
        (await Invite()).EnsureSuccessStatusCode();
    }
}
