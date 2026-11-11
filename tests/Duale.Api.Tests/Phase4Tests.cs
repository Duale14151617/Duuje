using System.Net;
using System.Net.Http.Json;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Duale.Api.Data;
using Duale.Api.Domain;
using Duale.Api.Services;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
namespace Duale.Api.Tests;

public class Phase4UnitTests
{
    [Fact]
    public void Money_accepts_only_positive_amounts_with_at_most_four_decimals()
    {
        Assert.True(Money.Valid(0.0001m)); Assert.True(Money.Valid(1234.5678m));
        Assert.False(Money.Valid(0m)); Assert.False(Money.Valid(-1m)); Assert.False(Money.Valid(1.00001m)); Assert.False(Money.Valid(1_000_000_000_000m));
        Assert.True(Money.ValidOrZero(0m));
    }

    [Fact]
    public void Settlement_moves_from_open_to_settled_only_when_paid_in_full_and_reconciled()
    {
        PaymentRecord P(decimal a, PaymentStatus s, bool rec = false) => new() { Amount = a, Status = s, Reconciled = rec };
        Assert.Equal("Open", FinanceMath.Settle(100, []).State);
        Assert.Equal("PaymentInitiated", FinanceMath.Settle(100, [P(100, PaymentStatus.Initiated)]).State);
        Assert.Equal("PartiallyPaid", FinanceMath.Settle(100, [P(40, PaymentStatus.Confirmed)]).State);
        Assert.Equal("Paid", FinanceMath.Settle(100, [P(60, PaymentStatus.Confirmed, true), P(40, PaymentStatus.Confirmed)]).State);
        Assert.Equal("Settled", FinanceMath.Settle(100, [P(60, PaymentStatus.Confirmed, true), P(40, PaymentStatus.Confirmed, true)]).State);
        Assert.Equal("Open", FinanceMath.Settle(100, [P(100, PaymentStatus.Reversed), P(100, PaymentStatus.Failed)]).State);   // reversed and failed money does not count
    }

    [Fact]
    public void Ledger_rejects_unbalanced_and_malformed_postings()
    {
        var opts = new DbContextOptionsBuilder<AppDbContext>().UseSqlite("DataSource=:memory:").Options;
        using var db = new AppDbContext(opts);
        Assert.Throws<InvalidOperationException>(() => Ledger.Post(db, Guid.NewGuid(), "t1", "USD", "x", "1", null, new Line("1000", 10, 0), new Line("4000", 0, 9)));
        Assert.Throws<InvalidOperationException>(() => Ledger.Post(db, Guid.NewGuid(), "t2", "USD", "x", "1", null, new Line("1000", 10, 0)));
        Assert.Throws<InvalidOperationException>(() => Ledger.Post(db, Guid.NewGuid(), "t3", "USD", "x", "1", null, new Line("1000", 10, 10), new Line("4000", 0, 0)));
        Ledger.Post(db, Guid.NewGuid(), "t4", "USD", "x", "1", null, new Line("1000", 10, 0), new Line("4000", 0, 10));
        Assert.Equal(2, db.Ledger.Local.Count);
    }
}

public class Phase4Tests(ApiFactory f) : IClassFixture<ApiFactory>
{
    readonly Kit k = new(f);
    FinKit fk => new(f, k);
    static string C(Guid id) => $"/companies/{id}";

