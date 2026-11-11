namespace Duale.Api.Domain;

public enum AccountStatus { Active, Suspended }
public enum VerificationStatus { Pending, NeedsInfo, Approved, Rejected }
public enum MembershipStatus { Active, Removed }

public class User
{
    public Guid Id { get; set; } = Guid.NewGuid();
    public string Email { get; set; } = "";            // stored lower-case, unique
    public string PasswordHash { get; set; } = "";
    public string DisplayName { get; set; } = "";
    public AccountStatus Status { get; set; } = AccountStatus.Active;
    public int TokenVersion { get; set; }              // bump to revoke all sessions
    public bool MfaEnabled { get; set; }
    public string? MfaSecretEnc { get; set; }          // AES-GCM sealed TOTP secret; set at setup, active once MfaEnabled
    public long MfaLastStep { get; set; }              // last accepted TOTP step (replay protection)
    public int MfaFailures { get; set; }
    public DateTime? MfaLockedUntil { get; set; }
    public DateTime? EmailVerifiedAt { get; set; }     // set when the person confirms a code sent to Email
    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
}

public class Company
{
    public Guid Id { get; set; } = Guid.NewGuid();
    public string DisplayName { get; set; } = "";
    public string BusinessCategory { get; set; } = "";  // free text until the platform approves a category list
    public string? RegistrationRef { get; set; }
    public string ContactEmail { get; set; } = "";
    public string? ContactPhone { get; set; }
    public VerificationStatus Verification { get; set; } = VerificationStatus.Pending;
    public string? VerificationNote { get; set; }
    public AccountStatus Status { get; set; } = AccountStatus.Active;
    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;

    // Pending -> Approved | Rejected | NeedsInfo ; NeedsInfo -> Pending (owner resubmits)
    public bool TryDecide(string decision, string? note, out string? error)
    {
        error = null;
        if (Verification != VerificationStatus.Pending)
        {
            error = $"Company is {Verification}; only Pending companies can be decided.";
            return false;
        }
        var next = Verify.Map(decision);
        if (next is null) { error = "decision must be approve, reject or request_info."; return false; }
        Verification = next.Value;
        VerificationNote = note;
        return true;
    }

    public bool TryResubmit()
    {
        if (Verification != VerificationStatus.NeedsInfo) return false;
        Verification = VerificationStatus.Pending;
        return true;
    }
}

public static class Verify
{
    public static VerificationStatus? Map(string? decision) => decision switch
    {
        "approve" => VerificationStatus.Approved,
        "reject" => VerificationStatus.Rejected,
        "request_info" => VerificationStatus.NeedsInfo,
        _ => null
    };
}

public class Role { public string Code { get; set; } = ""; public string Scope { get; set; } = ""; }
public class Permission { public string Code { get; set; } = ""; }
public class RolePermission { public string RoleCode { get; set; } = ""; public string PermissionCode { get; set; } = ""; }

public class CompanyMembership
{
    public Guid Id { get; set; } = Guid.NewGuid();
    public Guid UserId { get; set; }
    public Guid CompanyId { get; set; }
    public MembershipStatus Status { get; set; } = MembershipStatus.Active;
    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
}
public class MembershipRole { public Guid MembershipId { get; set; } public string RoleCode { get; set; } = ""; }
public class PlatformRoleAssignment { public Guid UserId { get; set; } public string RoleCode { get; set; } = ""; }

public class Trade { public Guid Id { get; set; } = Guid.NewGuid(); public string Name { get; set; } = ""; public bool Active { get; set; } = true; }
public class Skill { public Guid Id { get; set; } = Guid.NewGuid(); public Guid TradeId { get; set; } public string Name { get; set; } = ""; public bool Active { get; set; } = true; }

public class Technician
{
    public Guid Id { get; set; } = Guid.NewGuid();
    public Guid UserId { get; set; }
    public string DisplayName { get; set; } = "";
    public string? Phone { get; set; }
    public DateTime? PhoneVerifiedAt { get; set; }     // cleared whenever the phone number changes
    public AccountStatus Status { get; set; } = AccountStatus.Active;
    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
}

public class TechnicianSkill
{
    public Guid TechnicianId { get; set; }
    public Guid SkillId { get; set; }
    public VerificationStatus Verification { get; set; } = VerificationStatus.Pending;
    public DateOnly? ExpiresOn { get; set; }
    public Guid? ReviewedBy { get; set; }
    public DateTime? ReviewedAt { get; set; }

    public bool IsEligible(DateOnly today) =>
        Verification == VerificationStatus.Approved && (ExpiresOn is null || ExpiresOn >= today);
}

public class AuditEvent
{
    public Guid Id { get; set; } = Guid.NewGuid();
    public Guid? ActorUserId { get; set; }
    public string Action { get; set; } = "";
    public string ResourceType { get; set; } = "";
    public string ResourceId { get; set; } = "";
    public Guid? CompanyId { get; set; }
    public DateTime OccurredAt { get; set; } = DateTime.UtcNow;
    public string CorrelationId { get; set; } = "";
    public string? Metadata { get; set; }              // never put secrets or documents here
}
