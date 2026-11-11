using System.Net;
using System.Net.Http.Json;
using Duale.Api.Data;
using Duale.Api.Domain;
using Duale.Api.Services;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging.Abstractions;
namespace Duale.Api.Tests;

class FakePublisher(Func<OutboxMessage, bool> succeeds) : IOutboxPublisher
{
    public List<OutboxMessage> Seen { get; } = [];
    public Task PublishAsync(OutboxMessage m, CancellationToken ct)
    {
        Seen.Add(m);
        return succeeds(m) ? Task.CompletedTask : throw new InvalidOperationException("consumer down");
    }
}

public class Phase7Tests(ApiFactory f) : IClassFixture<ApiFactory>
{
    readonly Kit k = new(f);
    FinKit fk => new(f, k);
    static string C(Guid id) => $"/companies/{id}";
    static IConfiguration Cfg(params (string, string)[] kv) => new ConfigurationBuilder().AddInMemoryCollection(kv.ToDictionary(x => x.Item1, x => (string?)x.Item2)).Build();

    // ---------- Payable cancellation ----------
    [Fact]
    public async Task Owner_can_cancel_an_approved_payable_and_the_ledger_accrual_is_reversed()
    {
        var (fld, fin, pid) = await fk.ApprovedPayableAsync();
        var co = fld.Co;
        Assert.Equal(HttpStatusCode.Forbidden, (await fin.PostAsJsonAsync($"{C(co.Id)}/payables/{pid}/cancel", new { reason = "wrong" })).StatusCode);   // finance officer lacks finance.adjust
        Assert.Equal(HttpStatusCode.BadRequest, (await co.Owner.PostAsJsonAsync($"{C(co.Id)}/payables/{pid}/cancel", new { reason = " " })).StatusCode);
        var r = await Kit.Json(await co.Owner.PostAsJsonAsync($"{C(co.Id)}/payables/{pid}/cancel", new { reason = "Entered against the wrong technician" }));
        Assert.Equal("Cancelled", r.GetProperty("status").GetString());
        Assert.True(r.GetProperty("ledgerReversed").GetBoolean());
        Assert.Equal(HttpStatusCode.Conflict, (await co.Owner.PostAsJsonAsync($"{C(co.Id)}/payables/{pid}/cancel", new { reason = "again" })).StatusCode);

        using var scope = f.Services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<AppDbContext>();
        var rev = await db.Ledger.Where(e => e.CompanyId == co.Id && e.TxnKey == $"payable-cancel:{pid}").ToListAsync();
        Assert.Equal(2, rev.Count);
        Assert.Equal(rev.Sum(e => e.Debit), rev.Sum(e => e.Credit));
        Assert.Equal(1, await db.AuditEvents.CountAsync(a => a.Action == "finance.payable_cancelled" && a.ResourceId == pid.ToString()));
        Assert.Equal(1, await db.OutboxEvents.CountAsync(o => o.Type == "finance.payable_cancelled" && o.AggregateId == pid.ToString()));
    }

    [Fact]
    public async Task A_payable_with_a_live_payment_or_another_companys_owner_cannot_cancel()
    {
        var (fld, _, pid) = await fk.ApprovedPayableAsync();
        var co = fld.Co;
        await fk.InitiateAsync(co.Owner, co.Id, new { payableId = pid, method = "bank", amount = 20m, providerRef = "P7-" + Guid.NewGuid().ToString("N")[..8] });
        Assert.Equal(HttpStatusCode.Conflict, (await co.Owner.PostAsJsonAsync($"{C(co.Id)}/payables/{pid}/cancel", new { reason = "too late" })).StatusCode);

        var other = await k.NewCompanyAsync();
        Assert.Equal(HttpStatusCode.NotFound, (await other.Owner.PostAsJsonAsync($"{C(other.Id)}/payables/{pid}/cancel", new { reason = "x" })).StatusCode);   // id substitution inside own company
        Assert.Equal(HttpStatusCode.NotFound, (await other.Owner.PostAsJsonAsync($"{C(co.Id)}/payables/{pid}/cancel", new { reason = "x" })).StatusCode);   // foreign company
    }

