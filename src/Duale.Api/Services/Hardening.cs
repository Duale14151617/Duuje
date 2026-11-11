using System.Diagnostics;
using System.Security.Claims;
using Duale.Api.Auth;
using System.Net.Sockets;
using System.Text;
using Duale.Api.Data;
using Duale.Api.Domain;
using Microsoft.EntityFrameworkCore;
namespace Duale.Api.Services;

// ---------- Response hardening, correlation and request metrics ----------
public static class Telemetry
{
    static long _total, _s2xx, _s3xx, _s4xx, _s5xx, _inflight, _limited;
    static readonly long[] Buckets = new long[8];
    static readonly double[] Bounds = [0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, double.MaxValue];
    static double _sumSeconds;
    static readonly object Gate = new();

    public static void Begin() => Interlocked.Increment(ref _inflight);
    public static void End(int status, double seconds)
    {
        Interlocked.Decrement(ref _inflight); Interlocked.Increment(ref _total);
        if (status == 429) Interlocked.Increment(ref _limited);
        if (status >= 500) Interlocked.Increment(ref _s5xx); else if (status >= 400) Interlocked.Increment(ref _s4xx); else if (status >= 300) Interlocked.Increment(ref _s3xx); else Interlocked.Increment(ref _s2xx);
        lock (Gate) { _sumSeconds += seconds; for (var i = 0; i < Bounds.Length; i++) if (seconds <= Bounds[i]) { Buckets[i]++; break; } }
    }

    public static string Render(Dictionary<string, long> gauges)
    {
        var sb = new StringBuilder();
        void M(string name, string type, string help, long v) => sb.Append($"# HELP {name} {help}\n# TYPE {name} {type}\n{name} {v}\n");
        M("duale_http_requests_total", "counter", "Requests handled", Interlocked.Read(ref _total));
        M("duale_http_responses_5xx_total", "counter", "Server errors", Interlocked.Read(ref _s5xx));
        M("duale_http_responses_4xx_total", "counter", "Client errors", Interlocked.Read(ref _s4xx));
        M("duale_http_rate_limited_total", "counter", "Requests rejected by rate limiting", Interlocked.Read(ref _limited));
        M("duale_http_inflight", "gauge", "Requests in flight", Interlocked.Read(ref _inflight));
        lock (Gate)
        {
            sb.Append("# TYPE duale_http_request_seconds histogram\n");
            long cum = 0;
            for (var i = 0; i < Bounds.Length; i++) { cum += Buckets[i]; sb.Append($"duale_http_request_seconds_bucket{{le=\"{(i == Bounds.Length - 1 ? "+Inf" : Bounds[i].ToString(System.Globalization.CultureInfo.InvariantCulture))}\"}} {cum}\n"); }
            sb.Append($"duale_http_request_seconds_sum {_sumSeconds.ToString(System.Globalization.CultureInfo.InvariantCulture)}\nduale_http_request_seconds_count {cum}\n");
        }
        foreach (var (k, v) in gauges) M(k, "gauge", k.Replace('_', ' '), v);
        return sb.ToString();
    }
}

public static class Hardening
{
    public static void Use(WebApplication app)
    {
        var serveSpa = app.Configuration["Web:ServeSpa"] == "true";
        app.Use(async (ctx, next) =>
        {
            var sw = Stopwatch.StartNew();
            Telemetry.Begin();
            ctx.Response.OnStarting(() =>
            {
                var h = ctx.Response.Headers;
                h["X-Content-Type-Options"] = "nosniff"; h["X-Frame-Options"] = "DENY"; h["Referrer-Policy"] = "no-referrer";
                // API responses get the strictest policy. The app shell and its static files (only when Web:ServeSpa=true) need to load their own scripts.
                var spa = serveSpa && !ctx.Request.PathBase.HasValue && (ctx.Request.Path == "/index.html" || Path.HasExtension(ctx.Request.Path.Value));
                h["Content-Security-Policy"] = spa
                    ? "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; object-src 'self' blob:; frame-src blob:; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
                    : "default-src 'none'; frame-ancestors 'none'";
                h["Permissions-Policy"] = "geolocation=(), camera=(), microphone=()";
                h["Cache-Control"] = !spa ? "no-store" : ctx.Request.Path.StartsWithSegments("/assets") ? "public, max-age=31536000, immutable" : "no-cache";
                h["X-Correlation-Id"] = ctx.TraceIdentifier;
                return Task.CompletedTask;
            });
            try { await next(); }
            finally { Telemetry.End(ctx.Response.StatusCode, sw.Elapsed.TotalSeconds); }
        });
    }

