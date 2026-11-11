using Duale.Api.Domain;
using Microsoft.EntityFrameworkCore;
namespace Duale.Api.Data;

public static class ModelPhase8
{
    public static void Configure(ModelBuilder b)
    {
        b.Entity<JobRating>(e =>
        {
            e.ToTable("JobRatings");
            e.Property(x => x.Comment).HasMaxLength(1000);
            e.HasIndex(x => x.JobId).IsUnique();           // one rating per job
            e.HasIndex(x => x.TechnicianId);
            e.HasOne<Job>().WithMany().HasForeignKey(x => x.JobId);
            e.HasOne<Technician>().WithMany().HasForeignKey(x => x.TechnicianId);
            e.HasOne<Company>().WithMany().HasForeignKey(x => x.CompanyId);
        });
        b.Entity<VerificationCode>(e =>
        {
            e.ToTable("VerificationCodes");
            e.Property(x => x.Channel).HasMaxLength(10);
            e.Property(x => x.Target).HasMaxLength(254);
            e.Property(x => x.CodeHash).HasMaxLength(64);
            e.HasIndex(x => new { x.UserId, x.Channel });
            e.HasOne<User>().WithMany().HasForeignKey(x => x.UserId);
        });
    }
}
