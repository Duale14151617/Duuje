namespace Duale.Api.Domain;

public class Branch
{
    public Guid Id { get; set; } = Guid.NewGuid();
    public Guid CompanyId { get; set; }
    public string Name { get; set; } = "";
    public string? Address { get; set; }
    public AccountStatus Status { get; set; } = AccountStatus.Active;   // Suspended = closed; history is kept
    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
}

// Which branches a staff member may work in. No rows = company-wide access (decision for the business to confirm).
public class BranchMembership { public Guid MembershipId { get; set; } public Guid BranchId { get; set; } }

public class ServiceArea { public Guid Id { get; set; } = Guid.NewGuid(); public string Name { get; set; } = ""; public bool Active { get; set; } = true; }
public class TechnicianServiceArea { public Guid TechnicianId { get; set; } public Guid ServiceAreaId { get; set; } }

public class TechnicianDocument
{
    public Guid Id { get; set; } = Guid.NewGuid();
    public Guid TechnicianId { get; set; }
    public string Kind { get; set; } = "";              // identity | qualification | other
    public string FileName { get; set; } = "";          // display only; never used as a path
    public string ContentType { get; set; } = "";       // sniffed from the bytes, not trusted from the client
    public long SizeBytes { get; set; }
    public string Sha256 { get; set; } = "";
    public string StorageKey { get; set; } = "";        // random; resolved only inside the file store
    public VerificationStatus Status { get; set; } = VerificationStatus.Pending;
    public string? ReviewNote { get; set; }
    public Guid? ReviewedBy { get; set; }
    public DateTime? ReviewedAt { get; set; }
    public DateOnly? ExpiresOn { get; set; }
    public DateTime UploadedAt { get; set; } = DateTime.UtcNow;
}

public class MfaRecoveryCode { public Guid Id { get; set; } = Guid.NewGuid(); public Guid UserId { get; set; } public string CodeHash { get; set; } = ""; public DateTime? UsedAt { get; set; } }
public class PasswordResetToken
{
    public Guid Id { get; set; } = Guid.NewGuid();
    public Guid UserId { get; set; }
    public string TokenHash { get; set; } = "";         // only the hash is stored
    public DateTime ExpiresAt { get; set; }
    public DateTime? UsedAt { get; set; }
    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
}