    // Sends nothing identifying; only requests carrying the configured token may scrape. No token configured = endpoint does not exist.
    public static void MapOps(WebApplication app)
    {
        app.MapGet("/health/live", () => Results.Ok(new { status = "live" }));
        app.MapGet("/health/ready", async Task<IResult> (AppDbContext db, IConfiguration cfg, CancellationToken ct) =>
        {
            var problems = new List<string>();
            try { if (!await db.Database.CanConnectAsync(ct)) problems.Add("database"); } catch { problems.Add("database"); }
            try { if (problems.Count == 0 && (await db.Database.GetPendingMigrationsAsync(ct)).Any()) problems.Add("pending migrations"); } catch { /* in-memory/test providers have no migrations */ }
            var root = cfg["Files:Root"];
            if (!string.IsNullOrEmpty(root)) { try { Directory.CreateDirectory(root); var probe = Path.Combine(root, ".ready-" + Guid.NewGuid().ToString("N")); await File.WriteAllTextAsync(probe, "x", ct); File.Delete(probe); } catch { problems.Add("file storage"); } }
            return problems.Count == 0 ? Results.Ok(new { status = "ready" }) : Results.Json(new { status = "not ready", problems }, statusCode: 503);
        });
        app.MapGet("/metrics", async Task<IResult> (HttpRequest req, AppDbContext db, IConfiguration cfg, CancellationToken ct) =>
        {
            var token = cfg["Metrics:Token"];
            if (string.IsNullOrEmpty(token) || token.Length < 16) return Results.NotFound();
            if (req.Headers.Authorization.ToString() != "Bearer " + token) return Results.NotFound();
            var now = DateTime.UtcNow; var stale = now.AddHours(-24);
            var g = new Dictionary<string, long>
            {
                ["duale_notification_deliveries_pending"] = await db.Deliveries.CountAsync(x => x.Status == "Pending", ct),
                ["duale_notification_deliveries_dead"] = await db.Deliveries.CountAsync(x => x.Status == "Dead", ct),
                ["duale_notifications_not_fanned_out"] = await db.Notifications.CountAsync(x => x.FannedOutAt == null, ct),
                ["duale_payments_initiated_over_24h"] = await db.Payments.CountAsync(x => x.Status == PaymentStatus.Initiated && x.InitiatedAt < stale, ct),
                ["duale_payments_confirmed_unreconciled"] = await db.Payments.CountAsync(x => x.Status == PaymentStatus.Confirmed && !x.Reconciled, ct),
                ["duale_outbox_pending"] = await db.OutboxEvents.CountAsync(x => x.Status == "Pending", ct),
                ["duale_outbox_dead"] = await db.OutboxEvents.CountAsync(x => x.Status == "Dead", ct),
                ["duale_disputes_open"] = await db.Disputes.CountAsync(x => x.Status == "Open", ct),
                ["duale_verification_queue_companies"] = await db.Companies.CountAsync(x => x.Verification == VerificationStatus.Pending, ct),
                ["duale_verification_queue_documents"] = await db.TechnicianDocuments.CountAsync(x => x.Status == VerificationStatus.Pending, ct),
            };
            return Results.Text(Telemetry.Render(g), "text/plain; version=0.0.4");
        });
        // Consistency checks over the whole database: run after every restore and on a schedule. Findings are ids only.
        app.MapGet("/platform/integrity", async Task<IResult> (ClaimsPrincipal p, AccessService access, IntegrityService svc, CancellationToken ct) =>
        {
            if (!await access.HasPlatform(Guid.Parse(p.FindFirstValue("sub")!), "platform.oversight", ct)) return Results.StatusCode(403);
            var f = await svc.RunAsync(ct);
            return Results.Ok(new { ok = f.Count == 0, count = f.Count, findings = f.Take(200) });
        }).RequireAuthorization();
    }
}

