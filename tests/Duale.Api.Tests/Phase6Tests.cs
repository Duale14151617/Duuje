using System.Net;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using Duale.Api.Data;
using Duale.Api.Domain;
using Duale.Api.Services;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.DependencyInjection.Extensions;
namespace Duale.Api.Tests;

class RejectingScanner : IUploadScanner { public Task<bool> IsCleanAsync(byte[] data, CancellationToken ct) => Task.FromResult(false); }

// Security, resilience and operability checks for the hardening phase.
public class Phase6Tests(ApiFactory f) : IClassFixture<ApiFactory>
{
    readonly Kit k = new(f);
    FinKit fk => new(f, k);
    static string C(Guid id) => $"/companies/{id}";

    // A second host with different settings that shares the same database; a signed-in client is re-pointed at it.
    static HttpClient On(WebApplicationFactory<Program> host, HttpClient signedIn)
    {
        var c = host.CreateClient();
        c.DefaultRequestHeaders.Authorization = signedIn.DefaultRequestHeaders.Authorization;
        return c;
    }

    [Fact]
    public async Task Responses_carry_security_headers_and_a_correlation_id()
    {
        var r = await f.CreateClient().GetAsync("/health/live");
        Assert.Equal(HttpStatusCode.OK, r.StatusCode);
        Assert.Equal("nosniff", r.Headers.GetValues("X-Content-Type-Options").Single());
        Assert.Equal("DENY", r.Headers.GetValues("X-Frame-Options").Single());
        Assert.Contains("default-src 'none'", r.Headers.GetValues("Content-Security-Policy").Single());
        Assert.Equal("no-store", r.Headers.CacheControl?.NoStore == true ? "no-store" : "");
        Assert.NotEmpty(r.Headers.GetValues("X-Correlation-Id").Single());
    }

    [Fact]
    public async Task Readiness_checks_the_database_and_file_storage()
    {
        await f.UserAsync();   // creates the schema
        var r = await f.CreateClient().GetAsync("/health/ready");
        Assert.Equal(HttpStatusCode.OK, r.StatusCode);
    }

    [Fact]
    public async Task Metrics_exist_only_with_a_configured_token_and_expose_queue_health()
    {
        await f.UserAsync();
        Assert.Equal(HttpStatusCode.NotFound, (await f.CreateClient().GetAsync("/metrics")).StatusCode);   // no token configured = no endpoint
        using var host = f.WithWebHostBuilder(b => b.UseSetting("Metrics:Token", "metrics-token-0123456789"));
        var c = host.CreateClient();
        Assert.Equal(HttpStatusCode.NotFound, (await c.GetAsync("/metrics")).StatusCode);
        c.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue("Bearer", "wrong-token-wrong-token");
        Assert.Equal(HttpStatusCode.NotFound, (await c.GetAsync("/metrics")).StatusCode);
        c.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue("Bearer", "metrics-token-0123456789");
        var text = await (await c.GetAsync("/metrics")).Content.ReadAsStringAsync();
        Assert.Contains("duale_http_requests_total", text);
        Assert.Contains("duale_notification_deliveries_dead", text);
        Assert.Contains("duale_payments_confirmed_unreconciled", text);
        Assert.Contains("duale_http_request_seconds_bucket", text);
    }

    [Fact]
    public async Task Requests_are_rate_limited_per_client()
    {
        using var host = f.WithWebHostBuilder(b => b.UseSetting("RateLimit:ApiPerMinute", "5"));
        var c = host.CreateClient();
        var codes = new List<HttpStatusCode>();
        for (var i = 0; i < 9; i++) codes.Add((await c.GetAsync("/health/live")).StatusCode);
        Assert.Contains(HttpStatusCode.TooManyRequests, codes);
        Assert.Equal(HttpStatusCode.OK, codes[0]);
    }