    [Fact]
    public async Task Terms_need_a_second_person_and_the_right_permissions()
    {
        var co = await k.NewCompanyAsync();
        var job = await k.NewJobAsync(co);
        var url = $"{C(co.Id)}/jobs/{job}/financial-terms";
        var terms = new { currency = "USD", customerCharge = 100m, technicianCompensation = 60m, platformFee = 5m, payerType = "company" };

        Assert.Equal(HttpStatusCode.BadRequest, (await co.Dispatcher.PostAsJsonAsync(url, new { currency = "USD", customerCharge = 100m, technicianCompensation = 1.00001m, payerType = "company" })).StatusCode);   // more than 4 decimals
        Assert.Equal(HttpStatusCode.BadRequest, (await co.Dispatcher.PostAsJsonAsync(url, new { currency = "EUR", customerCharge = 100m, technicianCompensation = 60m })).StatusCode);   // not an allowed currency
        var tid = Kit.Id(await Kit.Json(await co.Dispatcher.PostAsJsonAsync(url, terms)));

        // a dispatcher can propose but not approve; the supervisor cannot even propose
        Assert.Equal(HttpStatusCode.Forbidden, (await co.Dispatcher.PostAsJsonAsync($"{url}/{tid}/approve", new { })).StatusCode);
        Assert.Equal(HttpStatusCode.Forbidden, (await co.Supervisor.PostAsJsonAsync(url, terms)).StatusCode);
        (await co.Owner.PostAsJsonAsync($"{url}/{tid}/approve", new { })).EnsureSuccessStatusCode();
        Assert.Equal(HttpStatusCode.Conflict, (await co.Owner.PostAsJsonAsync($"{url}/{tid}/approve", new { })).StatusCode);   // already approved

        // the owner may propose, but not approve their own proposal
        var own = Kit.Id(await Kit.Json(await co.Owner.PostAsJsonAsync(url, terms)));
        Assert.Equal(HttpStatusCode.Forbidden, (await co.Owner.PostAsJsonAsync($"{url}/{own}/approve", new { })).StatusCode);
    }

