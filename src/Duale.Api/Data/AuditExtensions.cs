using System.Text.Json;
using Duale.Api.Domain;
namespace Duale.Api.Data;

public static class AuditExtensions
{
    // Adds to the current unit of work so the audit row commits atomically with the change it describes.
    public static void Audit(this AppDbContext db, HttpContext http, Guid? actor, string action, string type, string id,
        Guid? companyId = null, object? meta = null) =>
        db.AuditEvents.Add(new AuditEvent
        {
            ActorUserId = actor, Action = action, ResourceType = type, ResourceId = id, CompanyId = companyId,
            CorrelationId = http.TraceIdentifier, Metadata = meta is null ? null : JsonSerializer.Serialize(meta)
        });
}