    // ---------- Platform subscriptions ----------
    [Fact]
    public async Task Platform_finance_records_subscriptions_without_overlap_and_the_company_can_read_its_own()
    {
        var co = await k.NewCompanyAsync();
        var (pf, _) = await f.UserAsync("platform_finance");
        var today = DateOnly.FromDateTime(DateTime.UtcNow);
        var body = new { planLabel = "Pilot", amount = 0m, currency = "USD", periodStart = today.AddDays(-1), periodEnd = today.AddDays(29) };
        var created = await Kit.Json(await pf.PostAsJsonAsync($"/platform/companies/{co.Id}/subscriptions", body));
        var sid = Kit.Id(created);

        Assert.Equal(HttpStatusCode.Conflict, (await pf.PostAsJsonAsync($"/platform/companies/{co.Id}/subscriptions", body)).StatusCode);   // overlaps
        Assert.Equal(HttpStatusCode.BadRequest, (await pf.PostAsJsonAsync($"/platform/companies/{co.Id}/subscriptions", new { planLabel = "x", amount = -1m, currency = "USD", periodStart = today, periodEnd = today })).StatusCode);
        Assert.Equal(HttpStatusCode.BadRequest, (await pf.PostAsJsonAsync($"/platform/companies/{co.Id}/subscriptions", new { planLabel = "x", amount = 1m, currency = "USD", periodStart = today, periodEnd = today.AddDays(-1) })).StatusCode);
        Assert.Equal(HttpStatusCode.BadRequest, (await pf.PostAsJsonAsync($"/platform/companies/{co.Id}/subscriptions", new { planLabel = "x", amount = 1m, currency = "XXX", periodStart = today, periodEnd = today })).StatusCode);

        var mine = await Kit.Json(await co.Owner.GetAsync($"{C(co.Id)}/subscription"));
        Assert.Equal(sid, mine.GetProperty("current").GetProperty("id").GetGuid());

        var other = await k.NewCompanyAsync();
        Assert.Equal(HttpStatusCode.NotFound, (await other.Owner.GetAsync($"{C(co.Id)}/subscription")).StatusCode);   // not a member of that company

        (await pf.PostAsJsonAsync($"/platform/subscriptions/{sid}/cancel", new { reason = "Company left" })).EnsureSuccessStatusCode();
        Assert.Equal(HttpStatusCode.Conflict, (await pf.PostAsJsonAsync($"/platform/subscriptions/{sid}/cancel", new { reason = "again" })).StatusCode);
        (await pf.PostAsJsonAsync($"/platform/companies/{co.Id}/subscriptions", body)).EnsureSuccessStatusCode();   // period is free again
    }

    [Fact]
    public async Task Only_platform_finance_can_manage_subscriptions()
    {
        var co = await k.NewCompanyAsync();
        var today = DateOnly.FromDateTime(DateTime.UtcNow);
        var body = new { planLabel = "Std", amount = 10m, currency = "USD", periodStart = today, periodEnd = today.AddDays(5) };
        Assert.Equal(HttpStatusCode.Forbidden, (await co.Admin.PostAsJsonAsync($"/platform/companies/{co.Id}/subscriptions", body)).StatusCode);   // platform_admin has no platform.finance
        Assert.Equal(HttpStatusCode.Forbidden, (await co.Owner.PostAsJsonAsync($"/platform/companies/{co.Id}/subscriptions", body)).StatusCode);   // company owner is not platform staff
        Assert.Equal(HttpStatusCode.Forbidden, (await co.Owner.GetAsync("/platform/subscriptions")).StatusCode);
    }

    // ---------- Integration accounts ----------
    [Fact]
    public async Task Integration_accounts_hold_secret_names_only_and_are_platform_admin_only()
    {
        var co = await k.NewCompanyAsync();
        var name = "Mail " + Guid.NewGuid().ToString("N")[..6];
        Assert.Equal(HttpStatusCode.Forbidden, (await co.Owner.PostAsJsonAsync("/platform/integrations", new { kind = "email", provider = "x", displayName = name })).StatusCode);
        Assert.Equal(HttpStatusCode.BadRequest, (await co.Admin.PostAsJsonAsync("/platform/integrations", new { kind = "fax", provider = "x", displayName = name })).StatusCode);
        Assert.Equal(HttpStatusCode.BadRequest, (await co.Admin.PostAsJsonAsync("/platform/integrations", new { kind = "email", provider = "x", displayName = name, secretRef = "sk_live abc 123 value with spaces" })).StatusCode);

        var created = await Kit.Json(await co.Admin.PostAsJsonAsync("/platform/integrations", new { kind = "email", provider = "ProviderX", displayName = name }));
        var aid = Kit.Id(created);
        Assert.Equal(HttpStatusCode.Conflict, (await co.Admin.PostAsJsonAsync("/platform/integrations", new { kind = "email", provider = "ProviderX", displayName = name })).StatusCode);   // unique
        Assert.Equal(HttpStatusCode.Conflict, (await co.Admin.PostAsJsonAsync($"/platform/integrations/{aid}/status", new { enabled = true })).StatusCode);   // needs a secretRef first

        var withSecret = await Kit.Json(await co.Admin.PostAsJsonAsync("/platform/integrations", new { kind = "storage", provider = "S3", displayName = name, secretRef = "Storage__AccessKey" }));
        var on = await Kit.Json(await co.Admin.PostAsJsonAsync($"/platform/integrations/{Kit.Id(withSecret)}/status", new { enabled = true }));
        Assert.Equal("Enabled", on.GetProperty("status").GetString());
    }

