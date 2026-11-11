using Duale.Api.Domain;
using Microsoft.EntityFrameworkCore;
namespace Duale.Api.Data;

public static class ModelPhase2
{
    public static void Configure(ModelBuilder b)
    {
        b.Entity<TechnicianCompanyRelationship>(e =>
        {
            e.ToTable("Relationships");
            e.HasIndex(x => new { x.TechnicianId, x.CompanyId }).IsUnique();
            e.HasIndex(x => new { x.CompanyId, x.Status });
            e.HasOne<Technician>().WithMany().HasForeignKey(x => x.TechnicianId);
            e.HasOne<Company>().WithMany().HasForeignKey(x => x.CompanyId);
        });
        b.Entity<TechnicianAvailability>(e =>
        {
            e.ToTable("Availability");
            e.HasIndex(x => new { x.TechnicianId, x.StartsAt });
            e.HasOne<Technician>().WithMany().HasForeignKey(x => x.TechnicianId);
        });
        b.Entity<Customer>(e =>
        {
            e.ToTable("Customers");
            e.Property(x => x.Name).HasMaxLength(160);
            e.HasIndex(x => new { x.CompanyId, x.Name });
            e.HasOne<Company>().WithMany().HasForeignKey(x => x.CompanyId);
        });
        b.Entity<ServiceLocation>(e =>
        {
            e.ToTable("Locations");
            e.HasOne<Customer>().WithMany().HasForeignKey(x => x.CustomerId);
            e.HasOne<Company>().WithMany().HasForeignKey(x => x.CompanyId);
        });
        b.Entity<Job>(e =>
        {
            e.ToTable("Jobs");
            e.Property(x => x.Reference).HasMaxLength(30);
            e.Property(x => x.Description).HasMaxLength(4000);
            e.HasIndex(x => x.Reference).IsUnique();
            e.HasIndex(x => new { x.CompanyId, x.Status });
            e.HasOne<Company>().WithMany().HasForeignKey(x => x.CompanyId);
            e.HasOne<Customer>().WithMany().HasForeignKey(x => x.CustomerId);
            e.HasOne<ServiceLocation>().WithMany().HasForeignKey(x => x.LocationId);
            e.HasOne<Trade>().WithMany().HasForeignKey(x => x.TradeId);
        });
        b.Entity<JobRequiredSkill>(e =>
        {
            e.ToTable("JobRequiredSkills");
            e.HasKey(x => new { x.JobId, x.SkillId });
            e.HasOne<Job>().WithMany().HasForeignKey(x => x.JobId);
            e.HasOne<Skill>().WithMany().HasForeignKey(x => x.SkillId);
        });
        b.Entity<JobAssignment>(e =>
        {
            e.ToTable("Assignments");
            e.HasIndex(x => new { x.TechnicianId, x.Status });
            // At most one live (Offered/Accepted) assignment per job, enforced by the database.
            e.HasIndex(x => x.JobId).IsUnique().HasFilter("\"Status\" IN ('Offered','Accepted')").HasDatabaseName("UX_Assignments_OneActivePerJob");
            e.HasOne<Job>().WithMany().HasForeignKey(x => x.JobId);
            e.HasOne<Technician>().WithMany().HasForeignKey(x => x.TechnicianId);
            e.HasOne<TechnicianCompanyRelationship>().WithMany().HasForeignKey(x => x.RelationshipId);
        });
        b.Entity<JobStatusHistory>(e =>
        {
            e.ToTable("JobStatusHistory");
            e.HasIndex(x => x.JobId);
            e.HasOne<Job>().WithMany().HasForeignKey(x => x.JobId);
        });
        b.Entity<Notification>(e =>
        {
            e.ToTable("Notifications");
            e.HasIndex(x => new { x.UserId, x.ReadAt });
            e.HasOne<User>().WithMany().HasForeignKey(x => x.UserId);
        });
    }
}