    [Fact]
    public async Task Company_paid_flow_from_completion_to_settled_with_separated_duties_and_a_balanced_ledger()
    {
        var fld = await k.SubmittedJobAsync(); var co = fld.Co;
        var fin = await fk.FinanceUserAsync(co);
        await fk.TermsAsync(co, fld.JobId, "company", 100m, 60m, 5m);
        (await fk.ReviewApproveAsync(co, fld.JobId)).EnsureSuccessStatusCode();   // completion starts the finance workflow

        var pb = await fk.PayableForJobAsync(fin, co.Id, fld.JobId);
        var pid = Kit.Id(pb);
        Assert.Equal("Accrued", pb.GetProperty("status").GetString());
        Assert.Equal(60m, pb.GetProperty("amount").GetDecimal());

        // cannot pay an unapproved payable; the technician cannot confirm a company payment
        Assert.Equal(HttpStatusCode.Conflict, (await co.Owner.PostAsJsonAsync($"{C(co.Id)}/payments", new { payableId = pid, method = "bank", amount = 60m })).StatusCode);
        Assert.Equal(HttpStatusCode.Conflict, (await fld.Tech.Client.PostAsJsonAsync($"/technicians/me/payables/{pid}/acknowledge", new { amount = 60m })).StatusCode);
        (await fin.PostAsync($"{C(co.Id)}/payables/{pid}/approve", null)).EnsureSuccessStatusCode();

        var payId = await fk.InitiateAsync(co.Owner, co.Id, new { payableId = pid, method = "bank", amount = 40m, providerRef = "BANK-1" });
        Assert.Equal(HttpStatusCode.Conflict, (await co.Owner.PostAsJsonAsync($"{C(co.Id)}/payments", new { payableId = pid, method = "bank", amount = 30m })).StatusCode);   // 40 + 30 > 60
        Assert.Equal(HttpStatusCode.Conflict, (await co.Owner.PostAsJsonAsync($"{C(co.Id)}/payments", new { payableId = pid, method = "bank", amount = 20m, providerRef = "BANK-1" })).StatusCode);   // reference already used
        Assert.Equal(HttpStatusCode.Conflict, (await co.Owner.PostAsJsonAsync($"{C(co.Id)}/payments", new { payableId = pid, method = "bank", amount = 20m, currency = "SOS" })).StatusCode);   // currency mismatch

        // initiation and confirmation are different people; confirmation and reconciliation too
        Assert.Equal(HttpStatusCode.Forbidden, (await co.Owner.PostAsJsonAsync($"{C(co.Id)}/payments/{payId}/confirm", new { })).StatusCode);
        (await fin.PostAsJsonAsync($"{C(co.Id)}/payments/{payId}/confirm", new { })).EnsureSuccessStatusCode();
        Assert.Equal(HttpStatusCode.Forbidden, (await fin.PostAsJsonAsync($"{C(co.Id)}/payments/{payId}/reconcile", new { })).StatusCode);
        (await co.Owner.PostAsJsonAsync($"{C(co.Id)}/payments/{payId}/reconcile", new { })).EnsureSuccessStatusCode();

        var second = await fk.InitiateAsync(co.Owner, co.Id, new { payableId = pid, method = "bank", amount = 20m, providerRef = "BANK-2" });
        (await fin.PostAsJsonAsync($"{C(co.Id)}/payments/{second}/confirm", new { })).EnsureSuccessStatusCode();
        Assert.Equal("Paid", (await fk.PayableForJobAsync(fin, co.Id, fld.JobId)).GetProperty("settlement").GetString());   // paid, but not yet reconciled
        (await co.Owner.PostAsJsonAsync($"{C(co.Id)}/payments/{second}/reconcile", new { })).EnsureSuccessStatusCode();
        Assert.Equal("Settled", (await fk.PayableForJobAsync(fin, co.Id, fld.JobId)).GetProperty("settlement").GetString());

        // technician sees the confirmed payments but nothing about other people's
        var mine = await Kit.Json(await fld.Tech.Client.GetAsync("/technicians/me/payables"));
        Assert.Equal(2, mine.EnumerateArray().Single().GetProperty("payments").GetArrayLength());

        // ledger: balanced, and the technician payable account nets to zero once fully paid
        var rec = await Kit.Json(await fin.GetAsync($"{C(co.Id)}/finance/reconciliation"));
        Assert.All(rec.GetProperty("balanceCheck").EnumerateArray(), b => Assert.True(b.GetProperty("balanced").GetBoolean()));
        var ap = rec.GetProperty("trialBalance").EnumerateArray().Single(x => x.GetProperty("account").GetString() == Acct.TechPayable);
        Assert.Equal(60m, ap.GetProperty("debit").GetDecimal()); Assert.Equal(60m, ap.GetProperty("credit").GetDecimal());
        Assert.Empty(rec.GetProperty("awaitingReconciliation").EnumerateArray());
    }

    [Fact]
    public async Task Terms_approved_after_completion_still_create_the_payable_and_a_platform_fee_that_platform_finance_settles()
    {
        var fld = await k.CompletedJobAsync(); var co = fld.Co;
        var fin = await fk.FinanceUserAsync(co);
        Assert.Empty((await Kit.Json(await fin.GetAsync($"{C(co.Id)}/payables"))).EnumerateArray());   // nothing without terms
        await fk.TermsAsync(co, fld.JobId, "company", 100m, 60m, 7.5m);
        Assert.Equal(60m, (await fk.PayableForJobAsync(fin, co.Id, fld.JobId)).GetProperty("amount").GetDecimal());

        // changing terms once obligations exist is refused
        Assert.Equal(HttpStatusCode.Conflict, (await co.Dispatcher.PostAsJsonAsync($"{C(co.Id)}/jobs/{fld.JobId}/financial-terms", new { currency = "USD", customerCharge = 100m, technicianCompensation = 70m })).StatusCode);

        var (pf, _) = await f.UserAsync("platform_finance");
        var fees = await Kit.Json(await pf.GetAsync("/platform/fees?status=Accrued"));
        var fee = fees.EnumerateArray().Single(x => x.GetProperty("companyId").GetGuid() == co.Id);
        Assert.Equal(7.5m, fee.GetProperty("amount").GetDecimal());
        Assert.Equal(HttpStatusCode.Forbidden, (await co.Owner.GetAsync("/platform/fees")).StatusCode);
        Assert.Equal(HttpStatusCode.Forbidden, (await co.Admin.GetAsync("/platform/fees")).StatusCode);   // platform admin is not platform finance
        var fid = Kit.Id(fee);
        Assert.Equal(HttpStatusCode.BadRequest, (await pf.PostAsJsonAsync($"/platform/fees/{fid}/decision", new { decision = "waive" })).StatusCode);   // waiving needs a note
        (await pf.PostAsJsonAsync($"/platform/fees/{fid}/decision", new { decision = "settle" })).EnsureSuccessStatusCode();
        Assert.Equal(HttpStatusCode.Conflict, (await pf.PostAsJsonAsync($"/platform/fees/{fid}/decision", new { decision = "settle" })).StatusCode);
    }