// ---------- Upload scanning: ClamAV over its TCP INSTREAM protocol. Fails closed. ----------
public class ClamAvScanner(IConfiguration cfg, ILogger<ClamAvScanner> log) : IUploadScanner
{
    public async Task<bool> IsCleanAsync(byte[] data, CancellationToken ct)
    {
        try
        {
            using var cts = CancellationTokenSource.CreateLinkedTokenSource(ct); cts.CancelAfter(TimeSpan.FromSeconds(20));
            using var client = new TcpClient();
            await client.ConnectAsync(cfg["Scanner:ClamAv:Host"]!, int.TryParse(cfg["Scanner:ClamAv:Port"], out var p) ? p : 3310, cts.Token);
            var s = client.GetStream();
            await s.WriteAsync(Encoding.ASCII.GetBytes("zINSTREAM\0"), cts.Token);
            for (var off = 0; off < data.Length; off += 8192)
            {
                var n = Math.Min(8192, data.Length - off);
                await s.WriteAsync(BitConverter.GetBytes(System.Net.IPAddress.HostToNetworkOrder(n)), cts.Token);
                await s.WriteAsync(data.AsMemory(off, n), cts.Token);
            }
            await s.WriteAsync(new byte[4], cts.Token);
            var buf = new byte[256]; var read = await s.ReadAsync(buf, cts.Token);
            var reply = Encoding.ASCII.GetString(buf, 0, read).TrimEnd('\0', '\n');
            if (reply.EndsWith("OK")) return true;
            if (reply.Contains("FOUND")) log.LogWarning("Upload rejected by scanner: {Reply}", reply);
            else log.LogError("Scanner returned an unexpected reply: {Reply}", reply);
            return false;
        }
        catch (Exception ex) when (ex is not OperationCanceledException || !ct.IsCancellationRequested)
        {
            log.LogError(ex, "Scanner unavailable; rejecting the upload (fail closed).");
            return false;
        }
    }
}

// ---------- Retention (only what is safe without a business decision; everything else is configuration) ----------
public class RetentionService(AppDbContext db, IConfiguration cfg)
{
    public async Task<int> PurgeAsync(DateTime now, CancellationToken ct)
    {
        // Must outlast the longest time a phone may stay offline before replaying a queued request.
        var days = int.TryParse(cfg["Retention:IdempotencyDays"], out var d) && d > 0 ? d : 14;
        var cutoff = now.AddDays(-days);
        return await db.IdempotencyRecords.Where(x => x.CreatedAt < cutoff).ExecuteDeleteAsync(ct);
    }
}

// ---------- Integrity checks: run after a restore, after incidents, and on a schedule ----------
public record Finding(string Check, string Detail);