    [Fact]
    public async Task Permissions_listed_as_mfa_required_are_refused_to_users_without_a_second_factor()
    {
        await f.UserAsync();
        var (admin, _) = await f.UserAsync("platform_admin");
        var (owner, _) = await f.UserAsync();
        var company = await f.CreateCompanyAsync(owner);
        using var host = f.WithWebHostBuilder(b => b.UseSetting("Security:MfaRequiredPermissions", "company.verify"));
        var strict = On(host, admin);
        Assert.Equal(HttpStatusCode.Forbidden, (await strict.PostAsJsonAsync($"/platform/companies/{company}/decision", new { decision = "approve" })).StatusCode);
        Assert.Equal(HttpStatusCode.OK, (await strict.GetAsync("/platform/technician-skills")).StatusCode);   // permissions not on the list are unaffected
        Assert.Equal(HttpStatusCode.OK, (await admin.PostAsJsonAsync($"/platform/companies/{company}/decision", new { decision = "approve" })).StatusCode);   // default host: no policy
    }

    [Fact]
    public async Task Another_company_cannot_reach_any_record_by_substituting_ids()
    {
        var (fld, fin, pid) = await fk.ApprovedPayableAsync("company", 60m, 2m);
        var co1 = fld.Co; var co2 = await k.NewCompanyAsync();
        var exec = await Kit.Json(await co1.Owner.GetAsync($"{C(co1.Id)}/jobs/{fld.JobId}/execution"));
        var evidenceId = exec.GetProperty("evidence")[0].GetProperty("id").GetGuid();

        // company 1's data through company 1's URL
        foreach (var path in new[] { $"{C(co1.Id)}/jobs/{fld.JobId}", $"{C(co1.Id)}/jobs/{fld.JobId}/execution", $"{C(co1.Id)}/payables", $"{C(co1.Id)}/ledger", $"{C(co1.Id)}/reports/jobs", $"{C(co1.Id)}/reports/finance", $"{C(co1.Id)}/customers" })
            Assert.Equal(HttpStatusCode.NotFound, (await co2.Owner.GetAsync(path)).StatusCode);

        // company 1's ids through company 2's own URL (company 2 holds every permission there)
        foreach (var path in new[] { $"{C(co2.Id)}/jobs/{fld.JobId}", $"{C(co2.Id)}/jobs/{fld.JobId}/execution", $"{C(co2.Id)}/jobs/{fld.JobId}/financial-terms", $"{C(co2.Id)}/jobs/{fld.JobId}/candidates" })
            Assert.Equal(HttpStatusCode.NotFound, (await co2.Owner.GetAsync(path)).StatusCode);
        Assert.Equal(HttpStatusCode.NotFound, (await co2.Owner.PostAsJsonAsync($"{C(co2.Id)}/evidence/{evidenceId}/link", new { })).StatusCode);
        Assert.Equal(HttpStatusCode.NotFound, (await co2.Owner.PostAsJsonAsync($"{C(co2.Id)}/jobs/{fld.JobId}/review", new { decision = "approve" })).StatusCode);
        Assert.Equal(HttpStatusCode.NotFound, (await co2.Owner.PostAsJsonAsync($"{C(co2.Id)}/jobs/{fld.JobId}/invoice", new { })).StatusCode);
        Assert.Equal(HttpStatusCode.NotFound, (await co2.Owner.PostAsJsonAsync($"{C(co2.Id)}/jobs/{fld.JobId}/financial-terms", new { currency = "USD", customerCharge = 1m, technicianCompensation = 1m })).StatusCode);

        // a signed link for company 1's evidence cannot be used by someone else
        var link = (await Kit.Json(await co1.Owner.PostAsJsonAsync($"{C(co1.Id)}/evidence/{evidenceId}/link", new { }))).GetProperty("url").GetString()!;
        Assert.Equal(HttpStatusCode.OK, (await co1.Owner.GetAsync(link)).StatusCode);
        Assert.Equal(HttpStatusCode.NotFound, (await co2.Owner.GetAsync(link)).StatusCode);
        Assert.Equal(HttpStatusCode.Unauthorized, (await f.CreateClient().GetAsync(link)).StatusCode);
    }