    [Fact]
    public async Task Direct_customer_payment_is_self_reported_then_reconciled_and_never_touches_the_company_books()
    {
        var (fld, fin, pid) = await fk.ApprovedPayableAsync("customer", 60m, 0m);
        var co = fld.Co; var tech = fld.Tech.Client;

        var mine = (await Kit.Json(await tech.GetAsync("/technicians/me/payables"))).EnumerateArray().Single();
        Assert.Equal("customer", mine.GetProperty("payerType").GetString());
        Assert.Equal("Approved", mine.GetProperty("status").GetString());

        Assert.Equal(HttpStatusCode.Conflict, (await tech.PostAsJsonAsync($"/technicians/me/payables/{pid}/acknowledge", new { amount = 70m })).StatusCode);   // more than agreed
        var ack = await Kit.Json(await tech.PostAsJsonAsync($"/technicians/me/payables/{pid}/acknowledge", new { amount = 60m, method = "cash" }));
        Assert.False(ack.GetProperty("verified").GetBoolean());          // a self-reported cash record is never "verified"
        Assert.Equal("Confirmed", ack.GetProperty("status").GetString());
        Assert.Equal(HttpStatusCode.Conflict, (await tech.PostAsJsonAsync($"/technicians/me/payables/{pid}/acknowledge", new { amount = 1m })).StatusCode);   // fully paid already

        var rec = await Kit.Json(await fin.GetAsync($"{C(co.Id)}/finance/reconciliation"));
        Assert.Single(rec.GetProperty("selfReported").EnumerateArray());
        var payId = Kit.Id(ack);
        (await fin.PostAsJsonAsync($"{C(co.Id)}/payments/{payId}/reconcile", new { note = "Customer confirmed by phone" })).EnsureSuccessStatusCode();
        Assert.Equal("Settled", (await fk.PayableForJobAsync(fin, co.Id, fld.JobId)).GetProperty("settlement").GetString());

        var ledger = await Kit.Json(await fin.GetAsync($"{C(co.Id)}/ledger"));
        Assert.DoesNotContain(ledger.EnumerateArray(), e => e.GetProperty("txnKey").GetString()!.StartsWith("pay-confirm"));
        Assert.DoesNotContain(ledger.EnumerateArray(), e => e.GetProperty("txnKey").GetString()!.StartsWith("payable-accrue"));
    }

