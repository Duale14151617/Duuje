using System.Net;
using System.Net.Http.Json;
using System.Text.Json;
namespace Duale.Api.Tests;

public class Phase2Tests(ApiFactory f) : IClassFixture<ApiFactory>
{
    static readonly Guid Plumbing = new(2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0);   // seeded trade
    static Guid Id(JsonElement e) => e.GetProperty("id").GetGuid();
    static async Task<JsonElement> Json(HttpResponseMessage r) { r.EnsureSuccessStatusCode(); return await r.Content.ReadFromJsonAsync<JsonElement>(); }

    record Company(HttpClient Owner, Guid Id, Guid CustomerId, Guid LocationId, Guid SkillId, HttpClient Admin);
    record Tech(HttpClient Client, string Email, Guid Id);

    async Task<Company> NewCompanyAsync()
    {
        var (owner, _) = await f.UserAsync();
        var company = await f.CreateCompanyAsync(owner);
        await f.ApproveAsync(company);
        var (admin, _) = await f.UserAsync("platform_admin");
        var skill = Id(await Json(await admin.PostAsJsonAsync($"/platform/trades/{Plumbing}/skills", new { name = "Pipe fitting " + Guid.NewGuid().ToString("N") })));
        var cust = Id(await Json(await owner.PostAsJsonAsync($"/companies/{company}/customers", new { name = "Amina", phone = "+252611111111" })));
        var loc = Id(await Json(await owner.PostAsJsonAsync($"/companies/{company}/customers/{cust}/locations", new { label = "Home", address = "Garowe" })));
        return new Company(owner, company, cust, loc, skill, admin);
    }

    // Technician with a verified skill, a wide availability window, and an active relationship with the company.
    async Task<Tech> NewTechnicianAsync(Company c, string type = "Independent", bool verified = true, bool link = true)
    {
        var (client, email) = await f.UserAsync();
        var tech = Id(await Json(await client.PostAsJsonAsync("/technicians/me", new { displayName = "Tech " + Guid.NewGuid().ToString("N")[..4] })));
        (await client.PutAsJsonAsync("/technicians/me/skills", new { skillIds = new[] { c.SkillId } })).EnsureSuccessStatusCode();
        if (verified) (await c.Admin.PostAsJsonAsync($"/platform/technicians/{tech}/skills/{c.SkillId}/decision", new { decision = "approve" })).EnsureSuccessStatusCode();
        (await client.PostAsJsonAsync("/technicians/me/availability", new { startsAt = DateTimeOffset.UtcNow.AddMinutes(-1), endsAt = DateTimeOffset.UtcNow.AddDays(20) })).EnsureSuccessStatusCode();
        if (link)
        {
            var rel = Id(await Json(await c.Owner.PostAsJsonAsync($"/companies/{c.Id}/relationships", new { technicianEmail = email, type })));
            (await client.PostAsJsonAsync($"/technicians/me/relationships/{rel}/respond", new { accept = true })).EnsureSuccessStatusCode();
        }
        return new Tech(client, email, tech);
    }

    async Task<Guid> NewJobAsync(Company c, int dayOffset = 2, int hour = 9)
    {
        var start = DateTimeOffset.UtcNow.Date.AddDays(dayOffset).AddHours(hour);
        var r = await c.Owner.PostAsJsonAsync($"/companies/{c.Id}/jobs", new
        {
            customerId = c.CustomerId, locationId = c.LocationId, tradeId = Plumbing, description = "Fix kitchen sink", priority = "High",
            scheduledStart = start, scheduledEnd = start.AddHours(2), requiredSkillIds = new[] { c.SkillId }
        });
        return Id(await Json(r));
    }

    [Fact]
    public async Task Other_company_cannot_see_jobs_or_use_foreign_customers()
    {
        var a = await NewCompanyAsync(); var b = await NewCompanyAsync();
        var job = await NewJobAsync(a);
        Assert.Equal(HttpStatusCode.NotFound, (await b.Owner.GetAsync($"/companies/{a.Id}/jobs/{job}")).StatusCode);
        Assert.Equal(HttpStatusCode.NotFound, (await b.Owner.GetAsync($"/companies/{b.Id}/jobs/{job}")).StatusCode); // right company, foreign job id
        var start = DateTimeOffset.UtcNow.AddDays(3);
        var r = await b.Owner.PostAsJsonAsync($"/companies/{b.Id}/jobs", new { customerId = a.CustomerId, locationId = a.LocationId, tradeId = Plumbing, description = "x", scheduledStart = start, scheduledEnd = start.AddHours(1) });
        Assert.Equal(HttpStatusCode.BadRequest, r.StatusCode);
    }

    [Fact]
    public async Task Candidates_require_verified_skill_and_employed_ranks_above_independent()
    {
        var c = await NewCompanyAsync();
        var unverified = await NewTechnicianAsync(c, verified: false, link: false);
        var inv = await c.Owner.PostAsJsonAsync($"/companies/{c.Id}/relationships", new { technicianEmail = unverified.Email, type = "Independent" });
        Assert.Equal(HttpStatusCode.Conflict, inv.StatusCode);   // cannot even be linked without a verified skill

        var independent = await NewTechnicianAsync(c, "Independent");
        var employed = await NewTechnicianAsync(c, "Employed");
        var job = await NewJobAsync(c);
        var res = await Json(await c.Owner.GetAsync($"/companies/{c.Id}/jobs/{job}/candidates"));
        var list = res.GetProperty("candidates").EnumerateArray().ToList();
        Assert.Equal(2, list.Count);
        Assert.Equal(employed.Id, list[0].GetProperty("technicianId").GetGuid());
        Assert.True(list[0].GetProperty("score").GetInt32() > list[1].GetProperty("score").GetInt32());
        Assert.Equal("Open", res.GetProperty("status").GetString());   // recommending never assigns
    }