    [Fact]
    public async Task Staff_cannot_escalate_their_own_role()
    {
        var co = await k.NewCompanyAsync();
        var (_, dispatcherEmail) = await f.UserAsync();
        (await co.Owner.PostAsJsonAsync($"{C(co.Id)}/members", new { email = dispatcherEmail, roleCode = "dispatcher" })).EnsureSuccessStatusCode();
        // The Co fixture's dispatcher is another account; log a fresh one in as that member and try to grant itself ownership.
        Assert.Equal(HttpStatusCode.Forbidden, (await co.Dispatcher.PostAsJsonAsync($"{C(co.Id)}/members", new { email = dispatcherEmail, roleCode = "company_owner" })).StatusCode);
        Assert.Equal(HttpStatusCode.Forbidden, (await co.Supervisor.PostAsJsonAsync($"{C(co.Id)}/members", new { email = dispatcherEmail, roleCode = "company_owner" })).StatusCode);
        Assert.Equal(HttpStatusCode.BadRequest, (await co.Owner.PostAsJsonAsync($"{C(co.Id)}/members", new { email = dispatcherEmail, roleCode = "platform_admin" })).StatusCode);   // platform roles are not company roles
        var tech = await k.NewTechnicianAsync(co);
        Assert.Equal(HttpStatusCode.NotFound, (await tech.Client.GetAsync($"{C(co.Id)}/members")).StatusCode);   // a technician is not staff
    }

    static async Task<HttpResponseMessage> RawUpload(HttpClient c, Guid aid, byte[] bytes, string fileName, string contentType = "image/png")
    {
        var form = new MultipartFormDataContent { { new StringContent("progress"), "kind" } };
        var file = new ByteArrayContent(bytes); file.Headers.ContentType = new MediaTypeHeaderValue(contentType);
        form.Add(file, "file", fileName);
        return await c.PostAsync($"/technicians/me/assignments/{aid}/evidence", form);
    }

    async Task<Kit.Field> OnSiteAsync()
    {
        var fld = await k.AcceptedJobAsync();
        foreach (var s in new[] { "EnRoute", "Arrived", "InProgress" }) (await Kit.StatusAsync(fld.Tech.Client, fld.AssignmentId, s)).EnsureSuccessStatusCode();
        return fld;
    }

    [Fact]
    public async Task Malicious_uploads_are_refused_and_names_cannot_escape()
    {
        var fld = await OnSiteAsync(); var t = fld.Tech.Client; var aid = fld.AssignmentId;
        Assert.Equal(HttpStatusCode.BadRequest, (await RawUpload(t, aid, "MZ\u0090\u0000\u0003"u8.ToArray().Concat(new byte[64]).ToArray(), "photo.png")).StatusCode);   // executable posing as an image
        Assert.Equal(HttpStatusCode.BadRequest, (await RawUpload(t, aid, "<script>alert(1)</script>"u8.ToArray(), "a.png")).StatusCode);
        Assert.Equal(HttpStatusCode.BadRequest, (await RawUpload(t, aid, "<svg onload=alert(1)>"u8.ToArray(), "a.svg", "image/svg+xml")).StatusCode);
        Assert.Equal(HttpStatusCode.RequestEntityTooLarge, (await RawUpload(t, aid, Kit.Png.Concat(new byte[6_000_000]).ToArray(), "big.png")).StatusCode);

        var ok = await Kit.Json(await RawUpload(t, aid, Kit.Png, "../../../etc/passwd.png"));
        Assert.DoesNotContain("/", ok.GetProperty("fileName").GetString());
        Assert.Equal("image/png", ok.GetProperty("contentType").GetString());   // taken from the bytes, not from the request
    }

    [Fact]
    public async Task A_failing_scanner_blocks_the_upload()
    {
        var fld = await OnSiteAsync();
        using var host = f.WithWebHostBuilder(b => b.ConfigureServices(s => { s.RemoveAll<IUploadScanner>(); s.AddSingleton<IUploadScanner, RejectingScanner>(); }));
        var r = await RawUpload(On(host, fld.Tech.Client), fld.AssignmentId, Kit.Png, "photo.png");
        Assert.Equal(HttpStatusCode.BadRequest, r.StatusCode);
        Assert.Contains("security scan", await r.Content.ReadAsStringAsync());
    }