public class IntegrityService(AppDbContext db)
{
    public async Task<List<Finding>> RunAsync(CancellationToken ct)
    {
        var f = new List<Finding>();
        var ledger = await db.Ledger.Select(e => new { e.CompanyId, e.TxnKey, e.Currency, e.Debit, e.Credit }).ToListAsync(ct);
        foreach (var g in ledger.GroupBy(e => (e.CompanyId, e.TxnKey, e.Currency)).Where(g => g.Sum(x => x.Debit) != g.Sum(x => x.Credit)))
            f.Add(new("ledger_balanced", $"Posting {g.Key.TxnKey} (company {g.Key.CompanyId}) is unbalanced in {g.Key.Currency}."));

        var confirmed = await db.Payments.Where(p => p.Status == PaymentStatus.Confirmed && p.Kind != "direct_customer_to_technician").Select(p => new { p.Id, p.CompanyId }).ToListAsync(ct);
        var posted = (await db.Ledger.Where(e => e.TxnKey.StartsWith("pay-confirm:")).Select(e => e.TxnKey).Distinct().ToListAsync(ct)).ToHashSet();
        foreach (var p in confirmed.Where(p => !posted.Contains($"pay-confirm:{p.Id}"))) f.Add(new("payment_posted", $"Confirmed payment {p.Id} has no ledger posting."));

        var reversed = await db.Payments.Where(p => p.Status == PaymentStatus.Reversed && p.Kind != "direct_customer_to_technician").Select(p => p.Id).ToListAsync(ct);
        var reversals = (await db.Ledger.Where(e => e.TxnKey.StartsWith("pay-reverse:")).Select(e => e.TxnKey).Distinct().ToListAsync(ct)).ToHashSet();
        foreach (var id in reversed.Where(id => !reversals.Contains($"pay-reverse:{id}"))) f.Add(new("payment_reversal_posted", $"Reversed payment {id} has no reversal posting."));

        var invoices = await db.Invoices.Where(i => i.Status != "Void").Select(i => new { i.Id, i.Total }).ToListAsync(ct);
        var lines = (await db.InvoiceLines.Select(l => new { l.InvoiceId, l.Amount }).ToListAsync(ct)).GroupBy(l => l.InvoiceId).ToDictionary(g => g.Key, g => g.Sum(x => x.Amount));
        foreach (var i in invoices.Where(i => !lines.TryGetValue(i.Id, out var s) || s != i.Total)) f.Add(new("invoice_lines", $"Invoice {i.Id} lines do not add up to its total."));

        var money = await db.Payments.Where(p => p.Status == PaymentStatus.Confirmed || p.Status == PaymentStatus.Initiated).Select(p => new { p.Id, p.InvoiceId, p.PayableId, p.RefundId, p.Amount }).ToListAsync(ct);
        foreach (var g in money.Where(p => p.InvoiceId != null).GroupBy(p => p.InvoiceId!.Value))
        { var inv = await db.Invoices.Where(i => i.Id == g.Key).Select(i => i.Total).FirstAsync(ct); if (g.Sum(x => x.Amount) > inv) f.Add(new("overpaid_invoice", $"Invoice {g.Key} has more payments than its total.")); }
        foreach (var g in money.Where(p => p.PayableId != null).GroupBy(p => p.PayableId!.Value))
        { var amt = await db.Payables.Where(i => i.Id == g.Key).Select(i => i.Amount).FirstAsync(ct); if (g.Sum(x => x.Amount) > amt) f.Add(new("overpaid_payable", $"Payable {g.Key} has more payments than its amount.")); }

        var live = (await db.Assignments.Where(a => a.Status == AssignmentStatus.Offered || a.Status == AssignmentStatus.Accepted).Select(a => a.JobId).ToListAsync(ct)).GroupBy(x => x).Where(g => g.Count() > 1);
        foreach (var g in live) f.Add(new("one_live_assignment", $"Job {g.Key} has several live assignments."));

        foreach (var j in await db.Jobs.Where(j => j.Status == JobStatus.Completed && j.CompletedAt == null).Select(j => j.Reference).ToListAsync(ct)) f.Add(new("completed_has_timestamp", $"Job {j} is Completed without a completion time."));
        var completedNoHist = await db.Jobs.Where(j => j.Status != JobStatus.Open).Select(j => new { j.Id, j.Reference }).ToListAsync(ct);
        var withHist = (await db.JobStatusHistory.Select(h => h.JobId).Distinct().ToListAsync(ct)).ToHashSet();
        foreach (var j in completedNoHist.Where(j => !withHist.Contains(j.Id))) f.Add(new("status_history", $"Job {j.Reference} has no status history."));

        return f;
    }
}