    [Fact]
    public async Task Invoice_collection_and_refund_follow_approval_and_never_exceed_what_was_collected()
    {
        var fld = await k.CompletedJobAsync(); var co = fld.Co;
        var fin = await fk.FinanceUserAsync(co);
        await fk.TermsAsync(co, fld.JobId, "company", 100m, 60m, 0m);

        var inv = $"{C(co.Id)}/jobs/{fld.JobId}/invoice";
        Assert.Equal(HttpStatusCode.Forbidden, (await co.Dispatcher.PostAsJsonAsync(inv, new { })).StatusCode);
        Assert.Equal(HttpStatusCode.Conflict, (await fin.PostAsJsonAsync(inv, new { lines = new[] { new { description = "Labour", quantity = 1m, unitPrice = 90m } } })).StatusCode);   // must equal the approved charge
        var iid = Kit.Id(await Kit.Json(await fin.PostAsJsonAsync(inv, new { lines = new[] { new { description = "Labour", quantity = 2m, unitPrice = 30m }, new { description = "Parts", quantity = 1m, unitPrice = 40m } } })));
        Assert.Equal(HttpStatusCode.Conflict, (await fin.PostAsJsonAsync(inv, new { })).StatusCode);   // one live invoice per job

        // cash needs the name of whoever acknowledged it
        var pay = await fk.InitiateAsync(fin, co.Id, new { invoiceId = iid, method = "cash", amount = 100m });
        Assert.Equal(HttpStatusCode.BadRequest, (await co.Owner.PostAsJsonAsync($"{C(co.Id)}/payments/{pay}/confirm", new { })).StatusCode);
        (await co.Owner.PostAsJsonAsync($"{C(co.Id)}/payments/{pay}/confirm", new { acknowledgedBy = "Amina (customer)" })).EnsureSuccessStatusCode();
        var detail = await Kit.Json(await fin.GetAsync($"{C(co.Id)}/invoices/{iid}"));
        Assert.Equal(0m, detail.GetProperty("invoice").GetProperty("outstanding").GetDecimal());
        Assert.False(detail.GetProperty("payments")[0].GetProperty("verified").GetBoolean());
        Assert.Equal(HttpStatusCode.Forbidden, (await fin.PostAsJsonAsync($"{C(co.Id)}/invoices/{iid}/void", new { reason = "mistake" })).StatusCode);   // finance officers cannot void (finance.adjust is owner-only)
        Assert.Equal(HttpStatusCode.Conflict, (await co.Owner.PostAsJsonAsync($"{C(co.Id)}/invoices/{iid}/void", new { reason = "mistake" })).StatusCode);   // and nobody can while money is collected

        // refunds
        Assert.Equal(HttpStatusCode.Conflict, (await fin.PostAsJsonAsync($"{C(co.Id)}/refunds", new { invoiceId = iid, amount = 150m, reason = "too much" })).StatusCode);
        var rf = Kit.Id(await Kit.Json(await fin.PostAsJsonAsync($"{C(co.Id)}/refunds", new { invoiceId = iid, amount = 40m, reason = "Part of the work was redone elsewhere" })));
        Assert.Equal(HttpStatusCode.Conflict, (await fin.PostAsJsonAsync($"{C(co.Id)}/refunds", new { invoiceId = iid, amount = 70m, reason = "more" })).StatusCode);   // 40 + 70 > 100
        Assert.Equal(HttpStatusCode.Conflict, (await co.Owner.PostAsJsonAsync($"{C(co.Id)}/payments", new { refundId = rf, method = "cash", amount = 40m })).StatusCode);   // not approved yet
        Assert.Equal(HttpStatusCode.Forbidden, (await fin.PostAsJsonAsync($"{C(co.Id)}/refunds/{rf}/decision", new { decision = "approve" })).StatusCode);   // finance cannot approve refunds
        (await co.Owner.PostAsJsonAsync($"{C(co.Id)}/refunds/{rf}/decision", new { decision = "approve" })).EnsureSuccessStatusCode();

        var own = Kit.Id(await Kit.Json(await co.Owner.PostAsJsonAsync($"{C(co.Id)}/refunds", new { invoiceId = iid, amount = 10m, reason = "goodwill" })));
        Assert.Equal(HttpStatusCode.Forbidden, (await co.Owner.PostAsJsonAsync($"{C(co.Id)}/refunds/{own}/decision", new { decision = "approve" })).StatusCode);   // not your own request

        var rpay = await fk.InitiateAsync(co.Owner, co.Id, new { refundId = rf, method = "cash", amount = 40m });
        (await fin.PostAsJsonAsync($"{C(co.Id)}/payments/{rpay}/confirm", new { acknowledgedBy = "Amina (customer)" })).EnsureSuccessStatusCode();
        var ledger = await Kit.Json(await fin.GetAsync($"{C(co.Id)}/finance/reconciliation"));
        var refunds = ledger.GetProperty("trialBalance").EnumerateArray().Single(x => x.GetProperty("account").GetString() == Acct.Refunds);
        Assert.Equal(40m, refunds.GetProperty("debit").GetDecimal());
        Assert.All(ledger.GetProperty("balanceCheck").EnumerateArray(), b => Assert.True(b.GetProperty("balanced").GetBoolean()));
    }

