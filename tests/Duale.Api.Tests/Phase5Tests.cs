using System.Net;
using System.Net.Http.Json;
using Duale.Api.Data;
using Duale.Api.Domain;
using Duale.Api.Services;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
namespace Duale.Api.Tests;

class FakeProvider(string channel, Func<DeliveryMessage, SendResult> behave) : INotificationProvider
{
    public string Channel => channel;
    public List<DeliveryMessage> Sent { get; } = [];
    public Task<SendResult> SendAsync(DeliveryMessage m, CancellationToken ct) { Sent.Add(m); return Task.FromResult(behave(m)); }
}

public class Phase5Tests(ApiFactory f) : IClassFixture<ApiFactory>
{
    readonly Kit k = new(f);
    FinKit fk => new(f, k);

    static IConfiguration Cfg(params (string, string)[] kv) => new ConfigurationBuilder().AddInMemoryCollection(kv.ToDictionary(x => x.Item1, x => (string?)x.Item2)).Build();

    // A technician with an email preference switched on, plus the notification a job offer creates for them.
    async Task<(Kit.Tech Tech, Guid UserId)> TechWithEmailAsync()
    {
        var co = await k.NewCompanyAsync();
        var tech = await k.NewTechnicianAsync(co);
        var job = await k.NewJobAsync(co);
        await k.OfferAsync(co, job, tech);                      // notifies the technician in-app
        using var scope = f.Services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<AppDbContext>();
        var uid = await db.Technicians.Where(t => t.Id == tech.Id).Select(t => t.UserId).FirstAsync();
        db.NotificationPreferences.Add(new NotificationPreference { UserId = uid, Channel = "email", Enabled = true });
        await db.SaveChangesAsync();
        return (tech, uid);
    }

    [Fact]
    public async Task Only_users_who_enabled_a_channel_get_deliveries_and_a_rerun_never_resends()
    {
        var (tech, uid) = await TechWithEmailAsync();
        var (otherClient, otherEmail) = await f.UserAsync();     // no preference: in-app only
        var provider = new FakeProvider("email", _ => new SendResult(true, "msg-1"));

        using var scope = f.Services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<AppDbContext>();
        var d = new NotificationDispatcher(db, [provider], Cfg());
        var now = DateTime.UtcNow;
        await d.RunOnceAsync(now, default);
        await d.RunOnceAsync(now.AddMinutes(5), default);

        var email = await db.Users.Where(u => u.Id == uid).Select(u => u.Email).FirstAsync();
        Assert.Single(provider.Sent, m => m.Address == email);                  // exactly once across two runs
        Assert.DoesNotContain(provider.Sent, m => m.Address == otherEmail);
        var delivery = await db.Deliveries.SingleAsync(x => x.UserId == uid);
        Assert.Equal("Sent", delivery.Status); Assert.Equal(1, delivery.Attempts);
        Assert.Equal(delivery.Id.ToString(), provider.Sent.Single(m => m.Address == email).DeliveryId);   // providers can dedupe on this
        Assert.Equal(HttpStatusCode.OK, (await tech.Client.GetAsync("/notifications")).StatusCode);        // in-app copy is unaffected
    }