    [Fact]
    public async Task Audit_events_cannot_be_edited_or_deleted()
    {
        var co = await k.NewCompanyAsync();
        using var scope = f.Services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<AppDbContext>();
        var ev = await db.AuditEvents.FirstAsync(e => e.CompanyId == co.Id);
        ev.Action = "tampered";
        await Assert.ThrowsAsync<InvalidOperationException>(() => db.SaveChangesAsync());
        db.ChangeTracker.Clear();
        db.AuditEvents.Remove(await db.AuditEvents.FirstAsync(e => e.CompanyId == co.Id));
        await Assert.ThrowsAsync<InvalidOperationException>(() => db.SaveChangesAsync());
        var pe = new PaymentEvent { PaymentId = Guid.NewGuid(), Event = "x" };
        db.ChangeTracker.Clear();
        db.Attach(pe).State = EntityState.Modified;
        await Assert.ThrowsAsync<InvalidOperationException>(() => db.SaveChangesAsync());
    }

    [Fact]
    public async Task Expired_idempotency_records_are_purged_and_recent_ones_kept()
    {
        await f.UserAsync();
        using var scope = f.Services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<AppDbContext>();
        db.IdempotencyRecords.AddRange(new IdempotencyRecord { Scope = "t", Key = "old-" + Guid.NewGuid(), ResponseStatus = 200, CreatedAt = DateTime.UtcNow.AddDays(-30) },
                                       new IdempotencyRecord { Scope = "t", Key = "new-" + Guid.NewGuid(), ResponseStatus = 200, CreatedAt = DateTime.UtcNow.AddDays(-1) });
        await db.SaveChangesAsync();
        var gone = await new RetentionService(db, new ConfigurationBuilder().Build()).PurgeAsync(DateTime.UtcNow, default);
        Assert.True(gone >= 1);
        Assert.Equal(0, await db.IdempotencyRecords.CountAsync(x => x.Scope == "t" && x.Key.StartsWith("old-")));
        Assert.Equal(1, await db.IdempotencyRecords.CountAsync(x => x.Scope == "t" && x.Key.StartsWith("new-")));
    }

    [Fact]
    public async Task A_queued_request_replayed_after_a_dropped_connection_has_one_effect()
    {
        var fld = await k.AcceptedJobAsync();
        var key = "queued-" + Guid.NewGuid();
        var first = await Kit.StatusAsync(fld.Tech.Client, fld.AssignmentId, "EnRoute", key);
        var replay = await Kit.StatusAsync(fld.Tech.Client, fld.AssignmentId, "EnRoute", key);     // the phone never saw the first answer
        Assert.Equal(HttpStatusCode.OK, first.StatusCode); Assert.Equal(HttpStatusCode.OK, replay.StatusCode);
        var detail = await Kit.Json(await fld.Co.Owner.GetAsync($"{C(fld.Co.Id)}/jobs/{fld.JobId}"));
        Assert.Equal(1, detail.GetProperty("history").EnumerateArray().Count(h => h.GetProperty("to").GetString() == "EnRoute"));

        // the same queue replayed in order (EnRoute already done, then Arrived) stays consistent
        var arrivedKey = "queued-" + Guid.NewGuid();
        Assert.Equal(HttpStatusCode.OK, (await Kit.StatusAsync(fld.Tech.Client, fld.AssignmentId, "Arrived", arrivedKey)).StatusCode);
        Assert.Equal(HttpStatusCode.OK, (await Kit.StatusAsync(fld.Tech.Client, fld.AssignmentId, "Arrived", arrivedKey)).StatusCode);
        // an out-of-order action is refused by the state machine, and a replay of that refusal is the same refusal
        var skipKey = "queued-" + Guid.NewGuid();
        Assert.Equal(HttpStatusCode.Conflict, (await Kit.StatusAsync(fld.Tech.Client, fld.AssignmentId, "EnRoute", skipKey)).StatusCode);
        Assert.Equal(HttpStatusCode.Conflict, (await Kit.StatusAsync(fld.Tech.Client, fld.AssignmentId, "EnRoute", skipKey)).StatusCode);
    }

