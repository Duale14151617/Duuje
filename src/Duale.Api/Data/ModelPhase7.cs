using Duale.Api.Domain;
using Microsoft.EntityFrameworkCore;
namespace Duale.Api.Data;

public static class ModelPhase7
{
    public static void Configure(ModelBuilder b)
    {
        b.Entity<OutboxEvent>(e =>
        {
            e.ToTable("OutboxEvents");
            e.Property(x => x.Type).HasMaxLength(80); e.Property(x => x.AggregateType).HasMaxLength(60); e.Property(x => x.AggregateId).HasMaxLength(80);
            e.Property(x => x.Status).HasMaxLength(10); e.Property(x => x.LastError).HasMaxLength(500);
            e.HasIndex(x => new { x.Status, x.NextAttemptAt });
            e.HasIndex(x => new { x.CompanyId, x.CreatedAt });
        });
        b.Entity<PlatformSubscription>(e =>
        {
            e.ToTable("PlatformSubscriptions");
            e.Property(x => x.PlanLabel).HasMaxLength(100); e.Property(x => x.Currency).HasMaxLength(3); e.Property(x => x.Status).HasMaxLength(10);
            e.Property(x => x.Note).HasMaxLength(500); e.Property(x => x.CancelReason).HasMaxLength(500);
            e.Property(x => x.Amount).HasPrecision(19, 4);
            e.Property(x => x.Seq).IsConcurrencyToken();
            e.HasIndex(x => new { x.CompanyId, x.Status, x.PeriodStart });
            e.HasOne<Company>().WithMany().HasForeignKey(x => x.CompanyId);
        });
        b.Entity<IntegrationAccount>(e =>
        {
            e.ToTable("IntegrationAccounts");
            e.Property(x => x.Kind).HasMaxLength(20); e.Property(x => x.Provider).HasMaxLength(60); e.Property(x => x.DisplayName).HasMaxLength(120);
            e.Property(x => x.SecretRef).HasMaxLength(100); e.Property(x => x.Status).HasMaxLength(10); e.Property(x => x.Note).HasMaxLength(500);
            e.HasIndex(x => new { x.Kind, x.Provider, x.DisplayName }).IsUnique();
        });
    }
}