    // ---------- Outbox ----------
    [Fact]
    public async Task A_job_offer_writes_an_outbox_event_in_the_same_transaction()
    {
        var co = await k.NewCompanyAsync();
        var tech = await k.NewTechnicianAsync(co);
        var job = await k.NewJobAsync(co);
        await k.OfferAsync(co, job, tech);
        using var scope = f.Services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<AppDbContext>();
        var ev = await db.OutboxEvents.SingleAsync(o => o.Type == "job.offered" && o.AggregateId == job.ToString());
        Assert.Equal("Pending", ev.Status);
        Assert.Equal(co.Id, ev.CompanyId);
        Assert.DoesNotContain("phone", ev.Payload, StringComparison.OrdinalIgnoreCase);   // no customer data in events
    }

    [Fact]
    public async Task Dispatcher_publishes_retries_with_backoff_and_goes_dead_after_max_attempts()
    {
        using var scope = f.Services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<AppDbContext>();
        await db.Database.EnsureCreatedAsync();
        var marker = Guid.NewGuid().ToString();
        db.OutboxEvents.Add(new OutboxEvent { Type = "test.ok", AggregateType = "t", AggregateId = marker });
        db.OutboxEvents.Add(new OutboxEvent { Type = "test.fail", AggregateType = "t", AggregateId = marker });
        await db.SaveChangesAsync();

        // No publisher registered: nothing is consumed, nothing is marked published.
        var none = new OutboxDispatcher(db, [], Cfg(), NullLogger<OutboxDispatcher>.Instance);
        Assert.Equal(0, await none.RunOnceAsync(DateTime.UtcNow.AddMinutes(1), default));
        Assert.All(await db.OutboxEvents.Where(o => o.AggregateId == marker).ToListAsync(), o => Assert.Equal("Pending", o.Status));

        var pub = new FakePublisher(m => m.Type != "test.fail");
        var d = new OutboxDispatcher(db, [pub], Cfg(("Outbox:MaxAttempts", "2")), NullLogger<OutboxDispatcher>.Instance);
        var t0 = DateTime.UtcNow.AddMinutes(1);
        await d.RunOnceAsync(t0, default);
        Assert.Equal(2, pub.Seen.Count(m => m.AggregateId == marker));          // both were attempted once (other tests' events may be published too)
        var ok = await db.OutboxEvents.SingleAsync(o => o.AggregateId == marker && o.Type == "test.ok");
        var bad = await db.OutboxEvents.SingleAsync(o => o.AggregateId == marker && o.Type == "test.fail");
        Assert.Equal("Published", ok.Status);
        Assert.Equal("Pending", bad.Status); Assert.Equal(1, bad.Attempts); Assert.True(bad.NextAttemptAt > t0);

        var seenBefore = pub.Seen.Count;
        await d.RunOnceAsync(t0, default);                                  // not due yet: not attempted again
        Assert.Equal(seenBefore, pub.Seen.Count);

        await d.RunOnceAsync(t0.AddHours(2), default);                      // due: second failure reaches MaxAttempts
        await db.Entry(bad).ReloadAsync();
        Assert.Equal("Dead", bad.Status); Assert.Equal(2, bad.Attempts); Assert.Contains("consumer down", bad.LastError);
        Assert.Equal(1, pub.Seen.Count(m => m.Type == "test.ok"));          // the published event is never re-sent
    }

    [Fact]
    public async Task Backoff_grows_and_is_capped()
    {
        Assert.True(OutboxDispatcher.Backoff(1) < OutboxDispatcher.Backoff(3));
        Assert.Equal(TimeSpan.FromHours(1), OutboxDispatcher.Backoff(50));
        await Task.CompletedTask;
    }

    [Fact]
    public async Task Platform_oversight_can_list_and_retry_dead_events_but_companies_cannot()
    {
        var co = await k.NewCompanyAsync();
        Guid id;
        using (var scope = f.Services.CreateScope())
        {
            var db = scope.ServiceProvider.GetRequiredService<AppDbContext>();
            var ev = new OutboxEvent { Type = "test.dead", AggregateType = "t", AggregateId = "1", Status = "Dead", Attempts = 8, LastError = "boom" };
            db.OutboxEvents.Add(ev); await db.SaveChangesAsync(); id = ev.Id;
        }
        Assert.Equal(HttpStatusCode.Forbidden, (await co.Owner.GetAsync("/platform/outbox")).StatusCode);
        Assert.Equal(HttpStatusCode.Forbidden, (await co.Owner.PostAsync($"/platform/outbox/{id}/retry", null)).StatusCode);
        var list = await Kit.Json(await co.Admin.GetAsync("/platform/outbox?status=Dead"));
        Assert.Contains(list.EnumerateArray(), x => x.GetProperty("id").GetGuid() == id);
        Assert.DoesNotContain("payload", (await co.Admin.GetStringAsync("/platform/outbox?status=Dead")), StringComparison.OrdinalIgnoreCase);
        (await co.Admin.PostAsync($"/platform/outbox/{id}/retry", null)).EnsureSuccessStatusCode();
        Assert.Equal(HttpStatusCode.Conflict, (await co.Admin.PostAsync($"/platform/outbox/{id}/retry", null)).StatusCode);   // now Pending
    }
}
