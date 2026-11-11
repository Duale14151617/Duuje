using Duale.Api.Data;
using Duale.Api.Domain;
using Microsoft.EntityFrameworkCore;
namespace Duale.Api.Services;

public static class Acct
{
    public const string Cash = "1000", Receivable = "1100", TechPayable = "2100", PlatformFeesPayable = "2200",
        Revenue = "4000", Refunds = "4900", TechExpense = "5000", PlatformFeeExpense = "5100";
}

public static class Money
{
    public const decimal Max = 999_999_999_999m;
    // Positive, at most 4 decimal places (matches NUMERIC(19,4)); never floating point.
    public static bool Valid(decimal v) => v > 0 && v <= Max && Math.Round(v, 4) == v;
    public static bool ValidOrZero(decimal v) => v == 0 || Valid(v);
    public static string? Currency(IConfiguration cfg, string? c)
    {
        var code = c?.Trim().ToUpperInvariant();
        var allowed = (cfg["Finance:AllowedCurrencies"] ?? "USD").Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries).Select(x => x.ToUpperInvariant());
        return code is { Length: 3 } && allowed.Contains(code) ? code : null;
    }
    // Amounts at or below this may be approved by the person who proposed them. Default 0 = separation of duties always.
    public static decimal SelfApprovalLimit(IConfiguration cfg) => decimal.TryParse(cfg["Finance:SelfApprovalLimit"], System.Globalization.NumberStyles.Number, System.Globalization.CultureInfo.InvariantCulture, out var v) ? v : 0m;
}

public record Line(string Account, decimal Debit, decimal Credit);

public static class Ledger
{
    // Adds one balanced posting to the unit of work. Duplicate postings fail on the unique LineKey.
    public static void Post(AppDbContext db, Guid companyId, string txnKey, string currency, string sourceType, string sourceId, Guid? actor, params Line[] lines)
    {
        if (lines.Length < 2) throw new InvalidOperationException("A posting needs at least two lines.");
        if (lines.Any(l => l.Debit < 0 || l.Credit < 0 || (l.Debit == 0) == (l.Credit == 0))) throw new InvalidOperationException("Each line must be a single positive debit or credit.");
        if (lines.Sum(l => l.Debit) != lines.Sum(l => l.Credit)) throw new InvalidOperationException("Posting is not balanced.");
        for (var i = 0; i < lines.Length; i++)
            db.Ledger.Add(new LedgerEntry { CompanyId = companyId, TxnKey = txnKey, LineKey = $"{txnKey}#{i}", AccountCode = lines[i].Account, Debit = lines[i].Debit, Credit = lines[i].Credit,
                Currency = currency, SourceType = sourceType, SourceId = sourceId, ActorUserId = actor });
    }

    // Corrections are new entries with debit/credit swapped; the originals stay untouched.
    public static async Task ReverseAsync(AppDbContext db, Guid companyId, string originalTxnKey, string reversalTxnKey, string sourceType, string sourceId, Guid? actor, CancellationToken ct)
    {
        var originals = await db.Ledger.Where(e => e.CompanyId == companyId && e.TxnKey == originalTxnKey).OrderBy(e => e.LineKey).ToListAsync(ct);
        for (var i = 0; i < originals.Count; i++)
        {
            var o = originals[i];
            db.Ledger.Add(new LedgerEntry { CompanyId = companyId, TxnKey = reversalTxnKey, LineKey = $"{reversalTxnKey}#{i}", AccountCode = o.AccountCode, Debit = o.Credit, Credit = o.Debit,
                Currency = o.Currency, SourceType = sourceType, SourceId = sourceId, ReversesLineKey = o.LineKey, ActorUserId = actor });
        }
    }
}

public record Settlement(decimal Amount, decimal Paid, decimal Pending, decimal Outstanding, string State);