    [Fact]
    public async Task Failed_deliveries_back_off_then_die_and_platform_staff_can_retry_them()
    {
        var (_, uid) = await TechWithEmailAsync();
        var broken = new FakeProvider("email", _ => new SendResult(false, null, "provider outage"));
        using var scope = f.Services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<AppDbContext>();
        var cfg = Cfg(("Notifications:MaxAttempts", "3"), ("Notifications:BackoffSeconds", "10"));
        var d = new NotificationDispatcher(db, [broken], cfg);
        var t0 = DateTime.UtcNow;

        await d.RunOnceAsync(t0, default);
        var row = await db.Deliveries.SingleAsync(x => x.UserId == uid);
        Assert.Equal("Pending", row.Status); Assert.Equal(1, row.Attempts); Assert.True(row.NextAttemptAt >= t0.AddSeconds(10));

        await d.RunOnceAsync(t0.AddSeconds(5), default);          // not due yet
        await db.Entry(row).ReloadAsync(); Assert.Equal(1, row.Attempts);
        await d.RunOnceAsync(t0.AddSeconds(11), default);         // second attempt, longer wait
        await db.Entry(row).ReloadAsync(); Assert.Equal(2, row.Attempts); Assert.True(row.NextAttemptAt >= t0.AddSeconds(11 + 20));
        await d.RunOnceAsync(t0.AddMinutes(10), default);         // third and last
        await db.Entry(row).ReloadAsync();
        Assert.Equal("Dead", row.Status); Assert.Contains("outage", row.LastError);

        // platform oversight sees it (without message bodies) and can put it back in the queue; company users cannot
        var (admin, _) = await f.UserAsync("platform_admin");
        var (company, _) = await f.UserAsync();
        Assert.Equal(HttpStatusCode.Forbidden, (await company.GetAsync("/platform/notifications/deliveries")).StatusCode);
        var dead = await Kit.Json(await admin.GetAsync("/platform/notifications/deliveries?status=Dead"));
        Assert.Contains(dead.EnumerateArray(), x => x.GetProperty("id").GetGuid() == row.Id);
        Assert.DoesNotContain("body", dead.ToString());
        Assert.Equal(HttpStatusCode.Forbidden, (await company.PostAsync($"/platform/notifications/deliveries/{row.Id}/retry", null)).StatusCode);
        (await admin.PostAsync($"/platform/notifications/deliveries/{row.Id}/retry", null)).EnsureSuccessStatusCode();

        var working = new FakeProvider("email", _ => new SendResult(true, "ok"));
        await new NotificationDispatcher(db, [working], cfg).RunOnceAsync(DateTime.UtcNow.AddSeconds(1), default);
        await db.Entry(row).ReloadAsync(); Assert.Equal("Sent", row.Status);
    }

    [Fact]
    public async Task A_recipient_without_an_address_is_marked_dead_instead_of_retried_forever()
    {
        var (_, uid) = await TechWithEmailAsync();
        using var scope = f.Services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<AppDbContext>();
        db.NotificationPreferences.Add(new NotificationPreference { UserId = uid, Channel = "sms", Enabled = true });   // technician has no phone
        await db.SaveChangesAsync();
        var d = new NotificationDispatcher(db, [new FakeProvider("email", _ => new SendResult(true)), new FakeProvider("sms", _ => new SendResult(true))], Cfg());
        await d.RunOnceAsync(DateTime.UtcNow, default);
        Assert.Equal("Dead", (await db.Deliveries.SingleAsync(x => x.UserId == uid && x.Channel == "sms")).Status);
        Assert.Equal("Sent", (await db.Deliveries.SingleAsync(x => x.UserId == uid && x.Channel == "email")).Status);
    }

    [Fact]
    public async Task A_channel_without_a_configured_provider_cannot_be_enabled()
    {
        var (c, _) = await f.UserAsync();
        Assert.Equal(HttpStatusCode.Conflict, (await c.PutAsJsonAsync("/notifications/preferences", new { channel = "email", enabled = true })).StatusCode);
        Assert.Equal(HttpStatusCode.NoContent, (await c.PutAsJsonAsync("/notifications/preferences", new { channel = "email", enabled = false })).StatusCode);
        var prefs = await Kit.Json(await c.GetAsync("/notifications/preferences"));
        Assert.Empty(prefs.GetProperty("availableChannels").EnumerateArray());
    }

