using System.Net;
using System.Net.Http.Json;
namespace Duale.Api.Tests;

public class Phase3Tests(ApiFactory f) : IClassFixture<ApiFactory>
{
    readonly Kit k = new(f);

    [Fact]
    public async Task Customer_details_are_hidden_until_accepted_and_from_other_technicians()
    {
        var co = await k.NewCompanyAsync();
        var t1 = await k.NewTechnicianAsync(co); var t2 = await k.NewTechnicianAsync(co);
        var job = await k.NewJobAsync(co);
        var aid = await k.OfferAsync(co, job, t1);

        var before = await Kit.Json(await t1.Client.GetAsync($"/technicians/me/assignments/{aid}/job"));
        Assert.Equal(System.Text.Json.JsonValueKind.Null, before.GetProperty("customer").ValueKind);

        (await t1.Client.PostAsJsonAsync($"/technicians/me/assignments/{aid}/respond", new { accept = true })).EnsureSuccessStatusCode();
        var after = await Kit.Json(await t1.Client.GetAsync($"/technicians/me/assignments/{aid}/job"));
        Assert.Equal("Amina", after.GetProperty("customer").GetProperty("name").GetString());
        Assert.Equal(HttpStatusCode.NotFound, (await t2.Client.GetAsync($"/technicians/me/assignments/{aid}/job")).StatusCode);
    }

    [Fact]
    public async Task Full_execution_with_return_and_resubmission_then_approval()
    {
        var fld = await k.AcceptedJobAsync();
        var t = fld.Tech.Client; var aid = fld.AssignmentId; var co = fld.Co;

        // cannot skip steps
        Assert.Equal(HttpStatusCode.Conflict, (await Kit.StatusAsync(t, aid, "InProgress")).StatusCode);
        foreach (var s in new[] { "EnRoute", "Arrived", "InProgress" }) (await Kit.StatusAsync(t, aid, s)).EnsureSuccessStatusCode();

        // report needs evidence
        var noEvidence = await t.PostAsJsonAsync($"/technicians/me/assignments/{aid}/report", new { summary = "Done" });
        Assert.Equal(HttpStatusCode.Conflict, noEvidence.StatusCode);
        (await Kit.UploadAsync(t, aid, "after")).EnsureSuccessStatusCode();
        (await t.PostAsJsonAsync($"/technicians/me/assignments/{aid}/report", new { summary = "Done", hoursWorked = 2 })).EnsureSuccessStatusCode();

        // a dispatcher cannot review; the supervisor must give a note when returning
        Assert.Equal(HttpStatusCode.Forbidden, (await co.Dispatcher.PostAsJsonAsync($"/companies/{co.Id}/jobs/{fld.JobId}/review", new { decision = "approve" })).StatusCode);
        Assert.Equal(HttpStatusCode.BadRequest, (await co.Supervisor.PostAsJsonAsync($"/companies/{co.Id}/jobs/{fld.JobId}/review", new { decision = "return" })).StatusCode);
        (await co.Supervisor.PostAsJsonAsync($"/companies/{co.Id}/jobs/{fld.JobId}/review", new { decision = "return", note = "Leak at the joint" })).EnsureSuccessStatusCode();

        var view = await Kit.Json(await t.GetAsync($"/technicians/me/assignments/{aid}/job"));
        Assert.Equal("Leak at the joint", view.GetProperty("returnNote").GetString());

        // fixing needs NEW evidence and a second report version
        (await Kit.StatusAsync(t, aid, "InProgress")).EnsureSuccessStatusCode();
        Assert.Equal(HttpStatusCode.Conflict, (await t.PostAsJsonAsync($"/technicians/me/assignments/{aid}/report", new { summary = "Fixed" })).StatusCode);
        (await Kit.UploadAsync(t, aid, "after")).EnsureSuccessStatusCode();
        var second = await Kit.Json(await t.PostAsJsonAsync($"/technicians/me/assignments/{aid}/report", new { summary = "Fixed" }));
        Assert.Equal(2, second.GetProperty("version").GetInt32());

        var done = await Kit.Json(await co.Supervisor.PostAsJsonAsync($"/companies/{co.Id}/jobs/{fld.JobId}/review", new { decision = "approve" }));
        Assert.Equal("Completed", done.GetProperty("status").GetString());
        var detail = await Kit.Json(await co.Owner.GetAsync($"/companies/{co.Id}/jobs/{fld.JobId}"));
        var states = detail.GetProperty("history").EnumerateArray().Select(h => h.GetProperty("to").GetString()).ToList();
        Assert.Equal(new[] { "Open", "Offered", "Accepted", "EnRoute", "Arrived", "InProgress", "AwaitingReview", "ReturnedForCorrection", "InProgress", "AwaitingReview", "Completed" }, states);
    }