    [Fact]
    public async Task Owner_can_void_an_unpaid_invoice_which_reverses_the_receivable_but_never_deletes_it()
    {
        var fld = await k.CompletedJobAsync(); var co = fld.Co;
        await fk.TermsAsync(co, fld.JobId, "company", 100m, 60m, 0m);
        var iid = Kit.Id(await Kit.Json(await co.Owner.PostAsJsonAsync($"{C(co.Id)}/jobs/{fld.JobId}/invoice", new { })));
        Assert.Equal(HttpStatusCode.BadRequest, (await co.Owner.PostAsJsonAsync($"{C(co.Id)}/invoices/{iid}/void", new { })).StatusCode);
        (await co.Owner.PostAsJsonAsync($"{C(co.Id)}/invoices/{iid}/void", new { reason = "Wrong customer" })).EnsureSuccessStatusCode();
        var rec = await Kit.Json(await co.Owner.GetAsync($"{C(co.Id)}/finance/reconciliation"));
        var ar = rec.GetProperty("trialBalance").EnumerateArray().Single(x => x.GetProperty("account").GetString() == Acct.Receivable);
        Assert.Equal(ar.GetProperty("debit").GetDecimal(), ar.GetProperty("credit").GetDecimal());   // reversed, not erased
        (await co.Owner.PostAsJsonAsync($"{C(co.Id)}/jobs/{fld.JobId}/invoice", new { })).EnsureSuccessStatusCode();   // a replacement can be issued
    }