    [Fact]
    public async Task Offer_then_accept_moves_job_and_keeps_history_and_reassign_preserves_old_assignment()
    {
        var c = await NewCompanyAsync();
        var t1 = await NewTechnicianAsync(c); var t2 = await NewTechnicianAsync(c);
        var job = await NewJobAsync(c);
        (await c.Owner.PostAsJsonAsync($"/companies/{c.Id}/jobs/{job}/offer", new { technicianId = t1.Id })).EnsureSuccessStatusCode();
        // a second offer on the same job is refused
        Assert.Equal(HttpStatusCode.Conflict, (await c.Owner.PostAsJsonAsync($"/companies/{c.Id}/jobs/{job}/offer", new { technicianId = t2.Id })).StatusCode);

        var offers = await Json(await t1.Client.GetAsync("/technicians/me/assignments?status=Offered"));
        var aid = offers.EnumerateArray().Single().GetProperty("assignmentId").GetGuid();
        Assert.False(offers.EnumerateArray().Single().GetProperty("job").TryGetProperty("customerId", out _));
        (await t1.Client.PostAsJsonAsync($"/technicians/me/assignments/{aid}/respond", new { accept = true })).EnsureSuccessStatusCode();

        (await c.Owner.PostAsJsonAsync($"/companies/{c.Id}/jobs/{job}/reassign", new { technicianId = t2.Id, reason = "Customer asked for another technician" })).EnsureSuccessStatusCode();
        var detail = await Json(await c.Owner.GetAsync($"/companies/{c.Id}/jobs/{job}"));
        var statuses = detail.GetProperty("assignments").EnumerateArray().Select(a => a.GetProperty("status").GetString()).ToList();
        Assert.Equal(new[] { "Reassigned", "Offered" }, statuses);
        Assert.Equal("Offered", detail.GetProperty("status").GetString());
    }

    [Fact]
    public async Task Technician_cannot_accept_two_overlapping_jobs_or_someone_elses_offer()
    {
        var c = await NewCompanyAsync();
        var t = await NewTechnicianAsync(c); var other = await NewTechnicianAsync(c);
        var j1 = await NewJobAsync(c, 4, 9); var j2 = await NewJobAsync(c, 4, 10);   // overlap 10:00-11:00
        (await c.Owner.PostAsJsonAsync($"/companies/{c.Id}/jobs/{j1}/offer", new { technicianId = t.Id })).EnsureSuccessStatusCode();
        var list = await Json(await t.Client.GetAsync("/technicians/me/assignments?status=Offered"));
        var first = list.EnumerateArray().Single().GetProperty("assignmentId").GetGuid();
        Assert.Equal(HttpStatusCode.NotFound, (await other.Client.PostAsJsonAsync($"/technicians/me/assignments/{first}/respond", new { accept = true })).StatusCode);
        (await t.Client.PostAsJsonAsync($"/technicians/me/assignments/{first}/respond", new { accept = true })).EnsureSuccessStatusCode();

        var blocked = await c.Owner.PostAsJsonAsync($"/companies/{c.Id}/jobs/{j2}/offer", new { technicianId = t.Id });
        Assert.Equal(HttpStatusCode.Conflict, blocked.StatusCode);   // eligibility already shows the clash
    }

    [Fact]
    public async Task Illegal_transitions_and_roles_are_rejected()
    {
        var c = await NewCompanyAsync();
        var job = await NewJobAsync(c);
        (await c.Owner.PostAsJsonAsync($"/companies/{c.Id}/jobs/{job}/cancel", new { reason = "Customer cancelled" })).EnsureSuccessStatusCode();
        Assert.Equal(HttpStatusCode.Conflict, (await c.Owner.PostAsJsonAsync($"/companies/{c.Id}/jobs/{job}/cancel", new { reason = "again" })).StatusCode);
        Assert.Equal(HttpStatusCode.Conflict, (await c.Owner.PostAsJsonAsync($"/companies/{c.Id}/jobs/{job}/reschedule", new { scheduledStart = DateTimeOffset.UtcNow.AddDays(5), scheduledEnd = DateTimeOffset.UtcNow.AddDays(5).AddHours(1) })).StatusCode);

        // an auditor can read jobs but cannot dispatch or create them
        var (auditor, auditorEmail) = await f.UserAsync();
        (await c.Owner.PostAsJsonAsync($"/companies/{c.Id}/members", new { email = auditorEmail, roleCode = "auditor" })).EnsureSuccessStatusCode();
        Assert.Equal(HttpStatusCode.OK, (await auditor.GetAsync($"/companies/{c.Id}/jobs")).StatusCode);
        Assert.Equal(HttpStatusCode.Forbidden, (await auditor.GetAsync($"/companies/{c.Id}/jobs/{job}/candidates")).StatusCode);
    }
}
