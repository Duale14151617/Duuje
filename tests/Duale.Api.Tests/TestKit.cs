using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text.Json;
namespace Duale.Api.Tests;

// Shared scenario builders for the Phase 3+ tests.
public class Kit(ApiFactory f)
{
    public static readonly Guid Plumbing = new(2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0);   // seeded trade
    public static Guid Id(JsonElement e) => e.GetProperty("id").GetGuid();
    public static async Task<JsonElement> Json(HttpResponseMessage r) { r.EnsureSuccessStatusCode(); return await r.Content.ReadFromJsonAsync<JsonElement>(); }
    public static readonly byte[] Png = [0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A, 1, 2, 3, 4, 5, 6, 7, 8];

    public record Co(HttpClient Owner, Guid Id, Guid CustomerId, Guid LocationId, Guid SkillId, HttpClient Admin, HttpClient Supervisor, HttpClient Dispatcher);
    public record Tech(HttpClient Client, string Email, Guid Id);
    public record Field(Co Co, Tech Tech, Guid JobId, Guid AssignmentId);

    public async Task<Co> NewCompanyAsync()
    {
        var (owner, _) = await f.UserAsync();
        var company = await f.CreateCompanyAsync(owner);
        await f.ApproveAsync(company);
        var (admin, _) = await f.UserAsync("platform_admin");
        var skill = Id(await Json(await admin.PostAsJsonAsync($"/platform/trades/{Plumbing}/skills", new { name = "Pipe fitting " + Guid.NewGuid().ToString("N") })));
        var cust = Id(await Json(await owner.PostAsJsonAsync($"/companies/{company}/customers", new { name = "Amina", phone = "+252611111111" })));
        var loc = Id(await Json(await owner.PostAsJsonAsync($"/companies/{company}/customers/{cust}/locations", new { label = "Home", address = "Garowe, Hodan street 12", accessInstructions = "Blue gate" })));
        var (sup, supEmail) = await f.UserAsync();
        var (disp, dispEmail) = await f.UserAsync();
        (await owner.PostAsJsonAsync($"/companies/{company}/members", new { email = supEmail, roleCode = "supervisor" })).EnsureSuccessStatusCode();
        (await owner.PostAsJsonAsync($"/companies/{company}/members", new { email = dispEmail, roleCode = "dispatcher" })).EnsureSuccessStatusCode();
        return new Co(owner, company, cust, loc, skill, admin, sup, disp);
    }

    public async Task<Tech> NewTechnicianAsync(Co c, string type = "Independent")
    {
        var (client, email) = await f.UserAsync();
        var tech = Id(await Json(await client.PostAsJsonAsync("/technicians/me", new { displayName = "Tech " + Guid.NewGuid().ToString("N")[..4] })));
        (await client.PutAsJsonAsync("/technicians/me/skills", new { skillIds = new[] { c.SkillId } })).EnsureSuccessStatusCode();
        (await c.Admin.PostAsJsonAsync($"/platform/technicians/{tech}/skills/{c.SkillId}/decision", new { decision = "approve" })).EnsureSuccessStatusCode();
        (await client.PostAsJsonAsync("/technicians/me/availability", new { startsAt = DateTimeOffset.UtcNow.AddMinutes(-1), endsAt = DateTimeOffset.UtcNow.AddDays(20) })).EnsureSuccessStatusCode();
        var rel = Id(await Json(await c.Owner.PostAsJsonAsync($"/companies/{c.Id}/relationships", new { technicianEmail = email, type })));
        (await client.PostAsJsonAsync($"/technicians/me/relationships/{rel}/respond", new { accept = true })).EnsureSuccessStatusCode();
        return new Tech(client, email, tech);
    }