    [Fact]
    public async Task Signed_provider_callback_confirms_once_and_duplicates_never_post_twice()
    {
        var fld = await k.CompletedJobAsync(); var co = fld.Co;
        var fin = await fk.FinanceUserAsync(co);
        await fk.TermsAsync(co, fld.JobId, "company", 100m, 60m, 0m);
        var iid = Kit.Id(await Kit.Json(await fin.PostAsJsonAsync($"{C(co.Id)}/jobs/{fld.JobId}/invoice", new { })));
        var init = await Kit.Json(await fin.PostAsJsonAsync($"{C(co.Id)}/payments", new { invoiceId = iid, method = "mobile_money", amount = 100m }));
        var reference = init.GetProperty("reference").GetString()!;
        var payId = Kit.Id(init);

        async Task<HttpResponseMessage> Send(object body, string? signWith = null)
        {
            var json = JsonSerializer.Serialize(body);
            var sig = Convert.ToHexString(HMACSHA256.HashData(Encoding.UTF8.GetBytes(signWith ?? ApiFactory.CallbackSecret), Encoding.UTF8.GetBytes(json))).ToLowerInvariant();
            var req = new HttpRequestMessage(HttpMethod.Post, "/payments/provider-callback") { Content = new StringContent(json, Encoding.UTF8, "application/json") };
            req.Headers.Add("X-Signature", sig);
            return await f.CreateClient().SendAsync(req);   // anonymous: the signature is the credential
        }
        var ok = new { reference, providerRef = "MM-77", status = "succeeded", amount = 100m, currency = "USD" };

        Assert.Equal(HttpStatusCode.Unauthorized, (await Send(ok, "wrong-secret-wrong-secret")).StatusCode);
        Assert.Equal(HttpStatusCode.Conflict, (await Send(new { reference, providerRef = "MM-77", status = "succeeded", amount = 90m, currency = "USD" })).StatusCode);   // amount mismatch is flagged, not posted
        Assert.Equal("Initiated", (await Kit.Json(await fin.GetAsync($"{C(co.Id)}/payments/{payId}"))).GetProperty("payment").GetProperty("status").GetString());

        Assert.Equal(HttpStatusCode.OK, (await Send(ok)).StatusCode);
        var again = await Kit.Json(await Send(ok));
        Assert.True(again.GetProperty("duplicate").GetBoolean());

        var view = await Kit.Json(await fin.GetAsync($"{C(co.Id)}/payments/{payId}"));
        Assert.True(view.GetProperty("payment").GetProperty("verified").GetBoolean());
        var events = view.GetProperty("history").EnumerateArray().Select(e => e.GetProperty("event").GetString()).ToList();
        Assert.Contains("callback_mismatch", events); Assert.Contains("callback_duplicate", events);
        var ledger = await Kit.Json(await fin.GetAsync($"{C(co.Id)}/ledger?take=500"));
        Assert.Equal(2, ledger.EnumerateArray().Count(e => e.GetProperty("txnKey").GetString() == $"pay-confirm:{payId}"));   // one balanced posting, once

        // a confirmed payment can be reversed by someone else, which posts the mirror image
        Assert.Equal(HttpStatusCode.Forbidden, (await fin.PostAsJsonAsync($"{C(co.Id)}/payments/{payId}/reverse", new { reason = "bounced" })).StatusCode);   // finance.adjust is owner-only
        (await co.Owner.PostAsJsonAsync($"{C(co.Id)}/payments/{payId}/reverse", new { reason = "Provider reported a chargeback" })).EnsureSuccessStatusCode();
        var after = await Kit.Json(await fin.GetAsync($"{C(co.Id)}/ledger?take=500"));
        Assert.Equal(2, after.EnumerateArray().Count(e => e.GetProperty("txnKey").GetString() == $"pay-reverse:{payId}"));
        Assert.Equal("Open", (await Kit.Json(await fin.GetAsync($"{C(co.Id)}/invoices/{iid}"))).GetProperty("invoice").GetProperty("settlement").GetString());
    }

    [Fact]
    public async Task Open_dispute_blocks_payout_until_someone_else_decides_it()
    {
        var (fld, fin, pid) = await fk.ApprovedPayableAsync("company", 60m, 0m);
        var co = fld.Co;
        var dsp = Kit.Id(await Kit.Json(await fld.Tech.Client.PostAsJsonAsync($"/technicians/me/payables/{pid}/dispute", new { description = "Hours were under-counted" })));
        Assert.Equal(HttpStatusCode.Conflict, (await co.Owner.PostAsJsonAsync($"{C(co.Id)}/payments", new { payableId = pid, method = "bank", amount = 60m })).StatusCode);
        Assert.True((await fk.PayableForJobAsync(fin, co.Id, fld.JobId)).GetProperty("disputed").GetBoolean());
        Assert.Equal(HttpStatusCode.BadRequest, (await co.Owner.PostAsJsonAsync($"{C(co.Id)}/disputes/{dsp}/decision", new { outcome = "rejected" })).StatusCode);   // resolution required
        (await co.Owner.PostAsJsonAsync($"{C(co.Id)}/disputes/{dsp}/decision", new { outcome = "rejected", resolution = "Timesheet matches the work report v1." })).EnsureSuccessStatusCode();
        (await co.Owner.PostAsJsonAsync($"{C(co.Id)}/payments", new { payableId = pid, method = "bank", amount = 60m })).EnsureSuccessStatusCode();
    }

