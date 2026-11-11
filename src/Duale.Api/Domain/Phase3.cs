namespace Duale.Api.Domain;

public enum ReviewStatus { Pending, Approved, Rejected }

public class JobEvidence
{
    public Guid Id { get; set; } = Guid.NewGuid();
    public Guid JobId { get; set; }
    public Guid AssignmentId { get; set; }
    public string Kind { get; set; } = "";             // before | progress | after | other
    public string FileName { get; set; } = "";
    public string ContentType { get; set; } = "";       // sniffed from the bytes
    public long SizeBytes { get; set; }
    public string Sha256 { get; set; } = "";
    public string StorageKey { get; set; } = "";
    public Guid UploadedBy { get; set; }
    public DateTime UploadedAt { get; set; } = DateTime.UtcNow;
}

// One row per submission; after "returned for correction" the technician submits a new version.
public class JobWorkReport
{
    public Guid Id { get; set; } = Guid.NewGuid();
    public Guid JobId { get; set; }
    public Guid AssignmentId { get; set; }
    public int Version { get; set; }
    public string Summary { get; set; } = "";
    public decimal? HoursWorked { get; set; }
    public Guid SubmittedBy { get; set; }
    public DateTime SubmittedAt { get; set; } = DateTime.UtcNow;
}

public class JobScopeChange
{
    public Guid Id { get; set; } = Guid.NewGuid();
    public Guid JobId { get; set; }
    public Guid AssignmentId { get; set; }
    public string Description { get; set; } = "";
    public ReviewStatus Status { get; set; } = ReviewStatus.Pending;
    public Guid RequestedBy { get; set; }
    public Guid? DecidedBy { get; set; }
    public string? DecisionNote { get; set; }
    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
    public DateTime? DecidedAt { get; set; }
}

public class JobReview
{
    public Guid Id { get; set; } = Guid.NewGuid();
    public Guid JobId { get; set; }
    public Guid? ReportId { get; set; }
    public Guid ReviewerUserId { get; set; }
    public string Decision { get; set; } = "";          // Approved | Returned
    public string? Note { get; set; }
    public DateTime At { get; set; } = DateTime.UtcNow;
}

public class JobComplaint
{
    public Guid Id { get; set; } = Guid.NewGuid();
    public Guid JobId { get; set; }
    public Guid CompanyId { get; set; }
    public Guid RaisedBy { get; set; }
    public string Description { get; set; } = "";
    public string Status { get; set; } = "Open";        // Open | Resolved
    public string? Resolution { get; set; }
    public Guid? ResolvedBy { get; set; }
    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
    public DateTime? ResolvedAt { get; set; }
}

// Links a follow-up (callback) job to the job it repairs.
public class JobRelationship
{
    public Guid Id { get; set; } = Guid.NewGuid();
    public Guid ParentJobId { get; set; }
    public Guid ChildJobId { get; set; }
    public string Type { get; set; } = "callback";
    public string ReworkResponsibility { get; set; } = "undetermined";   // technician | company | customer | undetermined
    public bool UnderWarranty { get; set; }
    public string? Notes { get; set; }
    public Guid? ComplaintId { get; set; }
    public Guid CreatedBy { get; set; }
    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
}

// Remembers the outcome of a request that carried an Idempotency-Key so a retry (flaky mobile network) is safe.
public class IdempotencyRecord
{
    public Guid Id { get; set; } = Guid.NewGuid();
    public string Scope { get; set; } = "";
    public string Key { get; set; } = "";
    public int ResponseStatus { get; set; }
    public string? ResponseBody { get; set; }
    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
}
