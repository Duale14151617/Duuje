using System.Text.Json;
using Duale.Api.Data;
using Duale.Api.Domain;
using Microsoft.EntityFrameworkCore;
namespace Duale.Api.Services;

// Wraps a state-changing request. With an `Idempotency-Key` header the first outcome is stored in the SAME save as the
// change itself, so a retry (e.g. after a dropped mobile connection) replays the stored response and never repeats the effect.
// The action must change the DbContext but NOT call SaveChanges; this helper does that once.
public static class Idem
{
    static readonly JsonSerializerOptions Json = new(JsonSerializerDefaults.Web);

    public static async Task<IResult> RunAsync(AppDbContext db, HttpContext http, string scope, Func<Task<(int Status, object? Body)>> action, CancellationToken ct)
    {
        var key = http.Request.Headers["Idempotency-Key"].ToString().Trim();
        if (key.Length > 100) return Results.BadRequest(new { error = "Idempotency-Key is too long." });
        if (key.Length > 0)
        {
            var existing = await db.IdempotencyRecords.AsNoTracking().FirstOrDefaultAsync(r => r.Scope == scope && r.Key == key, ct);
            if (existing is not null) return Replay(existing.ResponseStatus, existing.ResponseBody);
        }
        var (status, body) = await action();
        var text = body is null ? null : JsonSerializer.Serialize(body, Json);
        if (key.Length > 0 && status < 500) db.IdempotencyRecords.Add(new IdempotencyRecord { Scope = scope, Key = key, ResponseStatus = status, ResponseBody = text });
        try { await db.SaveChangesAsync(ct); }
        catch (DbUpdateException) when (key.Length > 0)
        {
            return Results.Conflict(new { error = "A request with this Idempotency-Key is already being processed." });
        }
        return Replay(status, text);
    }

    static IResult Replay(int status, string? body) =>
        body is null ? Results.StatusCode(status) : Results.Text(body, "application/json", null, status);
}