    public async Task<Guid> NewJobAsync(Co c, int dayOffset = 2, int hour = 9, int? warrantyDays = null)
    {
        var start = DateTimeOffset.UtcNow.Date.AddDays(dayOffset).AddHours(hour);
        var r = await c.Owner.PostAsJsonAsync($"/companies/{c.Id}/jobs", new
        {
            customerId = c.CustomerId, locationId = c.LocationId, tradeId = Plumbing, description = "Fix kitchen sink", priority = "High",
            scheduledStart = start, scheduledEnd = start.AddHours(2), requiredSkillIds = new[] { c.SkillId }, warrantyDays
        });
        return Id(await Json(r));
    }

    public async Task<Guid> OfferAsync(Co c, Guid jobId, Tech t)
    {
        var r = await Json(await c.Owner.PostAsJsonAsync($"/companies/{c.Id}/jobs/{jobId}/offer", new { technicianId = t.Id }));
        return r.GetProperty("assignmentId").GetGuid();
    }

    public async Task<Field> AcceptedJobAsync(Co? co = null, Tech? tech = null, int dayOffset = 2, int hour = 9, int? warrantyDays = null)
    {
        co ??= await NewCompanyAsync();
        tech ??= await NewTechnicianAsync(co);
        var job = await NewJobAsync(co, dayOffset, hour, warrantyDays);
        var aid = await OfferAsync(co, job, tech);
        (await tech.Client.PostAsJsonAsync($"/technicians/me/assignments/{aid}/respond", new { accept = true })).EnsureSuccessStatusCode();
        return new Field(co, tech, job, aid);
    }

    public static Task<HttpResponseMessage> StatusAsync(HttpClient c, Guid aid, string status, string? key = null)
    {
        var req = new HttpRequestMessage(HttpMethod.Post, $"/technicians/me/assignments/{aid}/status") { Content = JsonContent.Create(new { status }) };
        if (key != null) req.Headers.Add("Idempotency-Key", key);
        return c.SendAsync(req);
    }

    public static Task<HttpResponseMessage> UploadAsync(HttpClient c, Guid aid, string kind = "progress", byte[]? bytes = null, string? key = null)
    {
        var form = new MultipartFormDataContent { { new StringContent(kind), "kind" } };
        var file = new ByteArrayContent(bytes ?? Png); file.Headers.ContentType = new MediaTypeHeaderValue("image/png");
        form.Add(file, "file", "photo.png");
        var req = new HttpRequestMessage(HttpMethod.Post, $"/technicians/me/assignments/{aid}/evidence") { Content = form };
        if (key != null) req.Headers.Add("Idempotency-Key", key);
        return c.SendAsync(req);
    }

    // EnRoute -> Arrived -> InProgress -> evidence -> report: leaves the job AwaitingReview.
    public async Task<Field> SubmittedJobAsync(int dayOffset = 2, int hour = 9, int? warrantyDays = null, Co? co = null, Tech? tech = null)
    {
        var fld = await AcceptedJobAsync(co, tech, dayOffset, hour, warrantyDays);
        foreach (var s in new[] { "EnRoute", "Arrived", "InProgress" }) (await StatusAsync(fld.Tech.Client, fld.AssignmentId, s)).EnsureSuccessStatusCode();
        (await UploadAsync(fld.Tech.Client, fld.AssignmentId, "after")).EnsureSuccessStatusCode();
        (await fld.Tech.Client.PostAsJsonAsync($"/technicians/me/assignments/{fld.AssignmentId}/report", new { summary = "Replaced the sink trap.", hoursWorked = 1.5 })).EnsureSuccessStatusCode();
        return fld;
    }

    public async Task<Field> CompletedJobAsync(int dayOffset = 2, int hour = 9, int? warrantyDays = null, Co? co = null, Tech? tech = null)
    {
        var fld = await SubmittedJobAsync(dayOffset, hour, warrantyDays, co, tech);
        (await fld.Co.Supervisor.PostAsJsonAsync($"/companies/{fld.Co.Id}/jobs/{fld.JobId}/review", new { decision = "approve" })).EnsureSuccessStatusCode();
        return fld;
    }
}