public static class FinanceMath
{
    // Open -> PartiallyPaid -> Paid (confirmed in full) -> Settled (and every confirmed payment reconciled).
    public static Settlement Settle(decimal amount, IEnumerable<PaymentRecord> payments)
    {
        var list = payments.ToList();
        var paid = list.Where(p => p.Status == PaymentStatus.Confirmed).Sum(p => p.Amount);
        var pending = list.Where(p => p.Status == PaymentStatus.Initiated).Sum(p => p.Amount);
        var allReconciled = list.Where(p => p.Status == PaymentStatus.Confirmed).All(p => p.Reconciled);
        var state = paid >= amount ? (allReconciled ? "Settled" : "Paid") : paid > 0 ? "PartiallyPaid" : pending > 0 ? "PaymentInitiated" : "Open";
        return new Settlement(amount, paid, pending, Math.Max(0, amount - paid), state);
    }
}

public static class FinanceFlow
{
    public static string NewPaymentRef() => $"P-{DateTime.UtcNow:yyMMdd}-{Guid.NewGuid().ToString("N")[..8].ToUpperInvariant()}";

    // Called when a job is approved (review) and when terms are approved after completion. Idempotent per job.
    // The financial workflow runs separately from the approval itself: it never blocks or undoes completion.
    public static async Task AccrueAsync(AppDbContext db, Job job, Guid actor, CancellationToken ct)
    {
        if (job.Status != JobStatus.Completed) return;
        var terms = await db.FinancialTerms.FirstOrDefaultAsync(t => t.JobId == job.Id && t.Status == TermsStatus.Approved, ct);
        if (terms is null)
        {
            await Notifier.NotifyHoldersAsync(db, job.CompanyId, "finance.terms.approve", "finance.terms_missing", "Financial terms needed",
                $"Job {job.Reference} is completed but has no approved financial terms, so no payable was created.", ct);
            return;
        }
        if (await db.Payables.AnyAsync(p => p.JobId == job.Id && p.Status != "Cancelled", ct)) return;
        var assignment = await db.Assignments.Where(a => a.JobId == job.Id && a.Status == AssignmentStatus.Accepted).OrderByDescending(a => a.OfferedAt).FirstOrDefaultAsync(ct);
        if (assignment is null) return;

        var payable = new TechnicianPayable
        {
            CompanyId = job.CompanyId, JobId = job.Id, TechnicianId = assignment.TechnicianId, TermsId = terms.Id, PayerType = terms.PayerType, Currency = terms.Currency,
            Amount = terms.TechnicianCompensation,
            Status = terms.PayerType == "customer" ? "Approved" : "Accrued"   // a direct payment needs no company finance approval; it is only tracked
        };
        db.Payables.Add(payable);
        if (terms.PlatformFee > 0 && !await db.PlatformFees.AnyAsync(f => f.JobId == job.Id, ct))
        {
            var fee = new PlatformFeeRecord { CompanyId = job.CompanyId, JobId = job.Id, Currency = terms.Currency, Amount = terms.PlatformFee };
            db.PlatformFees.Add(fee);
            Ledger.Post(db, job.CompanyId, $"fee-accrue:{fee.Id}", fee.Currency, "platform_fee", fee.Id.ToString(), actor,
                new Line(Acct.PlatformFeeExpense, fee.Amount, 0), new Line(Acct.PlatformFeesPayable, 0, fee.Amount));
        }
        var tech = await db.Technicians.FirstAsync(t => t.Id == assignment.TechnicianId, ct);
        Notifier.Notify(db, tech.UserId, job.CompanyId, "finance.payable_created", "Payment recorded for your job",
            terms.PayerType == "customer" ? $"Job {job.Reference}: the customer pays you directly {terms.TechnicianCompensation} {terms.Currency}." : $"Job {job.Reference}: {terms.TechnicianCompensation} {terms.Currency} is awaiting company payment approval.");
        if (terms.PayerType == "company")
            await Notifier.NotifyHoldersAsync(db, job.CompanyId, "finance.payment", "finance.payable_created", "Technician payable to review", $"Job {job.Reference} has a payable of {terms.TechnicianCompensation} {terms.Currency}.", ct);
    }
}
