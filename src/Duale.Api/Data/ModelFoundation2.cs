using Duale.Api.Domain;
using Microsoft.EntityFrameworkCore;
namespace Duale.Api.Data;

public static class ModelFoundation2
{
    public static void Configure(ModelBuilder b)
    {
        b.Entity<Branch>(e =>
        {
            e.ToTable("Branches");
            e.Property(x => x.Name).HasMaxLength(120);
            e.Property(x => x.Address).HasMaxLength(300);
            e.HasIndex(x => new { x.CompanyId, x.Name }).IsUnique();
            e.HasOne<Company>().WithMany().HasForeignKey(x => x.CompanyId);
        });
        b.Entity<BranchMembership>(e =>
        {
            e.ToTable("BranchMemberships");
            e.HasKey(x => new { x.MembershipId, x.BranchId });
            e.HasOne<CompanyMembership>().WithMany().HasForeignKey(x => x.MembershipId);
            e.HasOne<Branch>().WithMany().HasForeignKey(x => x.BranchId);
        });
        b.Entity<ServiceArea>(e => { e.ToTable("ServiceAreas"); e.Property(x => x.Name).HasMaxLength(120); e.HasIndex(x => x.Name).IsUnique(); });
        b.Entity<TechnicianServiceArea>(e =>
        {
            e.ToTable("TechnicianServiceAreas");
            e.HasKey(x => new { x.TechnicianId, x.ServiceAreaId });
            e.HasOne<Technician>().WithMany().HasForeignKey(x => x.TechnicianId);
            e.HasOne<ServiceArea>().WithMany().HasForeignKey(x => x.ServiceAreaId);
        });
        b.Entity<ServiceLocation>(e =>
        {
            e.HasOne<ServiceArea>().WithMany().HasForeignKey(x => x.ServiceAreaId);
        });
        b.Entity<TechnicianDocument>(e =>
        {
            e.ToTable("TechnicianDocuments");
            e.Property(x => x.Kind).HasMaxLength(20);
            e.Property(x => x.FileName).HasMaxLength(120);
            e.Property(x => x.ContentType).HasMaxLength(60);
            e.Property(x => x.Sha256).HasMaxLength(64);
            e.Property(x => x.StorageKey).HasMaxLength(64);
            e.Property(x => x.ReviewNote).HasMaxLength(500);
            e.HasIndex(x => x.StorageKey).IsUnique();
            e.HasIndex(x => new { x.Status, x.UploadedAt });
            e.HasIndex(x => x.TechnicianId);
            e.HasOne<Technician>().WithMany().HasForeignKey(x => x.TechnicianId);
        });
        b.Entity<MfaRecoveryCode>(e =>
        {
            e.ToTable("MfaRecoveryCodes");
            e.Property(x => x.CodeHash).HasMaxLength(64);
            e.HasIndex(x => new { x.UserId, x.CodeHash }).IsUnique();
            e.HasOne<User>().WithMany().HasForeignKey(x => x.UserId);
        });
        b.Entity<PasswordResetToken>(e =>
        {
            e.ToTable("PasswordResetTokens");
            e.Property(x => x.TokenHash).HasMaxLength(64);
            e.HasIndex(x => x.TokenHash).IsUnique();
            e.HasOne<User>().WithMany().HasForeignKey(x => x.UserId);
        });
    }
}
