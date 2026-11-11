using Duale.Api.Domain;
using Microsoft.EntityFrameworkCore;
namespace Duale.Api.Data;

public static class ModelPhase3
{
    public static void Configure(ModelBuilder b)
    {
        b.Entity<JobEvidence>(e =>
        {
            e.ToTable("JobEvidence");
            e.Property(x => x.Kind).HasMaxLength(20); e.Property(x => x.FileName).HasMaxLength(120);
            e.Property(x => x.ContentType).HasMaxLength(60); e.Property(x => x.Sha256).HasMaxLength(64); e.Property(x => x.StorageKey).HasMaxLength(64);
            e.HasIndex(x => x.StorageKey).IsUnique(); e.HasIndex(x => x.JobId);
            e.HasOne<Job>().WithMany().HasForeignKey(x => x.JobId);
            e.HasOne<JobAssignment>().WithMany().HasForeignKey(x => x.AssignmentId);
        });
        b.Entity<JobWorkReport>(e =>
        {
            e.ToTable("JobWorkReports");
            e.Property(x => x.Summary).HasMaxLength(4000); e.Property(x => x.HoursWorked).HasPrecision(9, 2);
            e.HasIndex(x => new { x.JobId, x.Version }).IsUnique();
            e.HasOne<Job>().WithMany().HasForeignKey(x => x.JobId);
            e.HasOne<JobAssignment>().WithMany().HasForeignKey(x => x.AssignmentId);
        });
        b.Entity<JobScopeChange>(e =>
        {
            e.ToTable("JobScopeChanges");
            e.Property(x => x.Description).HasMaxLength(2000); e.Property(x => x.DecisionNote).HasMaxLength(500);
            e.HasIndex(x => new { x.JobId, x.Status });
            e.HasOne<Job>().WithMany().HasForeignKey(x => x.JobId);
            e.HasOne<JobAssignment>().WithMany().HasForeignKey(x => x.AssignmentId);
        });
        b.Entity<JobReview>(e =>
        {
            e.ToTable("JobReviews");
            e.Property(x => x.Decision).HasMaxLength(20); e.Property(x => x.Note).HasMaxLength(1000);
            e.HasIndex(x => x.JobId);
            e.HasOne<Job>().WithMany().HasForeignKey(x => x.JobId);
        });
        b.Entity<JobComplaint>(e =>
        {
            e.ToTable("JobComplaints");
            e.Property(x => x.Description).HasMaxLength(2000); e.Property(x => x.Status).HasMaxLength(20); e.Property(x => x.Resolution).HasMaxLength(2000);
            e.HasIndex(x => new { x.CompanyId, x.Status });
            e.HasOne<Job>().WithMany().HasForeignKey(x => x.JobId);
            e.HasOne<Company>().WithMany().HasForeignKey(x => x.CompanyId);
        });
        b.Entity<JobRelationship>(e =>
        {
            e.ToTable("JobRelationships");
            e.Property(x => x.Type).HasMaxLength(20); e.Property(x => x.ReworkResponsibility).HasMaxLength(20); e.Property(x => x.Notes).HasMaxLength(1000);
            e.HasIndex(x => x.ChildJobId).IsUnique();   // a callback job repairs exactly one job
            e.HasIndex(x => x.ParentJobId);
            e.HasOne<Job>().WithMany().HasForeignKey(x => x.ParentJobId);
            e.HasOne<Job>().WithMany().HasForeignKey(x => x.ChildJobId);
        });
        b.Entity<IdempotencyRecord>(e =>
        {
            e.ToTable("IdempotencyRecords");
            e.Property(x => x.Scope).HasMaxLength(80); e.Property(x => x.Key).HasMaxLength(100);
            e.HasIndex(x => new { x.Scope, x.Key }).IsUnique();
            e.HasIndex(x => x.CreatedAt);
        });
    }
}
