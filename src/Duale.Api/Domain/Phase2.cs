namespace Duale.Api.Domain;

public enum RelationshipType { Employed, Independent }
public enum RelationshipStatus { Invited, Active, Suspended, Ended, Declined }
public enum JobStatus { Open, Offered, Accepted, EnRoute, Arrived, InProgress, AwaitingReview, Completed, ReturnedForCorrection, Cancelled, Disputed }
public enum JobPriority { Low, Normal, High, Urgent }
public enum AssignmentStatus { Offered, Accepted, Declined, Withdrawn, Reassigned, Cancelled }

// One row per technician/company pair; re-inviting after Ended/Declined reuses the row.
public class TechnicianCompanyRelationship
{
    public Guid Id { get; set; } = Guid.NewGuid();
    public Guid TechnicianId { get; set; }
    public Guid CompanyId { get; set; }
    public RelationshipType Type { get; set; }
    public RelationshipStatus Status { get; set; } = RelationshipStatus.Invited;
    public DateTime ValidFrom { get; set; } = DateTime.UtcNow;
    public DateTime? ValidTo { get; set; }
    public string? CompensationTermsRef { get; set; }   // filled in Phase 4 (finance)
    public Guid InvitedBy { get; set; }
    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
    public DateTime UpdatedAt { get; set; } = DateTime.UtcNow;
}

public class TechnicianAvailability
{
    public Guid Id { get; set; } = Guid.NewGuid();
    public Guid TechnicianId { get; set; }
    public DateTime StartsAt { get; set; }
    public DateTime EndsAt { get; set; }
}

public class Customer
{
    public Guid Id { get; set; } = Guid.NewGuid();
    public Guid CompanyId { get; set; }
    public string Name { get; set; } = "";
    public string Phone { get; set; } = "";
    public string? Email { get; set; }
    public string? ContactPreference { get; set; }
    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
}

public class ServiceLocation
{
    public Guid Id { get; set; } = Guid.NewGuid();
    public Guid CompanyId { get; set; }
    public Guid CustomerId { get; set; }
    public string Label { get; set; } = "";
    public string Address { get; set; } = "";
    public double? Latitude { get; set; }
    public double? Longitude { get; set; }
    public string? AccessInstructions { get; set; }
    public Guid? ServiceAreaId { get; set; }
}

public class Job
{
    public Guid Id { get; set; } = Guid.NewGuid();
    public string Reference { get; set; } = "";
    public Guid CompanyId { get; set; }
    public Guid CustomerId { get; set; }
    public Guid LocationId { get; set; }
    public Guid TradeId { get; set; }
    public string Description { get; set; } = "";
    public JobPriority Priority { get; set; } = JobPriority.Normal;
    public JobStatus Status { get; set; } = JobStatus.Open;
    public DateTime ScheduledStart { get; set; }
    public DateTime ScheduledEnd { get; set; }
    public Guid CreatedBy { get; set; }
    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
    public DateTime? CompletedAt { get; set; }
    public int? WarrantyDays { get; set; }              // set when the job is created; the business decides the terms
    public DateTime? WarrantyEndsAt { get; set; }       // computed when the work is approved
}

public class JobRequiredSkill { public Guid JobId { get; set; } public Guid SkillId { get; set; } }

// Every offer/assignment is kept; nothing is overwritten when work is reassigned.
public class JobAssignment
{
    public Guid Id { get; set; } = Guid.NewGuid();
    public Guid JobId { get; set; }
    public Guid TechnicianId { get; set; }
    public Guid RelationshipId { get; set; }
    public AssignmentStatus Status { get; set; } = AssignmentStatus.Offered;
    public Guid AssignedBy { get; set; }
    public DateTime ScheduledStart { get; set; }      // copied from the job so the DB can forbid overlaps
    public DateTime ScheduledEnd { get; set; }
    public DateTime OfferedAt { get; set; } = DateTime.UtcNow;
    public DateTime? RespondedAt { get; set; }
    public DateTime? EndedAt { get; set; }
    public string? Reason { get; set; }
}

public class JobStatusHistory
{
    public Guid Id { get; set; } = Guid.NewGuid();
    public Guid JobId { get; set; }
    public string? FromStatus { get; set; }           // null = creation
    public JobStatus ToStatus { get; set; }
    public Guid ActorUserId { get; set; }
    public string? Reason { get; set; }
    public DateTime At { get; set; } = DateTime.UtcNow;
}

public class Notification
{
    public Guid Id { get; set; } = Guid.NewGuid();
    public Guid UserId { get; set; }
    public Guid? CompanyId { get; set; }
    public string Kind { get; set; } = "";
    public string Title { get; set; } = "";
    public string Body { get; set; } = "";
    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
    public DateTime? ReadAt { get; set; }
    public string? DedupeKey { get; set; }              // reminders: the same reminder is never created twice
    public DateTime? FannedOutAt { get; set; }          // set once delivery rows for external channels were created
}

public static class JobRules
{
    static readonly Dictionary<JobStatus, JobStatus[]> Map = new()
    {
        [JobStatus.Open] = [JobStatus.Offered, JobStatus.Cancelled],
        [JobStatus.Offered] = [JobStatus.Accepted, JobStatus.Open, JobStatus.Offered, JobStatus.Cancelled],
        [JobStatus.Accepted] = [JobStatus.EnRoute, JobStatus.Offered, JobStatus.Open, JobStatus.Cancelled],
        [JobStatus.EnRoute] = [JobStatus.Arrived, JobStatus.Cancelled],
        [JobStatus.Arrived] = [JobStatus.InProgress, JobStatus.Cancelled],
        [JobStatus.InProgress] = [JobStatus.AwaitingReview, JobStatus.Cancelled, JobStatus.Disputed],
        [JobStatus.AwaitingReview] = [JobStatus.Completed, JobStatus.ReturnedForCorrection, JobStatus.Disputed],
        [JobStatus.ReturnedForCorrection] = [JobStatus.InProgress, JobStatus.Cancelled],
        [JobStatus.Completed] = [JobStatus.Disputed],
    };
    public static bool Allowed(JobStatus from, JobStatus to) => Map.TryGetValue(from, out var t) && t.Contains(to);
}