    [Fact]
    public async Task Reminders_are_created_once_and_read_all_marks_them()
    {
        var fld = await k.AcceptedJobAsync();
        using var scope = f.Services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<AppDbContext>();
        var now = DateTime.UtcNow;
        var job = await db.Jobs.FirstAsync(j => j.Id == fld.JobId);
        job.ScheduledStart = now.AddHours(1); job.ScheduledEnd = now.AddHours(3);
        var a = await db.Assignments.FirstAsync(x => x.Id == fld.AssignmentId); a.ScheduledStart = job.ScheduledStart; a.ScheduledEnd = job.ScheduledEnd;
        await db.SaveChangesAsync();
        var uid = await db.Technicians.Where(t => t.Id == fld.Tech.Id).Select(t => t.UserId).FirstAsync();

        var svc = new ReminderService(db, Cfg());
        Assert.True(await svc.RunOnceAsync(now, default) >= 1);
        await svc.RunOnceAsync(now.AddMinutes(1), default);
        Assert.Equal(1, await db.Notifications.CountAsync(n => n.UserId == uid && n.Kind == "reminder.job_start"));

        var list = await Kit.Json(await fld.Tech.Client.GetAsync("/notifications?unread=true"));
        Assert.Contains(list.EnumerateArray(), n => n.GetProperty("kind").GetString() == "reminder.job_start");
        var marked = await Kit.Json(await fld.Tech.Client.PostAsync("/notifications/read-all", null));
        Assert.True(marked.GetProperty("marked").GetInt32() >= 1);
        Assert.Empty((await Kit.Json(await fld.Tech.Client.GetAsync("/notifications?unread=true"))).EnumerateArray());
    }

    [Fact]
    public async Task Overdue_review_and_unpaid_payable_reminders_go_to_the_people_who_can_act()
    {
        var fld = await k.SubmittedJobAsync(); var co = fld.Co;
        using var scope = f.Services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<AppDbContext>();
        var svc = new ReminderService(db, Cfg(("Reminders:ReviewHours", "24")));
        await svc.RunOnceAsync(DateTime.UtcNow, default);                        // just submitted: nothing overdue
        Assert.DoesNotContain(await db.Notifications.Where(n => n.Kind == "reminder.review_waiting").ToListAsync(), n => n.CompanyId == co.Id);
        await svc.RunOnceAsync(DateTime.UtcNow.AddHours(25), default);
        var notified = await db.Notifications.Where(n => n.Kind == "reminder.review_waiting" && n.CompanyId == co.Id).ToListAsync();
        Assert.NotEmpty(notified);
        var dispatcherOnly = await (from m in db.Memberships join mr in db.MembershipRoles on m.Id equals mr.MembershipId where m.CompanyId == co.Id && mr.RoleCode == "dispatcher" select m.UserId).ToListAsync();
        Assert.DoesNotContain(notified, n => dispatcherOnly.Contains(n.UserId));   // dispatchers cannot review, so they are not nagged
    }

    [Fact]
    public async Task Job_and_technician_reports_are_scoped_to_the_company_and_to_report_readers()
    {
        var fld = await k.CompletedJobAsync(); var co = fld.Co;
        var j = await Kit.Json(await co.Dispatcher.GetAsync($"/companies/{co.Id}/reports/jobs"));
        Assert.True(j.GetProperty("total").GetInt32() >= 1);
        Assert.True(j.GetProperty("byStatus").GetProperty("Completed").GetInt32() >= 1);
        Assert.True(j.GetProperty("offers").GetProperty("accepted").GetInt32() >= 1);
        Assert.True(j.GetProperty("avgHoursToComplete").GetDouble() >= 0);

        var t = await Kit.Json(await co.Supervisor.GetAsync($"/companies/{co.Id}/reports/technicians"));
        var mine = t.GetProperty("technicians").EnumerateArray().Single(x => x.GetProperty("technicianId").GetGuid() == fld.Tech.Id);
        Assert.Equal(1, mine.GetProperty("completed").GetInt32());
        Assert.True(mine.GetProperty("scheduledHours").GetDouble() >= 2);
        Assert.True(mine.GetProperty("utilization").GetDouble() is >= 0 and <= 1);

        var other = await k.NewCompanyAsync();
        Assert.Equal(HttpStatusCode.NotFound, (await other.Owner.GetAsync($"/companies/{co.Id}/reports/jobs")).StatusCode);
        Assert.Equal(HttpStatusCode.NotFound, (await fld.Tech.Client.GetAsync($"/companies/{co.Id}/reports/jobs")).StatusCode);
        var otherJobs = await Kit.Json(await other.Owner.GetAsync($"/companies/{other.Id}/reports/jobs"));
        Assert.Equal(0, otherJobs.GetProperty("total").GetInt32());   // nothing leaks across tenants
    }