    [Fact]
    public async Task Status_updates_and_uploads_are_idempotent()
    {
        var fld = await k.AcceptedJobAsync();
        var t = fld.Tech.Client; var aid = fld.AssignmentId;
        (await Kit.StatusAsync(t, aid, "EnRoute", "key-1")).EnsureSuccessStatusCode();
        var replay = await Kit.StatusAsync(t, aid, "EnRoute", "key-1");   // a retry after a dropped connection
        Assert.Equal(HttpStatusCode.OK, replay.StatusCode);
        Assert.Equal(HttpStatusCode.Conflict, (await Kit.StatusAsync(t, aid, "EnRoute", "key-2")).StatusCode);   // a genuinely new request is judged on its own

        await Kit.StatusAsync(t, aid, "Arrived"); await Kit.StatusAsync(t, aid, "InProgress");
        (await Kit.UploadAsync(t, aid, "before", key: "up-1")).EnsureSuccessStatusCode();
        (await Kit.UploadAsync(t, aid, "before", key: "up-1")).EnsureSuccessStatusCode();
        var list = await Kit.Json(await t.GetAsync($"/technicians/me/assignments/{aid}/evidence"));
        Assert.Single(list.EnumerateArray());

        var detail = await Kit.Json(await fld.Co.Owner.GetAsync($"/companies/{fld.Co.Id}/jobs/{fld.JobId}"));
        Assert.Single(detail.GetProperty("history").EnumerateArray().Where(h => h.GetProperty("to").GetString() == "EnRoute"));
    }

    [Fact]
    public async Task Evidence_is_private_to_the_technician_and_their_company()
    {
        var fld = await k.SubmittedJobAsync();
        var t = fld.Tech.Client; var co = fld.Co;
        var ev = await Kit.Json(await t.GetAsync($"/technicians/me/assignments/{fld.AssignmentId}/evidence"));
        var eid = ev.EnumerateArray().First().GetProperty("id").GetGuid();

        var link = await Kit.Json(await co.Supervisor.PostAsync($"/companies/{co.Id}/evidence/{eid}/link", null));
        var file = await co.Supervisor.GetAsync(link.GetProperty("url").GetString());
        Assert.Equal(HttpStatusCode.OK, file.StatusCode);
        Assert.Equal(Kit.Png, await file.Content.ReadAsByteArrayAsync());

        var other = await k.NewCompanyAsync();   // another tenant
        Assert.Equal(HttpStatusCode.NotFound, (await other.Supervisor.PostAsync($"/companies/{other.Id}/evidence/{eid}/link", null)).StatusCode);
        Assert.Equal(HttpStatusCode.NotFound, (await other.Supervisor.PostAsync($"/companies/{co.Id}/evidence/{eid}/link", null)).StatusCode);
        Assert.Equal(HttpStatusCode.NotFound, (await other.Supervisor.GetAsync(link.GetProperty("url").GetString())).StatusCode);   // a leaked link alone is useless
    }

