namespace Duale.Api.Domain;

// A company's 1-5 star rating of the technician whose work on a job was approved. One rating per job.
public class JobRating
{
    public Guid Id { get; set; } = Guid.NewGuid();
    public Guid JobId { get; set; }
    public Guid CompanyId { get; set; }
    public Guid TechnicianId { get; set; }
    public int Stars { get; set; }
    public string? Comment { get; set; }
    public Guid RatedBy { get; set; }
    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
}

// A 6-digit code sent to an email address or phone number. Only a salted hash is stored.
public class VerificationCode
{
    public Guid Id { get; set; } = Guid.NewGuid();
    public Guid UserId { get; set; }
    public string Channel { get; set; } = "";           // email | phone
    public string Target { get; set; } = "";            // the address the code was sent to
    public string CodeHash { get; set; } = "";
    public int Attempts { get; set; }
    public DateTime ExpiresAt { get; set; }
    public DateTime? UsedAt { get; set; }
    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
}