    [Fact]
    public async Task Tenants_technicians_and_roles_are_isolated()
    {
        var (fld, fin, pid) = await fk.ApprovedPayableAsync("company", 60m, 0m);
        var co1 = fld.Co;
        var pay = await fk.InitiateAsync(co1.Owner, co1.Id, new { payableId = pid, method = "bank", amount = 10m });
        var co2 = await k.NewCompanyAsync();
        var other = await k.NewTechnicianAsync(co2);

        // another company cannot see or use company 1's records, even with valid ids
        Assert.Equal(HttpStatusCode.NotFound, (await co2.Owner.GetAsync($"{C(co1.Id)}/payables")).StatusCode);
        Assert.Equal(HttpStatusCode.NotFound, (await co2.Owner.GetAsync($"{C(co1.Id)}/ledger")).StatusCode);
        Assert.Equal(HttpStatusCode.NotFound, (await co2.Owner.GetAsync($"{C(co2.Id)}/payments/{pay}")).StatusCode);
        Assert.Equal(HttpStatusCode.NotFound, (await co2.Owner.PostAsJsonAsync($"{C(co2.Id)}/payments", new { payableId = pid, method = "bank", amount = 10m })).StatusCode);
        Assert.Equal(HttpStatusCode.NotFound, (await co2.Owner.PostAsJsonAsync($"{C(co2.Id)}/payments/{pay}/confirm", new { providerRef = "X" })).StatusCode);
        Assert.Equal(HttpStatusCode.NotFound, (await co2.Owner.PostAsJsonAsync($"{C(co2.Id)}/payables/{pid}/approve", new { })).StatusCode);

        // another technician cannot see, acknowledge or dispute this technician's payable
        Assert.Empty((await Kit.Json(await other.Client.GetAsync("/technicians/me/payables"))).EnumerateArray());
        Assert.Equal(HttpStatusCode.NotFound, (await other.Client.PostAsJsonAsync($"/technicians/me/payables/{pid}/acknowledge", new { amount = 1m })).StatusCode);
        Assert.Equal(HttpStatusCode.NotFound, (await other.Client.PostAsJsonAsync($"/technicians/me/payables/{pid}/dispute", new { description = "x" })).StatusCode);

        // inside company 1, roles without the permission are refused
        Assert.Equal(HttpStatusCode.Forbidden, (await co1.Dispatcher.GetAsync($"{C(co1.Id)}/payables")).StatusCode);
        Assert.Equal(HttpStatusCode.Forbidden, (await co1.Supervisor.PostAsJsonAsync($"{C(co1.Id)}/payments", new { payableId = pid, method = "bank", amount = 1m })).StatusCode);
        Assert.Equal(HttpStatusCode.Unauthorized, (await f.CreateClient().GetAsync($"{C(co1.Id)}/payables")).StatusCode);
        Assert.Equal(HttpStatusCode.OK, (await fin.GetAsync($"{C(co1.Id)}/payables")).StatusCode);
    }

    [Fact]
    public async Task Ledger_entries_cannot_be_changed_and_the_same_posting_cannot_be_made_twice()
    {
        var fld = await k.CompletedJobAsync(); var co = fld.Co;
        await fk.TermsAsync(co, fld.JobId, "company", 100m, 60m, 0m);
        (await co.Owner.PostAsJsonAsync($"{C(co.Id)}/jobs/{fld.JobId}/invoice", new { })).EnsureSuccessStatusCode();

        using var scope = f.Services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<AppDbContext>();
        var entry = await db.Ledger.FirstAsync(e => e.CompanyId == co.Id);
        entry.Debit = 1m;
        await Assert.ThrowsAsync<InvalidOperationException>(() => db.SaveChangesAsync());
        db.ChangeTracker.Clear();

        Ledger.Post(db, co.Id, entry.TxnKey, "USD", "x", "1", null, new Line("1000", 5, 0), new Line("4000", 0, 5));   // same key again
        await Assert.ThrowsAnyAsync<DbUpdateException>(() => db.SaveChangesAsync());
    }
}