    [Fact]
    public async Task Executable_upload_is_rejected()
    {
        var fld = await k.AcceptedJobAsync();
        foreach (var s in new[] { "EnRoute", "Arrived" }) (await Kit.StatusAsync(fld.Tech.Client, fld.AssignmentId, s)).EnsureSuccessStatusCode();
        var r = await Kit.UploadAsync(fld.Tech.Client, fld.AssignmentId, "other", new byte[] { 0x4D, 0x5A, 0x90, 0x00, 1, 2, 3 });
        Assert.Equal(HttpStatusCode.BadRequest, r.StatusCode);
    }

    [Fact]
    public async Task Pending_scope_change_blocks_approval_until_decided()
    {
        var fld = await k.AcceptedJobAsync();
        var t = fld.Tech.Client; var aid = fld.AssignmentId; var co = fld.Co;
        foreach (var s in new[] { "EnRoute", "Arrived", "InProgress" }) (await Kit.StatusAsync(t, aid, s)).EnsureSuccessStatusCode();
        var sc = await Kit.Json(await t.PostAsJsonAsync($"/technicians/me/assignments/{aid}/scope-change", new { description = "Pipe behind the wall is corroded" }));
        (await Kit.UploadAsync(t, aid, "after")).EnsureSuccessStatusCode();
        (await t.PostAsJsonAsync($"/technicians/me/assignments/{aid}/report", new { summary = "Replaced extra pipe" })).EnsureSuccessStatusCode();

        Assert.Equal(HttpStatusCode.Conflict, (await co.Supervisor.PostAsJsonAsync($"/companies/{co.Id}/jobs/{fld.JobId}/review", new { decision = "approve" })).StatusCode);
        (await co.Supervisor.PostAsJsonAsync($"/companies/{co.Id}/jobs/{fld.JobId}/scope-changes/{Kit.Id(sc)}/decision", new { decision = "approve", note = "OK" })).EnsureSuccessStatusCode();
        (await co.Supervisor.PostAsJsonAsync($"/companies/{co.Id}/jobs/{fld.JobId}/review", new { decision = "approve" })).EnsureSuccessStatusCode();
    }

    [Fact]
    public async Task Complaint_then_warranty_callback_links_a_new_job()
    {
        var done = await k.CompletedJobAsync(warrantyDays: 30);
        var co = done.Co;

        var c = await Kit.Json(await co.Supervisor.PostAsJsonAsync($"/companies/{co.Id}/jobs/{done.JobId}/complaints", new { description = "Sink still drips" }));
        var cb = await Kit.Json(await co.Supervisor.PostAsJsonAsync($"/companies/{co.Id}/jobs/{done.JobId}/callback",
            new { scheduledStart = DateTimeOffset.UtcNow.AddDays(5), scheduledEnd = DateTimeOffset.UtcNow.AddDays(5).AddHours(2), responsibility = "technician", complaintId = Kit.Id(c) }));
        Assert.True(cb.GetProperty("underWarranty").GetBoolean());

        var child = await Kit.Json(await co.Owner.GetAsync($"/companies/{co.Id}/jobs/{Kit.Id(cb)}"));
        Assert.Equal("Open", child.GetProperty("status").GetString());
        var exec = await Kit.Json(await co.Owner.GetAsync($"/companies/{co.Id}/jobs/{done.JobId}/execution"));
        Assert.Single(exec.GetProperty("related").EnumerateArray());

        (await co.Supervisor.PostAsJsonAsync($"/companies/{co.Id}/jobs/{done.JobId}/complaints/{Kit.Id(c)}/resolve", new { resolution = "Callback scheduled" })).EnsureSuccessStatusCode();

        var open = await k.NewJobAsync(co, 6, 9);   // not completed: no callback
        Assert.Equal(HttpStatusCode.Conflict, (await co.Supervisor.PostAsJsonAsync($"/companies/{co.Id}/jobs/{open}/callback", new { scheduledStart = DateTimeOffset.UtcNow.AddDays(7), scheduledEnd = DateTimeOffset.UtcNow.AddDays(7).AddHours(1) })).StatusCode);
    }
}