    [Fact]
    public async Task Finance_report_keeps_currencies_apart_distinguishes_statuses_and_traces_to_source_records()
    {
        var fld = await k.CompletedJobAsync(); var co = fld.Co;
        var fin = await fk.FinanceUserAsync(co);
        await fk.TermsAsync(co, fld.JobId, "company", 100m, 60m, 4m);
        var iid = Kit.Id(await Kit.Json(await fin.PostAsJsonAsync($"/companies/{co.Id}/jobs/{fld.JobId}/invoice", new { })));
        var p1 = await fk.InitiateAsync(fin, co.Id, new { invoiceId = iid, method = "cash", amount = 30m });
        (await co.Owner.PostAsJsonAsync($"/companies/{co.Id}/payments/{p1}/confirm", new { acknowledgedBy = "Amina" })).EnsureSuccessStatusCode();
        var p2 = await fk.InitiateAsync(fin, co.Id, new { invoiceId = iid, method = "bank", amount = 20m, providerRef = "B-9" });
        (await fin.PostAsJsonAsync($"/companies/{co.Id}/payments/{p2}/fail", new { note = "Bank rejected" })).EnsureSuccessStatusCode();

        Assert.Equal(HttpStatusCode.Forbidden, (await co.Dispatcher.GetAsync($"/companies/{co.Id}/reports/finance")).StatusCode);   // report.read is not finance.read
        var r = await Kit.Json(await fin.GetAsync($"/companies/{co.Id}/reports/finance"));
        var usd = r.GetProperty("currencies").EnumerateArray().Single(x => x.GetProperty("currency").GetString() == "USD");
        var rec = usd.GetProperty("receivables");
        Assert.Equal(100m, rec.GetProperty("invoiced").GetDecimal()); Assert.Equal(30m, rec.GetProperty("collected").GetDecimal()); Assert.Equal(70m, rec.GetProperty("outstanding").GetDecimal());
        Assert.Equal(60m, usd.GetProperty("technicianPayables").GetProperty("accrued").GetDecimal());
        Assert.Equal(4m, usd.GetProperty("platformFees").GetProperty("accrued").GetDecimal());
        Assert.Equal(1, usd.GetProperty("paymentsByStatus").GetProperty("Failed").GetProperty("count").GetInt32());   // failed money is reported, not counted as collected
        Assert.Equal(30m, usd.GetProperty("unreconciled").GetProperty("amount").GetDecimal());
        Assert.Contains(rec.GetProperty("sources").GetProperty("invoices").EnumerateArray(), x => x.GetGuid() == iid);     // traceable
        Assert.Contains(rec.GetProperty("sources").GetProperty("payments").EnumerateArray(), x => x.GetGuid() == p1);
    }

    [Fact]
    public async Task Platform_overview_is_for_platform_staff_only()
    {
        var (admin, _) = await f.UserAsync("platform_admin");
        var (owner, _) = await f.UserAsync();
        await f.CreateCompanyAsync(owner);
        Assert.Equal(HttpStatusCode.Forbidden, (await owner.GetAsync("/platform/overview")).StatusCode);
        var o = await Kit.Json(await admin.GetAsync("/platform/overview"));
        Assert.True(o.GetProperty("companies").GetProperty("byVerification").GetProperty("Pending").GetInt32() >= 1);
        Assert.True(o.GetProperty("verificationQueues").GetProperty("companies").GetInt32() >= 1);
        Assert.True(o.TryGetProperty("notificationQueue", out _));
    }
}
