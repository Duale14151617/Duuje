using System.Security.Claims;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Duale.Api.Auth;
using Duale.Api.Data;
using Duale.Api.Domain;
using Duale.Api.Services;
using Microsoft.EntityFrameworkCore;
using static Duale.Api.Endpoints;
using static Duale.Api.Phase2Endpoints;
namespace Duale.Api;

public record TermsReq(string? Currency, decimal CustomerCharge, decimal TechnicianCompensation, decimal? PlatformFee, string? PayerType, string? Note);
public record InvoiceLineReq(string? Description, decimal Quantity, decimal UnitPrice);
public record InvoiceReq(List<InvoiceLineReq>? Lines);
public record PaymentReq(Guid? InvoiceId, Guid? PayableId, Guid? RefundId, string? Method, decimal Amount, string? Currency, string? ProviderRef, string? Note);
public record ConfirmReq(string? ProviderRef, string? AcknowledgedBy, string? Note);
public record FailReq(string? Note);
public record RefundReq(Guid InvoiceId, decimal Amount, string? Reason);
public record FinDecisionReq(string? Decision, string? Note);
public record DisputeReq(Guid? PayableId, Guid? PaymentId, string? Description);
public record DisputeDecisionReq(string? Outcome, string? Resolution);
public record AckReq(decimal Amount, string? Method, string? ProviderRef, string? Note);
public record ProviderCallbackReq(string? Reference, string? ProviderRef, string? Status, decimal Amount, string? Currency);

public static class Phase4Endpoints
{
    static readonly JsonSerializerOptions Json = new(JsonSerializerDefaults.Web);
    static IResult Err(int code, string m) => Results.Json(new { error = m }, statusCode: code);