    [Fact]
    public async Task A_large_notification_backlog_survives_a_provider_outage_and_drains_in_batches()
    {
        var (_, email) = await f.UserAsync();
        Guid uid;
        using (var scope = f.Services.CreateScope())
        {
            var db = scope.ServiceProvider.GetRequiredService<AppDbContext>();
            uid = await db.Users.Where(u => u.Email == email).Select(u => u.Id).FirstAsync();
            db.NotificationPreferences.Add(new NotificationPreference { UserId = uid, Channel = "email", Enabled = true });
            for (var i = 0; i < 250; i++) db.Notifications.Add(new Notification { UserId = uid, Kind = "load.test", Title = "n" + i, Body = "b" });
            await db.SaveChangesAsync();
        }
        using var s2 = f.Services.CreateScope();
        var d2 = s2.ServiceProvider.GetRequiredService<AppDbContext>();
        var cfg = new ConfigurationBuilder().AddInMemoryCollection(new Dictionary<string, string?> { ["Notifications:BackoffSeconds"] = "10", ["Notifications:MaxAttempts"] = "5" }).Build();
        var t0 = DateTime.UtcNow;

        var outage = new FakeProvider("email", _ => throw new HttpRequestException("provider down"));
        var disp = new NotificationDispatcher(d2, [outage], cfg);
        for (var i = 0; i < 4; i++) await disp.RunOnceAsync(t0, default);   // fan-out is capped per run; sends are capped at 100
        Assert.Equal(0, await d2.Deliveries.CountAsync(x => x.UserId == uid && x.Status == "Sent"));
        Assert.Equal(0, await d2.Deliveries.CountAsync(x => x.UserId == uid && x.Status == "Dead"));   // an outage must not kill messages
        Assert.Equal(250, await d2.Deliveries.CountAsync(x => x.UserId == uid && x.Status == "Pending"));

        var healthy = new FakeProvider("email", _ => new SendResult(true, "ok"));
        var recovered = new NotificationDispatcher(d2, [healthy], cfg);
        var passes = 0;
        while (await d2.Deliveries.AnyAsync(x => x.UserId == uid && x.Status == "Pending") && passes++ < 10) await recovered.RunOnceAsync(t0.AddMinutes(5), default);
        Assert.Equal(250, await d2.Deliveries.CountAsync(x => x.UserId == uid && x.Status == "Sent"));
        Assert.Equal(250, healthy.Sent.Select(m => m.DeliveryId).Distinct().Count());   // nothing sent twice
    }

    [Fact]
    public async Task Integrity_check_is_clean_on_good_data_and_flags_a_tampered_ledger()
    {
        var (fld, fin, pid) = await fk.ApprovedPayableAsync("company", 60m, 0m);
        var co = fld.Co;
        var pay = await fk.InitiateAsync(co.Owner, co.Id, new { payableId = pid, method = "bank", amount = 60m, providerRef = "INT-1" });
        (await fin.PostAsJsonAsync($"{C(co.Id)}/payments/{pay}/confirm", new { })).EnsureSuccessStatusCode();

        var (admin, _) = await f.UserAsync("platform_admin");
        var clean = await Kit.Json(await admin.GetAsync("/platform/integrity"));
        Assert.DoesNotContain(clean.GetProperty("findings").EnumerateArray(), x => x.GetProperty("detail").GetString()!.Contains(pay.ToString()) || x.GetProperty("detail").GetString()!.Contains(co.Id.ToString()));
        Assert.Equal(HttpStatusCode.Forbidden, (await co.Owner.GetAsync("/platform/integrity")).StatusCode);

        using (var scope = f.Services.CreateScope())   // simulate corruption that bypassed the application (SQLite has no trigger; PostgreSQL would refuse it)
        {
            var db = scope.ServiceProvider.GetRequiredService<AppDbContext>();
            db.Ledger.Add(new LedgerEntry { CompanyId = co.Id, TxnKey = "tamper:1", LineKey = "tamper:1#0", AccountCode = "1000", Debit = 5m, Currency = "USD", SourceType = "test", SourceId = "x" });
            await db.SaveChangesAsync();
        }
        var bad = await Kit.Json(await admin.GetAsync("/platform/integrity"));
        Assert.False(bad.GetProperty("ok").GetBoolean());
        Assert.Contains(bad.GetProperty("findings").EnumerateArray(), x => x.GetProperty("check").GetString() == "ledger_balanced" && x.GetProperty("detail").GetString()!.Contains("tamper:1"));
    }
}
