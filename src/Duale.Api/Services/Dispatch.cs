using Duale.Api.Data;
using Duale.Api.Domain;
using Microsoft.EntityFrameworkCore;
namespace Duale.Api.Services;

public static class JobFlow
{
    // The only place a job's status changes: validates the transition and records history.
    public static void Move(AppDbContext db, Job job, JobStatus to, Guid actor, string? reason)
    {
        if (!JobRules.Allowed(job.Status, to)) throw new InvalidOperationException($"Illegal job transition {job.Status} -> {to}.");
        db.JobStatusHistory.Add(new JobStatusHistory { JobId = job.Id, FromStatus = job.Status.ToString(), ToStatus = to, ActorUserId = actor, Reason = reason });
        job.Status = to;
    }

    public static void Notify(AppDbContext db, Guid userId, Guid? companyId, string kind, string title, string body) =>
        Notifier.Notify(db, userId, companyId, kind, title, body);
}

public record Candidate(Guid TechnicianId, Guid RelationshipId, string Name, string RelationshipType, bool Eligible, int Score, List<string> Reasons, List<string> Blockers);

// Explainable matching: filters on hard rules, ranks on configurable weights. It only ever returns
// recommendations; creating an assignment is a separate, explicit action by authorised staff.
public class MatchingService(AppDbContext db, IConfiguration cfg)
{
    int EmployedBonus => int.TryParse(cfg["Matching:EmployedBonus"], out var v) ? v : 10;
    int SameDayPenalty => int.TryParse(cfg["Matching:SameDayJobPenalty"], out var v) ? v : 3;

    public async Task<List<Candidate>> EvaluateAsync(Job job, Guid? onlyTechnician, CancellationToken ct)
    {
        var required = await db.JobRequiredSkills.Where(x => x.JobId == job.Id).Select(x => x.SkillId).ToListAsync(ct);
        var skillNames = await db.Skills.Where(s => required.Contains(s.Id)).ToDictionaryAsync(s => s.Id, s => s.Name, ct);

        var rels = await (from r in db.Relationships
                          join t in db.Technicians on r.TechnicianId equals t.Id
                          where r.CompanyId == job.CompanyId && r.Status == RelationshipStatus.Active
                                && (onlyTechnician == null || t.Id == onlyTechnician)
                          select new { Rel = r, Tech = t }).ToListAsync(ct);
        var ids = rels.Select(x => x.Tech.Id).ToList();

        var skills = await db.TechnicianSkills.Where(s => ids.Contains(s.TechnicianId)).ToListAsync(ct);
        var available = await db.Availability
            .Where(a => ids.Contains(a.TechnicianId) && a.StartsAt <= job.ScheduledStart && a.EndsAt >= job.ScheduledEnd)
            .Select(a => a.TechnicianId).Distinct().ToListAsync(ct);
        var lo = job.ScheduledStart.Date.AddDays(-1); var hi = job.ScheduledEnd.Date.AddDays(2);
        var accepted = await db.Assignments
            .Where(a => ids.Contains(a.TechnicianId) && a.Status == AssignmentStatus.Accepted && a.JobId != job.Id && a.ScheduledStart < hi && a.ScheduledEnd > lo)
            .ToListAsync(ct);

        var areaId = await db.Locations.Where(l => l.Id == job.LocationId).Select(l => l.ServiceAreaId).FirstOrDefaultAsync(ct);
        var inArea = areaId is null ? new List<Guid>()
            : await db.TechnicianServiceAreas.Where(a => a.ServiceAreaId == areaId && ids.Contains(a.TechnicianId)).Select(a => a.TechnicianId).ToListAsync(ct);

        var day = DateOnly.FromDateTime(job.ScheduledStart);
        var result = new List<Candidate>();
        foreach (var x in rels)
        {
            var id = x.Tech.Id; var blockers = new List<string>(); var reasons = new List<string>();
            if (x.Tech.Status != AccountStatus.Active) blockers.Add("Technician account is not active.");
            if (x.Rel.ValidFrom > job.ScheduledStart || (x.Rel.ValidTo != null && x.Rel.ValidTo < job.ScheduledEnd))
                blockers.Add("Relationship is not valid for the scheduled time.");
            var missing = required.Where(rs => !skills.Any(s => s.TechnicianId == id && s.SkillId == rs && s.IsEligible(day)))
                                  .Select(rs => skillNames.GetValueOrDefault(rs, "unknown")).ToList();
            if (missing.Count > 0) blockers.Add("Missing or unverified skill: " + string.Join(", ", missing));
            if (areaId is not null && !inArea.Contains(id)) blockers.Add("Technician does not serve the job's service area.");
            if (!available.Contains(id)) blockers.Add("No availability window covers the scheduled time.");
            if (accepted.Any(a => a.TechnicianId == id && a.ScheduledStart < job.ScheduledEnd && a.ScheduledEnd > job.ScheduledStart))
                blockers.Add("Already has a confirmed job at that time.");

            var score = 0;
            if (blockers.Count == 0)
            {
                score = 50;
                reasons.Add("All required skills verified and current.");
                reasons.Add("Available for the whole scheduled window.");
                if (x.Rel.Type == RelationshipType.Employed) { score += EmployedBonus; reasons.Add($"Employed technician (+{EmployedBonus})."); }
                var sameDay = accepted.Count(a => a.TechnicianId == id && DateOnly.FromDateTime(a.ScheduledStart) == day);
                if (sameDay > 0) { score -= SameDayPenalty * sameDay; reasons.Add($"{sameDay} confirmed job(s) the same day (-{SameDayPenalty} each)."); }
            }
            result.Add(new Candidate(id, x.Rel.Id, x.Tech.DisplayName, x.Rel.Type.ToString(), blockers.Count == 0, score, reasons, blockers));
        }
        return result.OrderByDescending(c => c.Eligible).ThenByDescending(c => c.Score).ThenBy(c => c.Name).ToList();
    }
}