    static string[] Methods(IConfiguration cfg) => (cfg["Finance:Methods"] ?? "cash,bank,mobile_money,other").Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);

    // Any one of several permissions opens the door (e.g. dispatchers propose terms, finance officers read them).
    static async Task<Access> AnyOf(AccessService access, Guid uid, Guid companyId, CancellationToken ct, params string[] perms)
    {
        var best = Access.NotMember;
        foreach (var perm in perms)
        {
            var a = await access.Company(uid, companyId, perm, ct);
            if (a == Access.Allowed) return a;
            if (a == Access.Forbidden) best = a;
        }
        return best;
    }

    static async Task<IResult> Guard(Func<Task<IResult>> action)
    {
        try { return await action(); }
        catch (DbUpdateException) { return Err(409, "Another change to this record happened at the same time, or it duplicates an existing record. Reload and retry."); }
    }

    static object TermsDto(JobFinancialTerms t) => new { t.Id, t.JobId, t.Version, t.Currency, t.CustomerCharge, t.TechnicianCompensation, t.PlatformFee, t.PayerType, status = t.Status.ToString(), t.Note, t.ProposedBy, t.ProposedAt, t.ApprovedBy, t.ApprovedAt };
    static object PayDto(PaymentRecord x) => new
    {
        x.Id, x.Reference, x.JobId, x.Kind, status = x.Status.ToString(), x.Method, x.Amount, x.Currency, x.InvoiceId, x.PayableId, x.RefundId, x.PayerType, x.PayeeType,
        x.ProviderRef, x.AcknowledgedBy, x.Note, x.Verified, x.Reconciled, x.InitiatedAt, x.ConfirmedAt, x.ReconciledAt, x.ReversedAt, x.ReverseReason
    };

    static Task<bool> OpenDispute(AppDbContext db, Guid payableId, CancellationToken ct) => db.Disputes.AnyAsync(x => x.PayableId == payableId && x.Status == "Open", ct);

    // Bumps the concurrency token of whatever the payment is for, so concurrent money movements on one target cannot both commit.
    static async Task TouchTargetAsync(AppDbContext db, PaymentRecord pay, CancellationToken ct)
    {
        if (pay.InvoiceId is { } iid) (await db.Invoices.FirstAsync(x => x.Id == iid, ct)).Seq++;
        else if (pay.PayableId is { } pid) (await db.Payables.FirstAsync(x => x.Id == pid, ct)).Seq++;
        else if (pay.RefundId is { } rid) (await db.Refunds.FirstAsync(x => x.Id == rid, ct)).Seq++;
    }

    // Everything that follows a confirmed payment, in the same unit of work as the confirmation.
    static async Task ApplyConfirmedAsync(AppDbContext db, PaymentRecord pay, Guid? actor, CancellationToken ct)
    {
        var key = $"pay-confirm:{pay.Id}";
        var id = pay.Id.ToString();
        switch (pay.Kind)
        {
            case "customer_collection": Ledger.Post(db, pay.CompanyId, key, pay.Currency, "payment", id, actor, new Line(Acct.Cash, pay.Amount, 0), new Line(Acct.Receivable, 0, pay.Amount)); break;
            case "technician_payout": Ledger.Post(db, pay.CompanyId, key, pay.Currency, "payment", id, actor, new Line(Acct.TechPayable, pay.Amount, 0), new Line(Acct.Cash, 0, pay.Amount)); break;
            case "refund": Ledger.Post(db, pay.CompanyId, key, pay.Currency, "payment", id, actor, new Line(Acct.Refunds, pay.Amount, 0), new Line(Acct.Cash, 0, pay.Amount)); break;
            // direct_customer_to_technician: money never passes through the company, so nothing is posted to its books.
        }
        await TouchTargetAsync(db, pay, ct);
        if (pay.PayableId is { } payableId && pay.Kind == "technician_payout")
        {
            var uid = await (from x in db.Payables join t in db.Technicians on x.TechnicianId equals t.Id where x.Id == payableId select t.UserId).FirstAsync(ct);
            Notifier.Notify(db, uid, pay.CompanyId, "finance.payment_confirmed", "Payment confirmed", $"{pay.Amount} {pay.Currency} was paid to you ({pay.Reference}).");
        }
    }

    public static void Map(WebApplication app, RouteGroupBuilder api)
    {
        // ======== Financial terms (versioned; approved by someone other than the proposer) ========
        api.MapPost("/companies/{id:guid}/jobs/{jobId:guid}/financial-terms", async Task<IResult> (Guid id, Guid jobId, TermsReq r, ClaimsPrincipal p, AppDbContext db, AccessService access, IConfiguration cfg, HttpContext http, CancellationToken ct) =>
            await Guard(async () =>
            {
                var uid = Uid(p);
                if (Deny(await access.Company(uid, id, "finance.terms", ct)) is { } d) return d;
                var j = await LoadJob(db, id, jobId, ct); if (j is null) return Results.NotFound();
                if (j.Status == JobStatus.Cancelled) return Err(409, "A cancelled job cannot have financial terms.");
                var cur = Money.Currency(cfg, r.Currency); if (cur is null) return Bad("currency must be one of the allowed ISO codes.");
                if (!Money.ValidOrZero(r.CustomerCharge) || !Money.Valid(r.TechnicianCompensation) || !Money.ValidOrZero(r.PlatformFee ?? 0)) return Bad("Amounts must be positive with at most 4 decimals (customerCharge and platformFee may be 0).");
                var payer = (r.PayerType ?? "company").Trim().ToLowerInvariant();
                if (payer is not ("company" or "customer")) return Bad("payerType must be company or customer.");
                if (await db.Payables.AnyAsync(x => x.JobId == jobId && x.Status != "Cancelled", ct)) return Err(409, "Payment obligations already exist for this job; use refunds, reversals or a dispute to correct them.");
                foreach (var old in await db.FinancialTerms.Where(x => x.JobId == jobId && x.Status == TermsStatus.Draft).ToListAsync(ct)) old.Status = TermsStatus.Superseded;
                var version = (await db.FinancialTerms.Where(x => x.JobId == jobId).MaxAsync(x => (int?)x.Version, ct) ?? 0) + 1;
                var t = new JobFinancialTerms { CompanyId = id, JobId = jobId, Version = version, Currency = cur, CustomerCharge = r.CustomerCharge, TechnicianCompensation = r.TechnicianCompensation, PlatformFee = r.PlatformFee ?? 0, PayerType = payer, Note = r.Note?.Trim(), ProposedBy = uid };
                db.FinancialTerms.Add(t);
                await Notifier.NotifyHoldersAsync(db, id, "finance.terms.approve", "finance.terms_proposed", "Financial terms to approve", $"Job {j.Reference}: terms v{version} are waiting for approval.", ct, except: uid);
                db.Audit(http, uid, "finance.terms_proposed", "job", jobId.ToString(), id, new { version, t.Currency, t.PayerType });
                await db.SaveChangesAsync(ct);
                return Results.Created($"/companies/{id}/jobs/{jobId}/financial-terms/{t.Id}", TermsDto(t));
            }));

        api.MapGet("/companies/{id:guid}/jobs/{jobId:guid}/financial-terms", async Task<IResult> (Guid id, Guid jobId, ClaimsPrincipal p, AppDbContext db, AccessService access, CancellationToken ct) =>
        {
            if (Deny(await AnyOf(access, Uid(p), id, ct, "finance.read", "finance.terms", "finance.terms.approve")) is { } d) return d;
            if (await LoadJob(db, id, jobId, ct) is null) return Results.NotFound();
            var rows = await db.FinancialTerms.Where(x => x.JobId == jobId && x.CompanyId == id).OrderBy(x => x.Version).ToListAsync(ct);
            return Results.Ok(rows.Select(TermsDto));
        });

        api.MapPost("/companies/{id:guid}/jobs/{jobId:guid}/financial-terms/{tid:guid}/approve", async Task<IResult> (Guid id, Guid jobId, Guid tid, ClaimsPrincipal p, AppDbContext db, AccessService access, IConfiguration cfg, HttpContext http, CancellationToken ct) =>
            await Guard(async () =>
            {
                var uid = Uid(p);
                if (Deny(await access.Company(uid, id, "finance.terms.approve", ct)) is { } d) return d;
                var j = await LoadJob(db, id, jobId, ct); if (j is null) return Results.NotFound();
                var t = await db.FinancialTerms.FirstOrDefaultAsync(x => x.Id == tid && x.JobId == jobId && x.CompanyId == id, ct);
                if (t is null) return Results.NotFound();
                if (t.Status != TermsStatus.Draft) return Err(409, $"These terms are {t.Status}.");
                if (t.ProposedBy == uid && t.CustomerCharge + t.TechnicianCompensation > Money.SelfApprovalLimit(cfg) && !await access.IsSuper(uid, ct)) return Err(403, "Terms must be approved by someone other than the person who proposed them.");
                if (await db.Payables.AnyAsync(x => x.JobId == jobId && x.Status != "Cancelled", ct)) return Err(409, "Payment obligations already exist for this job.");
                await using var tx = await db.Database.BeginTransactionAsync(ct);
                foreach (var old in await db.FinancialTerms.Where(x => x.JobId == jobId && x.Status == TermsStatus.Approved).ToListAsync(ct)) old.Status = TermsStatus.Superseded;
                await db.SaveChangesAsync(ct);   // frees the one-approved-per-job slot first
                t.Status = TermsStatus.Approved; t.ApprovedBy = uid; t.ApprovedAt = DateTime.UtcNow;
                db.Audit(http, uid, "finance.terms_approved", "job", jobId.ToString(), id, new { t.Version, t.CustomerCharge, t.TechnicianCompensation, t.PlatformFee });
                await FinanceFlow.AccrueAsync(db, j, uid, ct);   // only acts when the job is already Completed
                await db.SaveChangesAsync(ct);
                await tx.CommitAsync(ct);
                return Results.Ok(TermsDto(t));
            }));

        // ======== Invoices ========
        api.MapPost("/companies/{id:guid}/jobs/{jobId:guid}/invoice", async Task<IResult> (Guid id, Guid jobId, InvoiceReq r, ClaimsPrincipal p, AppDbContext db, AccessService access, HttpContext http, CancellationToken ct) =>
            await Guard(async () =>
            {
                var uid = Uid(p);
                if (Deny(await access.Company(uid, id, "finance.invoice", ct)) is { } d) return d;
                var j = await LoadJob(db, id, jobId, ct); if (j is null) return Results.NotFound();
                if (j.Status != JobStatus.Completed) return Err(409, "Invoices are issued for completed jobs.");
                var t = await db.FinancialTerms.FirstOrDefaultAsync(x => x.JobId == jobId && x.Status == TermsStatus.Approved, ct);
                if (t is null || t.CustomerCharge <= 0) return Err(409, "The job needs approved financial terms with a customer charge.");
                if (await db.Invoices.AnyAsync(x => x.JobId == jobId && x.Status != "Void", ct)) return Err(409, "This job already has an invoice.");
                var lines = r.Lines is { Count: > 0 } ? r.Lines : [new InvoiceLineReq($"Service job {j.Reference}", 1, t.CustomerCharge)];
                if (lines.Count > 50 || lines.Any(l => string.IsNullOrWhiteSpace(l.Description) || l.Description.Length > 200 || !Money.Valid(l.Quantity) || !Money.Valid(l.UnitPrice))) return Bad("Each line needs a description (max 200), a positive quantity and a positive unit price.");
                var built = lines.Select(l => new InvoiceLine { Description = l.Description!.Trim(), Quantity = l.Quantity, UnitPrice = l.UnitPrice, Amount = Math.Round(l.Quantity * l.UnitPrice, 4) }).ToList();
                var total = built.Sum(x => x.Amount);
                if (total != t.CustomerCharge) return Err(409, $"Invoice lines total {total} but the approved customer charge is {t.CustomerCharge}.");
                var inv = new Invoice { CompanyId = id, JobId = jobId, CustomerId = j.CustomerId, TermsId = t.Id, Number = $"INV-{DateTime.UtcNow:yyMMdd}-{Guid.NewGuid().ToString("N")[..6].ToUpperInvariant()}", Currency = t.Currency, Total = total, IssuedBy = uid };
                db.Invoices.Add(inv);
                foreach (var l in built) { l.InvoiceId = inv.Id; db.InvoiceLines.Add(l); }
                Ledger.Post(db, id, $"invoice-issue:{inv.Id}", inv.Currency, "invoice", inv.Id.ToString(), uid, new Line(Acct.Receivable, total, 0), new Line(Acct.Revenue, 0, total));
                db.Audit(http, uid, "finance.invoice_issued", "invoice", inv.Id.ToString(), id, new { inv.Number, total, inv.Currency });
                await db.SaveChangesAsync(ct);
                return Results.Created($"/companies/{id}/invoices/{inv.Id}", new { inv.Id, inv.Number, inv.Total, inv.Currency, status = inv.Status });
            }));

        async Task<object> InvoiceView(AppDbContext db, Invoice inv, CancellationToken ct)
        {
            var pays = await db.Payments.Where(x => x.InvoiceId == inv.Id).ToListAsync(ct);
            var refunds = await db.Refunds.Where(x => x.InvoiceId == inv.Id).ToListAsync(ct);
            var s = FinanceMath.Settle(inv.Total, pays);
            return new { inv.Id, inv.Number, inv.JobId, inv.CustomerId, inv.Currency, inv.Total, status = inv.Status, inv.IssuedAt, collected = s.Paid, pending = s.Pending, outstanding = inv.Status == "Void" ? 0m : s.Outstanding, settlement = s.State, refundsRequested = refunds.Where(x => x.Status != "Rejected").Sum(x => x.Amount) };
        }

        api.MapGet("/companies/{id:guid}/invoices", async Task<IResult> (Guid id, ClaimsPrincipal p, AppDbContext db, AccessService access, CancellationToken ct) =>
        {
            if (Deny(await access.Company(Uid(p), id, "finance.read", ct)) is { } d) return d;
            var rows = await db.Invoices.Where(x => x.CompanyId == id).OrderByDescending(x => x.IssuedAt).Take(100).ToListAsync(ct);
            var list = new List<object>(); foreach (var inv in rows) list.Add(await InvoiceView(db, inv, ct));
            return Results.Ok(list);
        });

        api.MapGet("/companies/{id:guid}/invoices/{iid:guid}", async Task<IResult> (Guid id, Guid iid, ClaimsPrincipal p, AppDbContext db, AccessService access, CancellationToken ct) =>
        {
            if (Deny(await access.Company(Uid(p), id, "finance.read", ct)) is { } d) return d;
            var inv = await db.Invoices.FirstOrDefaultAsync(x => x.Id == iid && x.CompanyId == id, ct); if (inv is null) return Results.NotFound();
            var lines = await db.InvoiceLines.Where(x => x.InvoiceId == iid).Select(x => new { x.Description, x.Quantity, x.UnitPrice, x.Amount }).ToListAsync(ct);
            var pays = await db.Payments.Where(x => x.InvoiceId == iid).OrderBy(x => x.InitiatedAt).ToListAsync(ct);
            return Results.Ok(new { invoice = await InvoiceView(db, inv, ct), lines, payments = pays.Select(PayDto) });
        });

        api.MapPost("/companies/{id:guid}/invoices/{iid:guid}/void", async Task<IResult> (Guid id, Guid iid, ReasonReq r, ClaimsPrincipal p, AppDbContext db, AccessService access, HttpContext http, CancellationToken ct) =>
            await Guard(async () =>
            {
                var uid = Uid(p);
                if (Deny(await access.Company(uid, id, "finance.adjust", ct)) is { } d) return d;
                var inv = await db.Invoices.FirstOrDefaultAsync(x => x.Id == iid && x.CompanyId == id, ct); if (inv is null) return Results.NotFound();
                if (string.IsNullOrWhiteSpace(r.Reason)) return Bad("reason is required.");
                if (inv.Status == "Void") return Err(409, "Already void.");
                if (await db.Payments.AnyAsync(x => x.InvoiceId == iid && (x.Status == PaymentStatus.Initiated || x.Status == PaymentStatus.Confirmed), ct)) return Err(409, "Reverse or fail the payments on this invoice first.");
                inv.Status = "Void"; inv.VoidedBy = uid; inv.VoidedAt = DateTime.UtcNow; inv.VoidReason = r.Reason.Trim(); inv.Seq++;
                await Ledger.ReverseAsync(db, id, $"invoice-issue:{iid}", $"invoice-void:{iid}", "invoice", iid.ToString(), uid, ct);
                db.Audit(http, uid, "finance.invoice_voided", "invoice", iid.ToString(), id, new { reason = r.Reason.Trim() });
                await db.SaveChangesAsync(ct);
                return Results.Ok(new { inv.Id, status = inv.Status });
            }));

        // ======== Technician payables (company-paid, or tracked direct customer payments) ========
        async Task<object> PayableView(AppDbContext db, TechnicianPayable x, CancellationToken ct)
        {
            var pays = await db.Payments.Where(y => y.PayableId == x.Id).ToListAsync(ct);
            var s = FinanceMath.Settle(x.Amount, pays);
            var tech = await db.Technicians.Where(t => t.Id == x.TechnicianId).Select(t => t.DisplayName).FirstAsync(ct);
            var job = await db.Jobs.Where(j => j.Id == x.JobId).Select(j => j.Reference).FirstAsync(ct);
            return new { x.Id, x.JobId, jobReference = job, x.TechnicianId, technician = tech, x.PayerType, x.Currency, x.Amount, status = x.Status, paid = s.Paid, pending = s.Pending, outstanding = s.Outstanding, settlement = s.State, x.CreatedAt, x.ApprovedAt, disputed = await OpenDispute(db, x.Id, ct) };
        }

        api.MapGet("/companies/{id:guid}/payables", async Task<IResult> (Guid id, ClaimsPrincipal p, AppDbContext db, AccessService access, CancellationToken ct) =>
        {
            if (Deny(await access.Company(Uid(p), id, "finance.read", ct)) is { } d) return d;
            var rows = await db.Payables.Where(x => x.CompanyId == id).OrderByDescending(x => x.CreatedAt).Take(100).ToListAsync(ct);
            var list = new List<object>(); foreach (var x in rows) list.Add(await PayableView(db, x, ct));
            return Results.Ok(list);
        });

        api.MapPost("/companies/{id:guid}/payables/{pid:guid}/approve", async Task<IResult> (Guid id, Guid pid, ClaimsPrincipal p, AppDbContext db, AccessService access, HttpContext http, CancellationToken ct) =>
            await Guard(async () =>
            {
                var uid = Uid(p);
                if (Deny(await access.Company(uid, id, "finance.payment", ct)) is { } d) return d;
                var x = await db.Payables.FirstOrDefaultAsync(y => y.Id == pid && y.CompanyId == id, ct); if (x is null) return Results.NotFound();
                if (x.PayerType != "company") return Err(409, "Direct customer payments need no company approval.");
                if (x.Status != "Accrued") return Err(409, $"This payable is {x.Status}.");
                x.Status = "Approved"; x.ApprovedBy = uid; x.ApprovedAt = DateTime.UtcNow; x.Seq++;
                Ledger.Post(db, id, $"payable-accrue:{x.Id}", x.Currency, "payable", x.Id.ToString(), uid, new Line(Acct.TechExpense, x.Amount, 0), new Line(Acct.TechPayable, 0, x.Amount));
                var techUser = await db.Technicians.Where(t => t.Id == x.TechnicianId).Select(t => t.UserId).FirstAsync(ct);
                Notifier.Notify(db, techUser, id, "finance.payable_approved", "Payment approved", $"{x.Amount} {x.Currency} was approved for payment.");
                db.Audit(http, uid, "finance.payable_approved", "payable", x.Id.ToString(), id, new { x.Amount, x.Currency });
                await db.SaveChangesAsync(ct);
                return Results.Ok(new { x.Id, x.Status });
            }));

        // ======== Payments: initiate -> confirm (different person) -> reconcile (not the confirmer) ========
        api.MapPost("/companies/{id:guid}/payments", async Task<IResult> (Guid id, PaymentReq r, ClaimsPrincipal p, AppDbContext db, AccessService access, IConfiguration cfg, HttpContext http, CancellationToken ct) =>
        {
            var uid = Uid(p);
            if (Deny(await access.Company(uid, id, "finance.payment", ct)) is { } d) return d;
            var targets = new[] { r.InvoiceId, r.PayableId, r.RefundId }.Count(x => x != null);
            if (targets != 1) return Bad("Give exactly one of invoiceId, payableId or refundId.");
            var method = (r.Method ?? "").Trim().ToLowerInvariant();
            if (!Methods(cfg).Contains(method)) return Bad("method must be one of: " + string.Join(", ", Methods(cfg)));
            if (!Money.Valid(r.Amount)) return Bad("amount must be positive with at most 4 decimals.");
            var providerRef = string.IsNullOrWhiteSpace(r.ProviderRef) ? null : r.ProviderRef.Trim();
            if (providerRef is { Length: > 100 }) return Bad("providerRef is too long.");
            return await Guard(() => Idem.RunAsync(db, http, $"pay-init:{uid}", async () =>
            {
                PaymentRecord pay; decimal limit; string cur; List<PaymentRecord> existing;
                if (r.InvoiceId is { } iid)
                {
                    var inv = await db.Invoices.FirstOrDefaultAsync(x => x.Id == iid && x.CompanyId == id, ct); if (inv is null) return (404, new { error = "Not found." });
                    if (inv.Status != "Issued") return (409, new { error = $"The invoice is {inv.Status}." });
                    limit = inv.Total; cur = inv.Currency; inv.Seq++;
                    existing = await db.Payments.Where(x => x.InvoiceId == iid).ToListAsync(ct);
                    pay = new PaymentRecord { JobId = inv.JobId, InvoiceId = iid, Kind = "customer_collection", PayerType = "customer", PayeeType = "company" };
                }
                else if (r.PayableId is { } pid)
                {
                    var x = await db.Payables.FirstOrDefaultAsync(y => y.Id == pid && y.CompanyId == id, ct); if (x is null) return (404, new { error = "Not found." });
                    if (x.Status != "Approved") return (409, new { error = x.Status == "Accrued" ? "Approve the payable before paying it." : $"The payable is {x.Status}." });
                    if (await OpenDispute(db, pid, ct)) return (409, new { error = "This payable has an open dispute; resolve it before paying." });
                    limit = x.Amount; cur = x.Currency; x.Seq++;
                    existing = await db.Payments.Where(y => y.PayableId == pid).ToListAsync(ct);
                    pay = new PaymentRecord { JobId = x.JobId, PayableId = pid, Kind = x.PayerType == "company" ? "technician_payout" : "direct_customer_to_technician", PayerType = x.PayerType, PayeeType = "technician" };
                }
                else
                {
                    var rf = await db.Refunds.FirstOrDefaultAsync(x => x.Id == r.RefundId && x.CompanyId == id, ct); if (rf is null) return (404, new { error = "Not found." });
                    if (rf.Status != "Approved") return (409, new { error = $"The refund is {rf.Status}; only approved refunds can be paid." });
                    limit = rf.Amount; cur = rf.Currency; rf.Seq++;
                    existing = await db.Payments.Where(x => x.RefundId == rf.Id).ToListAsync(ct);
                    pay = new PaymentRecord { JobId = rf.JobId, RefundId = rf.Id, Kind = "refund", PayerType = "company", PayeeType = "customer" };
                }
                if (r.Currency is not null && !string.Equals(r.Currency.Trim(), cur, StringComparison.OrdinalIgnoreCase)) return (409, new { error = $"Currency mismatch: this obligation is in {cur}." });
                var committed = existing.Where(x => x.Status is PaymentStatus.Initiated or PaymentStatus.Confirmed).Sum(x => x.Amount);
                if (committed + r.Amount > limit) return (409, new { error = $"Payment would exceed the amount due: {limit - committed} {cur} remains." });
                if (providerRef is not null && await db.Payments.AnyAsync(x => x.CompanyId == id && x.Method == method && x.ProviderRef == providerRef, ct)) return (409, new { error = "This provider reference is already recorded." });
                pay.CompanyId = id; pay.Reference = FinanceFlow.NewPaymentRef(); pay.Method = method; pay.Currency = cur; pay.Amount = r.Amount; pay.ProviderRef = providerRef; pay.Note = r.Note?.Trim(); pay.RecordedBy = uid;
                db.Payments.Add(pay);
                db.PaymentEvents.Add(new PaymentEvent { PaymentId = pay.Id, Event = "initiated", ActorUserId = uid, Note = pay.Note });
                db.Audit(http, uid, "finance.payment_initiated", "payment", pay.Id.ToString(), id, new { pay.Kind, pay.Amount, pay.Currency, pay.Method });
                return (201, PayDto(pay));
            }, ct));
        });

        api.MapGet("/companies/{id:guid}/payments", async Task<IResult> (Guid id, string? status, bool? unreconciled, ClaimsPrincipal p, AppDbContext db, AccessService access, CancellationToken ct) =>
        {
            if (Deny(await access.Company(Uid(p), id, "finance.read", ct)) is { } d) return d;
            var q = db.Payments.Where(x => x.CompanyId == id);
            if (status is not null) { if (!Enum.TryParse<PaymentStatus>(status, true, out var st)) return Bad("Unknown status."); q = q.Where(x => x.Status == st); }
            if (unreconciled == true) q = q.Where(x => x.Status == PaymentStatus.Confirmed && !x.Reconciled);
            var rows = await q.OrderByDescending(x => x.InitiatedAt).Take(100).ToListAsync(ct);
            return Results.Ok(rows.Select(PayDto));
        });

        api.MapGet("/companies/{id:guid}/payments/{pid:guid}", async Task<IResult> (Guid id, Guid pid, ClaimsPrincipal p, AppDbContext db, AccessService access, CancellationToken ct) =>
        {
            if (Deny(await access.Company(Uid(p), id, "finance.read", ct)) is { } d) return d;
            var x = await db.Payments.FirstOrDefaultAsync(y => y.Id == pid && y.CompanyId == id, ct); if (x is null) return Results.NotFound();
            var ev = await db.PaymentEvents.Where(e => e.PaymentId == pid).OrderBy(e => e.At).Select(e => new { e.Event, e.ActorUserId, e.Note, e.At }).ToListAsync(ct);
            return Results.Ok(new { payment = PayDto(x), history = ev });
        });

        api.MapPost("/companies/{id:guid}/payments/{pid:guid}/confirm", async Task<IResult> (Guid id, Guid pid, ConfirmReq r, ClaimsPrincipal p, AppDbContext db, AccessService access, IConfiguration cfg, HttpContext http, CancellationToken ct) =>
            await Guard(async () =>
            {
                var uid = Uid(p);
                if (Deny(await access.Company(uid, id, "finance.payment", ct)) is { } d) return d;
                var x = await db.Payments.FirstOrDefaultAsync(y => y.Id == pid && y.CompanyId == id, ct); if (x is null) return Results.NotFound();
                if (x.Status != PaymentStatus.Initiated) return Err(409, $"This payment is {x.Status}.");
                if (x.RecordedBy == uid && x.Amount > Money.SelfApprovalLimit(cfg) && !await access.IsSuper(uid, ct)) return Err(403, "Payment initiation and confirmation must be done by different people.");
                if (x.Method == "cash")
                {
                    if (string.IsNullOrWhiteSpace(r.AcknowledgedBy) || r.AcknowledgedBy.Length > 120) return Bad("acknowledgedBy (who received or handed over the cash) is required.");
                    x.AcknowledgedBy = r.AcknowledgedBy.Trim();
                }
                else
                {
                    var reference = string.IsNullOrWhiteSpace(r.ProviderRef) ? x.ProviderRef : r.ProviderRef.Trim();
                    if (string.IsNullOrWhiteSpace(reference) || reference.Length > 100) return Bad("providerRef (the bank or provider transaction reference) is required.");
                    x.ProviderRef = reference;
                }
                x.Status = PaymentStatus.Confirmed; x.ConfirmedBy = uid; x.ConfirmedAt = DateTime.UtcNow; x.Verified = false;   // a person said so; only a signed provider callback is "verified"
                if (!string.IsNullOrWhiteSpace(r.Note)) x.Note = r.Note.Trim();
                db.PaymentEvents.Add(new PaymentEvent { PaymentId = x.Id, Event = "confirmed_manually", ActorUserId = uid, Note = r.Note });
                await ApplyConfirmedAsync(db, x, uid, ct);
                db.Audit(http, uid, "finance.payment_confirmed", "payment", x.Id.ToString(), id, new { x.Amount, x.Currency, x.Method, verified = false });
                Outbox.Add(db, "finance.payment_confirmed", "payment", x.Id.ToString(), id, new { x.Amount, x.Currency, x.Kind, verified = false });
                await db.SaveChangesAsync(ct);
                return Results.Ok(PayDto(x));
            }));

        api.MapPost("/companies/{id:guid}/payments/{pid:guid}/fail", async Task<IResult> (Guid id, Guid pid, FailReq r, ClaimsPrincipal p, AppDbContext db, AccessService access, HttpContext http, CancellationToken ct) =>
            await Guard(async () =>
            {
                var uid = Uid(p);
                if (Deny(await access.Company(uid, id, "finance.payment", ct)) is { } d) return d;
                var x = await db.Payments.FirstOrDefaultAsync(y => y.Id == pid && y.CompanyId == id, ct); if (x is null) return Results.NotFound();
                if (x.Status != PaymentStatus.Initiated) return Err(409, $"Only initiated payments can fail; this one is {x.Status}.");
                if (string.IsNullOrWhiteSpace(r.Note)) return Bad("note is required.");
                x.Status = PaymentStatus.Failed;
                db.PaymentEvents.Add(new PaymentEvent { PaymentId = x.Id, Event = "failed", ActorUserId = uid, Note = r.Note.Trim() });
                await TouchTargetAsync(db, x, ct);
                db.Audit(http, uid, "finance.payment_failed", "payment", x.Id.ToString(), id);
                await db.SaveChangesAsync(ct);
                return Results.Ok(PayDto(x));
            }));

        api.MapPost("/companies/{id:guid}/payments/{pid:guid}/reverse", async Task<IResult> (Guid id, Guid pid, ReasonReq r, ClaimsPrincipal p, AppDbContext db, AccessService access, IConfiguration cfg, HttpContext http, CancellationToken ct) =>
            await Guard(async () =>
            {
                var uid = Uid(p);
                if (Deny(await access.Company(uid, id, "finance.adjust", ct)) is { } d) return d;
                var x = await db.Payments.FirstOrDefaultAsync(y => y.Id == pid && y.CompanyId == id, ct); if (x is null) return Results.NotFound();
                if (x.Status != PaymentStatus.Confirmed) return Err(409, $"Only confirmed payments can be reversed; this one is {x.Status}.");
                if (string.IsNullOrWhiteSpace(r.Reason)) return Bad("reason is required.");
                if (x.ConfirmedBy == uid && x.Amount > Money.SelfApprovalLimit(cfg) && !await access.IsSuper(uid, ct)) return Err(403, "A confirmed payment must be reversed by someone other than the person who confirmed it.");
                x.Status = PaymentStatus.Reversed; x.ReversedBy = uid; x.ReversedAt = DateTime.UtcNow; x.ReverseReason = r.Reason.Trim();
                await Ledger.ReverseAsync(db, id, $"pay-confirm:{x.Id}", $"pay-reverse:{x.Id}", "payment", x.Id.ToString(), uid, ct);
                await TouchTargetAsync(db, x, ct);
                db.PaymentEvents.Add(new PaymentEvent { PaymentId = x.Id, Event = "reversed", ActorUserId = uid, Note = r.Reason.Trim() });
                db.Audit(http, uid, "finance.payment_reversed", "payment", x.Id.ToString(), id, new { x.Amount, x.Currency });
                await db.SaveChangesAsync(ct);
                return Results.Ok(PayDto(x));
            }));

        api.MapPost("/companies/{id:guid}/payments/{pid:guid}/reconcile", async Task<IResult> (Guid id, Guid pid, FailReq r, ClaimsPrincipal p, AppDbContext db, AccessService access, HttpContext http, CancellationToken ct) =>
            await Guard(async () =>
            {
                var uid = Uid(p);
                if (Deny(await access.Company(uid, id, "finance.reconcile", ct)) is { } d) return d;
                var x = await db.Payments.FirstOrDefaultAsync(y => y.Id == pid && y.CompanyId == id, ct); if (x is null) return Results.NotFound();
                if (x.Status != PaymentStatus.Confirmed) return Err(409, $"Only confirmed payments can be reconciled; this one is {x.Status}.");
                if (x.Reconciled) return Err(409, "Already reconciled.");
                if (x.ConfirmedBy == uid) return Err(403, "Reconciliation must be done by someone other than the person who confirmed the payment.");
                x.Reconciled = true; x.ReconciledBy = uid; x.ReconciledAt = DateTime.UtcNow; x.ReconcileNote = r.Note?.Trim();
                db.PaymentEvents.Add(new PaymentEvent { PaymentId = x.Id, Event = "reconciled", ActorUserId = uid, Note = r.Note });
                await TouchTargetAsync(db, x, ct);
                db.Audit(http, uid, "finance.payment_reconciled", "payment", x.Id.ToString(), id);
                await db.SaveChangesAsync(ct);
                return Results.Ok(PayDto(x));
            }));

        // Signed callback from a payment provider. Which provider is a business decision, so this is provider-neutral:
        // the body carries our payment reference, and the HMAC-SHA256 of the raw body (hex, X-Signature) proves who sent it.
        app.MapPost("/payments/provider-callback", async Task<IResult> (HttpRequest req, AppDbContext db, IConfiguration cfg, CancellationToken ct) =>
        {
            var secret = cfg["Finance:CallbackSecret"];
            if (string.IsNullOrEmpty(secret) || secret.Length < 16) return Err(503, "Provider callbacks are not configured.");
            string body; using (var sr = new StreamReader(req.Body)) body = await sr.ReadToEndAsync(ct);
            var expected = Convert.ToHexString(HMACSHA256.HashData(Encoding.UTF8.GetBytes(secret), Encoding.UTF8.GetBytes(body))).ToLowerInvariant();
            var sig = req.Headers["X-Signature"].ToString().Trim().ToLowerInvariant();
            if (sig.Length != expected.Length || !CryptographicOperations.FixedTimeEquals(Encoding.ASCII.GetBytes(sig), Encoding.ASCII.GetBytes(expected))) return Results.Unauthorized();
            ProviderCallbackReq? m;
            try { m = JsonSerializer.Deserialize<ProviderCallbackReq>(body, Json); } catch (JsonException) { return Bad("Invalid JSON."); }
            if (m is null || string.IsNullOrWhiteSpace(m.Reference)) return Bad("reference is required.");
            var pay = await db.Payments.FirstOrDefaultAsync(x => x.Reference == m.Reference, ct); if (pay is null) return Results.NotFound();
            try
            {
                if (m.Status == "succeeded")
                {
                    if (pay.Status == PaymentStatus.Confirmed) { db.PaymentEvents.Add(new PaymentEvent { PaymentId = pay.Id, Event = "callback_duplicate" }); await db.SaveChangesAsync(ct); return Results.Ok(new { duplicate = true }); }
                    if (pay.Status != PaymentStatus.Initiated) return Err(409, $"The payment is {pay.Status}.");
                    if (m.Amount != pay.Amount || !string.Equals(m.Currency, pay.Currency, StringComparison.OrdinalIgnoreCase))
                    {
                        db.PaymentEvents.Add(new PaymentEvent { PaymentId = pay.Id, Event = "callback_mismatch", Note = $"provider said {m.Amount} {m.Currency}" }); await db.SaveChangesAsync(ct);
                        return Err(409, "Amount or currency does not match the payment; flagged for finance review.");
                    }
                    var reference = string.IsNullOrWhiteSpace(m.ProviderRef) ? pay.ProviderRef : m.ProviderRef.Trim();
                    if (string.IsNullOrWhiteSpace(reference) || reference.Length > 100) return Bad("providerRef is required.");
                    pay.ProviderRef = reference; pay.Status = PaymentStatus.Confirmed; pay.ConfirmedAt = DateTime.UtcNow; pay.Verified = true;
                    db.PaymentEvents.Add(new PaymentEvent { PaymentId = pay.Id, Event = "confirmed_by_provider" });
                    await ApplyConfirmedAsync(db, pay, null, ct);
                    await db.SaveChangesAsync(ct);
                    return Results.Ok(new { status = "Confirmed" });
                }
                if (m.Status == "failed")
                {
                    if (pay.Status == PaymentStatus.Initiated) { pay.Status = PaymentStatus.Failed; db.PaymentEvents.Add(new PaymentEvent { PaymentId = pay.Id, Event = "failed_by_provider" }); await TouchTargetAsync(db, pay, ct); await db.SaveChangesAsync(ct); }
                    return Results.Ok(new { status = pay.Status.ToString() });
                }
                return Bad("status must be succeeded or failed.");
            }
            catch (DbUpdateException) { return Err(409, "Concurrent update or duplicate reference; retry."); }   // the provider retries; the retry sees the settled state
        }).RequireRateLimiting("auth");

        // ======== Refunds: request -> approve by someone else -> pay through the normal payment flow ========
        api.MapPost("/companies/{id:guid}/refunds", async Task<IResult> (Guid id, RefundReq r, ClaimsPrincipal p, AppDbContext db, AccessService access, HttpContext http, CancellationToken ct) =>
            await Guard(async () =>
            {
                var uid = Uid(p);
                if (Deny(await access.Company(uid, id, "finance.refund.request", ct)) is { } d) return d;
                var inv = await db.Invoices.FirstOrDefaultAsync(x => x.Id == r.InvoiceId && x.CompanyId == id, ct); if (inv is null) return Results.NotFound();
                if (!Money.Valid(r.Amount)) return Bad("amount must be positive with at most 4 decimals.");
                if (string.IsNullOrWhiteSpace(r.Reason) || r.Reason.Length > 500) return Bad("reason is required (max 500).");
                if (inv.Status != "Issued") return Err(409, $"The invoice is {inv.Status}.");
                var collected = (await db.Payments.Where(x => x.InvoiceId == inv.Id).ToListAsync(ct)).Where(x => x.Status == PaymentStatus.Confirmed).Sum(x => x.Amount);
                var reserved = (await db.Refunds.Where(x => x.InvoiceId == inv.Id).ToListAsync(ct)).Where(x => x.Status != "Rejected").Sum(x => x.Amount);
                if (r.Amount > collected - reserved) return Err(409, $"At most {collected - reserved} {inv.Currency} can still be refunded on this invoice.");
                inv.Seq++;   // serialises concurrent refund requests on the same invoice
                var rf = new Refund { CompanyId = id, JobId = inv.JobId, InvoiceId = inv.Id, Currency = inv.Currency, Amount = r.Amount, Reason = r.Reason.Trim(), RequestedBy = uid };
                db.Refunds.Add(rf);
                await Notifier.NotifyHoldersAsync(db, id, "finance.refund.approve", "finance.refund_requested", "Refund to approve", $"A refund of {rf.Amount} {rf.Currency} on {inv.Number} is waiting for approval.", ct, except: uid);
                db.Audit(http, uid, "finance.refund_requested", "refund", rf.Id.ToString(), id, new { rf.Amount, rf.Currency });
                await db.SaveChangesAsync(ct);
                return Results.Created($"/companies/{id}/refunds/{rf.Id}", new { rf.Id, rf.Amount, rf.Currency, status = rf.Status });
            }));

        api.MapGet("/companies/{id:guid}/refunds", async Task<IResult> (Guid id, ClaimsPrincipal p, AppDbContext db, AccessService access, CancellationToken ct) =>
        {
            if (Deny(await access.Company(Uid(p), id, "finance.read", ct)) is { } d) return d;
            var rows = await db.Refunds.Where(x => x.CompanyId == id).OrderByDescending(x => x.RequestedAt).Take(100).ToListAsync(ct);
            var list = new List<object>();
            foreach (var x in rows)
            {
                var s = FinanceMath.Settle(x.Amount, await db.Payments.Where(y => y.RefundId == x.Id).ToListAsync(ct));
                list.Add(new { x.Id, x.InvoiceId, x.JobId, x.Currency, x.Amount, x.Reason, x.Status, x.RequestedBy, x.RequestedAt, x.DecidedBy, x.DecidedAt, x.DecisionNote, paid = s.Paid, settlement = x.Status == "Approved" ? s.State : x.Status });
            }
            return Results.Ok(list);
        });

        api.MapPost("/companies/{id:guid}/refunds/{rid:guid}/decision", async Task<IResult> (Guid id, Guid rid, FinDecisionReq r, ClaimsPrincipal p, AppDbContext db, AccessService access, IConfiguration cfg, HttpContext http, CancellationToken ct) =>
            await Guard(async () =>
            {
                var uid = Uid(p);
                if (Deny(await access.Company(uid, id, "finance.refund.approve", ct)) is { } d) return d;
                var x = await db.Refunds.FirstOrDefaultAsync(y => y.Id == rid && y.CompanyId == id, ct); if (x is null) return Results.NotFound();
                if (r.Decision is not ("approve" or "reject")) return Bad("decision must be approve or reject.");
                if (r.Decision == "reject" && string.IsNullOrWhiteSpace(r.Note)) return Bad("note is required when rejecting.");
                if (x.Status != "Requested") return Err(409, $"This refund is {x.Status}.");
                if (x.RequestedBy == uid && x.Amount > Money.SelfApprovalLimit(cfg) && !await access.IsSuper(uid, ct)) return Err(403, "A refund must be decided by someone other than the person who requested it.");
                x.Status = r.Decision == "approve" ? "Approved" : "Rejected"; x.DecidedBy = uid; x.DecidedAt = DateTime.UtcNow; x.DecisionNote = r.Note?.Trim(); x.Seq++;
                Notifier.Notify(db, x.RequestedBy, id, "finance.refund_decided", "Refund " + x.Status.ToLowerInvariant(), $"Your refund request of {x.Amount} {x.Currency} was {x.Status.ToLowerInvariant()}.");
                db.Audit(http, uid, "finance.refund_" + x.Status.ToLowerInvariant(), "refund", x.Id.ToString(), id, new { x.Amount, x.Currency });
                await db.SaveChangesAsync(ct);
                return Results.Ok(new { x.Id, x.Status });
            }));

        // ======== Disputes: link to a payable or payment, block payout while open, decide separately from any adjustment ========
        api.MapPost("/companies/{id:guid}/disputes", async Task<IResult> (Guid id, DisputeReq r, ClaimsPrincipal p, AppDbContext db, AccessService access, HttpContext http, CancellationToken ct) =>
            await Guard(async () =>
            {
                var uid = Uid(p);
                if (Deny(await access.Company(uid, id, "finance.read", ct)) is { } d) return d;
                if ((r.PayableId is null) == (r.PaymentId is null)) return Bad("Give exactly one of payableId or paymentId.");
                if (string.IsNullOrWhiteSpace(r.Description) || r.Description.Length > 2000) return Bad("description is required (max 2000).");
                Guid jobId;
                if (r.PayableId is { } pid) { var x = await db.Payables.FirstOrDefaultAsync(y => y.Id == pid && y.CompanyId == id, ct); if (x is null) return Results.NotFound(); jobId = x.JobId; }
                else { var x = await db.Payments.FirstOrDefaultAsync(y => y.Id == r.PaymentId && y.CompanyId == id, ct); if (x is null) return Results.NotFound(); jobId = x.JobId; }
                var dsp = new Dispute { CompanyId = id, JobId = jobId, PayableId = r.PayableId, PaymentId = r.PaymentId, RaisedBy = uid, Description = r.Description.Trim() };
                db.Disputes.Add(dsp);
                await Notifier.NotifyHoldersAsync(db, id, "finance.adjust", "finance.dispute_raised", "Dispute raised", "A payment dispute needs a decision.", ct, except: uid);
                db.Audit(http, uid, "finance.dispute_raised", "dispute", dsp.Id.ToString(), id);
                await db.SaveChangesAsync(ct);
                return Results.Created($"/companies/{id}/disputes/{dsp.Id}", new { dsp.Id, dsp.Status });
            }));

        api.MapGet("/companies/{id:guid}/disputes", async Task<IResult> (Guid id, ClaimsPrincipal p, AppDbContext db, AccessService access, CancellationToken ct) =>
        {
            if (Deny(await access.Company(Uid(p), id, "finance.read", ct)) is { } d) return d;
            return Results.Ok(await db.Disputes.Where(x => x.CompanyId == id).OrderByDescending(x => x.CreatedAt).Take(100).Select(x => new { x.Id, x.JobId, x.PayableId, x.PaymentId, x.Description, x.Status, x.Outcome, x.Resolution, x.CreatedAt, x.ResolvedAt }).ToListAsync(ct));
        });

        api.MapPost("/companies/{id:guid}/disputes/{did:guid}/decision", async Task<IResult> (Guid id, Guid did, DisputeDecisionReq r, ClaimsPrincipal p, AppDbContext db, AccessService access, HttpContext http, CancellationToken ct) =>
            await Guard(async () =>
            {
                var uid = Uid(p);
                if (Deny(await access.Company(uid, id, "finance.adjust", ct)) is { } d) return d;
                var x = await db.Disputes.FirstOrDefaultAsync(y => y.Id == did && y.CompanyId == id, ct); if (x is null) return Results.NotFound();
                if (r.Outcome is not ("upheld" or "rejected" or "adjusted")) return Bad("outcome must be upheld, rejected or adjusted.");
                if (string.IsNullOrWhiteSpace(r.Resolution) || r.Resolution.Length > 2000) return Bad("resolution is required (max 2000). Reference any refund or reversal posted separately.");
                if (x.Status != "Open") return Err(409, "Already resolved.");
                if (x.RaisedBy == uid) return Err(403, "A dispute must be decided by someone other than the person who raised it.");
                x.Status = "Resolved"; x.Outcome = r.Outcome; x.Resolution = r.Resolution.Trim(); x.DecidedBy = uid; x.ResolvedAt = DateTime.UtcNow;
                Notifier.Notify(db, x.RaisedBy, id, "finance.dispute_resolved", "Dispute resolved", $"Outcome: {x.Outcome}.");
                db.Audit(http, uid, "finance.dispute_resolved", "dispute", x.Id.ToString(), id, new { x.Outcome });
                await db.SaveChangesAsync(ct);
                return Results.Ok(new { x.Id, x.Status, x.Outcome });
            }));

        // ======== Ledger and reconciliation view ========
        api.MapGet("/companies/{id:guid}/ledger", async Task<IResult> (Guid id, int? take, ClaimsPrincipal p, AppDbContext db, AccessService access, CancellationToken ct) =>
        {
            if (Deny(await access.Company(Uid(p), id, "finance.read", ct)) is { } d) return d;
            var rows = await db.Ledger.Where(x => x.CompanyId == id).OrderByDescending(x => x.At).Take(Math.Clamp(take ?? 100, 1, 500)).ToListAsync(ct);
            return Results.Ok(rows.Select(x => new { x.Id, x.TxnKey, x.LineKey, x.AccountCode, x.Debit, x.Credit, x.Currency, x.SourceType, x.SourceId, x.ReversesLineKey, x.At }));
        });

        api.MapGet("/companies/{id:guid}/finance/reconciliation", async Task<IResult> (Guid id, ClaimsPrincipal p, AppDbContext db, AccessService access, CancellationToken ct) =>
        {
            if (Deny(await access.Company(Uid(p), id, "finance.read", ct)) is { } d) return d;
            var pays = await db.Payments.Where(x => x.CompanyId == id).ToListAsync(ct);
            var entries = await db.Ledger.Where(x => x.CompanyId == id).ToListAsync(ct);
            var trial = entries.GroupBy(x => (x.Currency, x.AccountCode)).OrderBy(g => g.Key.Currency).ThenBy(g => g.Key.AccountCode)
                .Select(g => new { g.Key.Currency, account = g.Key.AccountCode, debit = g.Sum(x => x.Debit), credit = g.Sum(x => x.Credit) }).ToList();
            var balanced = entries.GroupBy(x => x.Currency).Select(g => new { currency = g.Key, debit = g.Sum(x => x.Debit), credit = g.Sum(x => x.Credit), balanced = g.Sum(x => x.Debit) == g.Sum(x => x.Credit) }).ToList();
            var stale = DateTime.UtcNow.AddHours(-24);
            return Results.Ok(new
            {
                awaitingReconciliation = pays.Where(x => x.Status == PaymentStatus.Confirmed && !x.Reconciled).Select(PayDto),
                selfReported = pays.Where(x => x.Status == PaymentStatus.Confirmed && !x.Verified).Select(PayDto),
                stuckInitiated = pays.Where(x => x.Status == PaymentStatus.Initiated && x.InitiatedAt < stale).Select(PayDto),
                trialBalance = trial, balanceCheck = balanced
            });
        });

        // ======== Technician: own earnings, direct-payment acknowledgement, disputes ========
        async Task<Technician?> MyTech(AppDbContext db, ClaimsPrincipal p, CancellationToken ct) { var uid = Uid(p); return await db.Technicians.FirstOrDefaultAsync(t => t.UserId == uid, ct); }

        api.MapGet("/technicians/me/payables", async Task<IResult> (ClaimsPrincipal p, AppDbContext db, CancellationToken ct) =>
        {
            var t = await MyTech(db, p, ct); if (t is null) return Results.NotFound();
            var rows = await (from x in db.Payables join j in db.Jobs on x.JobId equals j.Id join c in db.Companies on x.CompanyId equals c.Id where x.TechnicianId == t.Id && x.Status != "Cancelled" select new { x, j.Reference, company = c.DisplayName }).ToListAsync(ct);
            var list = new List<object>();
            foreach (var row in rows.OrderByDescending(r0 => r0.x.CreatedAt))
            {
                var pays = await db.Payments.Where(y => y.PayableId == row.x.Id).ToListAsync(ct);
                var s = FinanceMath.Settle(row.x.Amount, pays);
                list.Add(new { row.x.Id, jobReference = row.Reference, row.company, row.x.PayerType, row.x.Currency, row.x.Amount, status = row.x.Status, paid = s.Paid, outstanding = s.Outstanding, settlement = s.State, row.x.CreatedAt,
                    payments = pays.Where(y => y.Status == PaymentStatus.Confirmed).Select(y => new { y.Reference, y.Method, y.Amount, y.ConfirmedAt, y.Verified, y.Reconciled }) });
            }
            return Results.Ok(list);
        });

        api.MapPost("/technicians/me/payables/{pid:guid}/acknowledge", async Task<IResult> (Guid pid, AckReq r, ClaimsPrincipal p, AppDbContext db, IConfiguration cfg, HttpContext http, CancellationToken ct) =>
        {
            var uid = Uid(p);
            return await Guard(() => Idem.RunAsync(db, http, $"tech-ack:{uid}", async () =>
            {
                var t = await MyTech(db, p, ct); if (t is null) return (404, new { error = "Not found." });
                var x = await db.Payables.FirstOrDefaultAsync(y => y.Id == pid && y.TechnicianId == t.Id, ct); if (x is null) return (404, new { error = "Not found." });
                if (x.PayerType != "customer") return (409, new { error = "This job is paid by the company; the company records and confirms that payment." });
                if (x.Status != "Approved") return (409, new { error = $"The payable is {x.Status}." });
                var method = (r.Method ?? "cash").Trim().ToLowerInvariant();
                if (!Methods(cfg).Contains(method)) return (400, new { error = "method must be one of: " + string.Join(", ", Methods(cfg)) });
                if (!Money.Valid(r.Amount)) return (400, new { error = "amount must be positive with at most 4 decimals." });
                var providerRef = string.IsNullOrWhiteSpace(r.ProviderRef) ? null : r.ProviderRef.Trim();
                var existing = await db.Payments.Where(y => y.PayableId == pid).ToListAsync(ct);
                var committed = existing.Where(y => y.Status is PaymentStatus.Initiated or PaymentStatus.Confirmed).Sum(y => y.Amount);
                if (committed + r.Amount > x.Amount) return (409, new { error = $"That would exceed the agreed amount: {x.Amount - committed} {x.Currency} remains." });
                if (providerRef is not null && await db.Payments.AnyAsync(y => y.CompanyId == x.CompanyId && y.Method == method && y.ProviderRef == providerRef, ct)) return (409, new { error = "This reference is already recorded." });
                x.Seq++;
                var pay = new PaymentRecord { CompanyId = x.CompanyId, JobId = x.JobId, PayableId = pid, Reference = FinanceFlow.NewPaymentRef(), Kind = "direct_customer_to_technician", PayerType = "customer", PayeeType = "technician",
                    Method = method, Currency = x.Currency, Amount = r.Amount, ProviderRef = providerRef, AcknowledgedBy = t.DisplayName, Note = r.Note?.Trim(), Status = PaymentStatus.Confirmed, Verified = false,
                    RecordedBy = uid, ConfirmedBy = uid, ConfirmedAt = DateTime.UtcNow };
                db.Payments.Add(pay);
                db.PaymentEvents.Add(new PaymentEvent { PaymentId = pay.Id, Event = "acknowledged_by_payee", ActorUserId = uid, Note = "Self-reported by the technician; not independently verified." });
                await Notifier.NotifyHoldersAsync(db, x.CompanyId, "finance.reconcile", "finance.direct_payment_reported", "Direct payment reported", $"A technician reported receiving {r.Amount} {x.Currency} directly from a customer. Please reconcile.", ct);
                db.Audit(http, uid, "finance.direct_payment_acknowledged", "payment", pay.Id.ToString(), x.CompanyId, new { r.Amount, x.Currency, method });
                return (201, PayDto(pay));
            }, ct));
        });

        api.MapPost("/technicians/me/payables/{pid:guid}/dispute", async Task<IResult> (Guid pid, DisputeReq r, ClaimsPrincipal p, AppDbContext db, HttpContext http, CancellationToken ct) =>
            await Guard(async () =>
            {
                var uid = Uid(p);
                var t = await MyTech(db, p, ct); if (t is null) return Results.NotFound();
                var x = await db.Payables.FirstOrDefaultAsync(y => y.Id == pid && y.TechnicianId == t.Id, ct); if (x is null) return Results.NotFound();
                if (string.IsNullOrWhiteSpace(r.Description) || r.Description.Length > 2000) return Bad("description is required (max 2000).");
                if (await OpenDispute(db, pid, ct)) return Err(409, "There is already an open dispute on this payment.");
                var dsp = new Dispute { CompanyId = x.CompanyId, JobId = x.JobId, PayableId = pid, RaisedBy = uid, Description = r.Description.Trim() };
                db.Disputes.Add(dsp);
                await Notifier.NotifyHoldersAsync(db, x.CompanyId, "finance.adjust", "finance.dispute_raised", "Dispute raised", $"{t.DisplayName} disputed a payment.", ct);
                db.Audit(http, uid, "finance.dispute_raised", "dispute", dsp.Id.ToString(), x.CompanyId);
                await db.SaveChangesAsync(ct);
                return Results.Created($"/technicians/me/payables/{pid}/dispute/{dsp.Id}", new { dsp.Id, dsp.Status });
            }));

        // ======== Platform finance: platform fees ========
        api.MapGet("/platform/fees", async Task<IResult> (string? status, ClaimsPrincipal p, AppDbContext db, AccessService access, CancellationToken ct) =>
        {
            if (!await access.HasPlatform(Uid(p), "platform.finance", ct)) return Forbidden();
            var q = from f in db.PlatformFees join c in db.Companies on f.CompanyId equals c.Id join j in db.Jobs on f.JobId equals j.Id select new { f, company = c.DisplayName, j.Reference };
            if (status is not null) q = q.Where(x => x.f.Status == status);
            var rows = await q.OrderByDescending(x => x.f.CreatedAt).Take(200).ToListAsync(ct);
            return Results.Ok(rows.Select(x => new { x.f.Id, x.f.CompanyId, x.company, jobReference = x.Reference, x.f.Currency, x.f.Amount, x.f.Status, x.f.CreatedAt, x.f.DecidedAt, x.f.Note }));
        });

        api.MapPost("/platform/fees/{fid:guid}/decision", async Task<IResult> (Guid fid, FinDecisionReq r, ClaimsPrincipal p, AppDbContext db, AccessService access, HttpContext http, CancellationToken ct) =>
            await Guard(async () =>
            {
                var uid = Uid(p);
                if (!await access.HasPlatform(uid, "platform.finance", ct)) return Forbidden();
                if (r.Decision is not ("settle" or "waive")) return Bad("decision must be settle or waive.");
                if (r.Decision == "waive" && string.IsNullOrWhiteSpace(r.Note)) return Bad("note is required when waiving.");
                var f = await db.PlatformFees.FirstOrDefaultAsync(x => x.Id == fid, ct); if (f is null) return Results.NotFound();
                if (f.Status != "Accrued") return Err(409, $"This fee is {f.Status}.");
                f.Status = r.Decision == "settle" ? "Settled" : "Waived"; f.DecidedBy = uid; f.DecidedAt = DateTime.UtcNow; f.Note = r.Note?.Trim();
                // Settled = the company's payment of the fee was received (outside this system); waived = the fee is written off.
                Ledger.Post(db, f.CompanyId, $"fee-{r.Decision}:{f.Id}", f.Currency, "platform_fee", f.Id.ToString(), uid,
                    new Line(Acct.PlatformFeesPayable, f.Amount, 0), new Line(r.Decision == "settle" ? Acct.Cash : Acct.PlatformFeeExpense, 0, f.Amount));
                db.Audit(http, uid, "finance.platform_fee_" + r.Decision, "platform_fee", f.Id.ToString(), f.CompanyId, new { f.Amount, f.Currency });
                await db.SaveChangesAsync(ct);
                return Results.Ok(new { f.Id, f.Status });
            }));
    }
}
