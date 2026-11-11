using Duale.Api.Domain;
using Microsoft.EntityFrameworkCore;
namespace Duale.Api.Data;

public static class ModelPhase4
{
    static void Money(Microsoft.EntityFrameworkCore.Metadata.Builders.PropertyBuilder<decimal> p) => p.HasPrecision(19, 4);

    public static void Configure(ModelBuilder b)
    {
        b.Entity<JobFinancialTerms>(e =>
        {
            e.ToTable("JobFinancialTerms");
            e.Property(x => x.Currency).HasMaxLength(3); e.Property(x => x.PayerType).HasMaxLength(10); e.Property(x => x.Note).HasMaxLength(500);
            e.Property(x => x.Status).HasConversion<string>().HasMaxLength(20);
            Money(e.Property(x => x.CustomerCharge)); Money(e.Property(x => x.TechnicianCompensation)); Money(e.Property(x => x.PlatformFee));
            e.HasIndex(x => new { x.JobId, x.Version }).IsUnique();
            e.HasIndex(x => x.JobId).IsUnique().HasFilter("\"Status\" = 'Approved'").HasDatabaseName("UX_Terms_OneApprovedPerJob");
            e.HasOne<Job>().WithMany().HasForeignKey(x => x.JobId);
            e.HasOne<Company>().WithMany().HasForeignKey(x => x.CompanyId);
        });
        b.Entity<Invoice>(e =>
        {
            e.ToTable("Invoices");
            e.Property(x => x.Number).HasMaxLength(40); e.Property(x => x.Currency).HasMaxLength(3); e.Property(x => x.Status).HasMaxLength(10); e.Property(x => x.VoidReason).HasMaxLength(500);
            Money(e.Property(x => x.Total)); e.Property(x => x.Seq).IsConcurrencyToken();
            e.HasIndex(x => x.Number).IsUnique();
            e.HasIndex(x => x.JobId).IsUnique().HasFilter("\"Status\" <> 'Void'").HasDatabaseName("UX_Invoices_OneLivePerJob");
            e.HasIndex(x => new { x.CompanyId, x.Status });
            e.HasOne<Job>().WithMany().HasForeignKey(x => x.JobId);
            e.HasOne<Company>().WithMany().HasForeignKey(x => x.CompanyId);
            e.HasOne<JobFinancialTerms>().WithMany().HasForeignKey(x => x.TermsId);
        });
        b.Entity<InvoiceLine>(e =>
        {
            e.ToTable("InvoiceLines");
            e.Property(x => x.Description).HasMaxLength(200);
            Money(e.Property(x => x.Quantity)); Money(e.Property(x => x.UnitPrice)); Money(e.Property(x => x.Amount));
            e.HasOne<Invoice>().WithMany().HasForeignKey(x => x.InvoiceId);
        });
        b.Entity<TechnicianPayable>(e =>
        {
            e.ToTable("TechnicianPayables");
            e.Property(x => x.PayerType).HasMaxLength(10); e.Property(x => x.Currency).HasMaxLength(3); e.Property(x => x.Status).HasMaxLength(12);
            Money(e.Property(x => x.Amount)); e.Property(x => x.Seq).IsConcurrencyToken();
            e.HasIndex(x => x.JobId).IsUnique().HasFilter("\"Status\" <> 'Cancelled'").HasDatabaseName("UX_Payables_OneLivePerJob");
            e.HasIndex(x => new { x.CompanyId, x.Status }); e.HasIndex(x => x.TechnicianId);
            e.HasOne<Job>().WithMany().HasForeignKey(x => x.JobId);
            e.HasOne<Technician>().WithMany().HasForeignKey(x => x.TechnicianId);
            e.HasOne<Company>().WithMany().HasForeignKey(x => x.CompanyId);
            e.HasOne<JobFinancialTerms>().WithMany().HasForeignKey(x => x.TermsId);
        });
        b.Entity<PaymentRecord>(e =>
        {
            e.ToTable("PaymentRecords");
            e.Property(x => x.Reference).HasMaxLength(40); e.Property(x => x.Kind).HasMaxLength(40); e.Property(x => x.PayerType).HasMaxLength(10); e.Property(x => x.PayeeType).HasMaxLength(10);
            e.Property(x => x.Method).HasMaxLength(20); e.Property(x => x.Currency).HasMaxLength(3); e.Property(x => x.ProviderRef).HasMaxLength(100);
            e.Property(x => x.AcknowledgedBy).HasMaxLength(120); e.Property(x => x.Note).HasMaxLength(500); e.Property(x => x.ReverseReason).HasMaxLength(500); e.Property(x => x.ReconcileNote).HasMaxLength(500);
            e.Property(x => x.Status).HasConversion<string>().HasMaxLength(20);
            Money(e.Property(x => x.Amount));
            e.HasIndex(x => x.Reference).IsUnique();
            // The same provider/bank reference can never be posted twice for a company.
            e.HasIndex(x => new { x.CompanyId, x.Method, x.ProviderRef }).IsUnique().HasFilter("\"ProviderRef\" IS NOT NULL").HasDatabaseName("UX_Payments_ProviderRef");
            e.HasIndex(x => new { x.CompanyId, x.Status, x.Reconciled });
            e.HasOne<Job>().WithMany().HasForeignKey(x => x.JobId);
            e.HasOne<Company>().WithMany().HasForeignKey(x => x.CompanyId);
            e.HasOne<Invoice>().WithMany().HasForeignKey(x => x.InvoiceId);
            e.HasOne<TechnicianPayable>().WithMany().HasForeignKey(x => x.PayableId);
            e.HasOne<Refund>().WithMany().HasForeignKey(x => x.RefundId);
        });
        b.Entity<PaymentEvent>(e =>
        {
            e.ToTable("PaymentEvents");
            e.Property(x => x.Event).HasMaxLength(40); e.Property(x => x.Note).HasMaxLength(500);
            e.HasIndex(x => x.PaymentId);
            e.HasOne<PaymentRecord>().WithMany().HasForeignKey(x => x.PaymentId);
        });
        b.Entity<Refund>(e =>
        {
            e.ToTable("Refunds");
            e.Property(x => x.Currency).HasMaxLength(3); e.Property(x => x.Reason).HasMaxLength(500); e.Property(x => x.Status).HasMaxLength(12); e.Property(x => x.DecisionNote).HasMaxLength(500);
            Money(e.Property(x => x.Amount)); e.Property(x => x.Seq).IsConcurrencyToken();
            e.HasIndex(x => new { x.CompanyId, x.Status });
            e.HasOne<Invoice>().WithMany().HasForeignKey(x => x.InvoiceId);
            e.HasOne<Job>().WithMany().HasForeignKey(x => x.JobId);
            e.HasOne<Company>().WithMany().HasForeignKey(x => x.CompanyId);
        });
        b.Entity<LedgerEntry>(e =>
        {
            e.ToTable("LedgerEntries");
            e.Property(x => x.TxnKey).HasMaxLength(80); e.Property(x => x.LineKey).HasMaxLength(90); e.Property(x => x.AccountCode).HasMaxLength(10);
            e.Property(x => x.Currency).HasMaxLength(3); e.Property(x => x.SourceType).HasMaxLength(30); e.Property(x => x.SourceId).HasMaxLength(60); e.Property(x => x.ReversesLineKey).HasMaxLength(90);
            Money(e.Property(x => x.Debit)); Money(e.Property(x => x.Credit));
            e.HasIndex(x => x.LineKey).IsUnique();
            e.HasIndex(x => new { x.CompanyId, x.TxnKey });
            e.HasOne<Company>().WithMany().HasForeignKey(x => x.CompanyId);
        });
        b.Entity<PlatformFeeRecord>(e =>
        {
            e.ToTable("PlatformFeeRecords");
            e.Property(x => x.Currency).HasMaxLength(3); e.Property(x => x.Status).HasMaxLength(10); e.Property(x => x.Note).HasMaxLength(500);
            Money(e.Property(x => x.Amount));
            e.HasIndex(x => x.JobId).IsUnique();   // one fee per job
            e.HasIndex(x => new { x.Status, x.CompanyId });
            e.HasOne<Job>().WithMany().HasForeignKey(x => x.JobId);
            e.HasOne<Company>().WithMany().HasForeignKey(x => x.CompanyId);
        });
        b.Entity<Dispute>(e =>
        {
            e.ToTable("Disputes");
            e.Property(x => x.Description).HasMaxLength(2000); e.Property(x => x.Status).HasMaxLength(10); e.Property(x => x.Outcome).HasMaxLength(10); e.Property(x => x.Resolution).HasMaxLength(2000);
            e.HasIndex(x => new { x.CompanyId, x.Status });
            e.HasOne<Job>().WithMany().HasForeignKey(x => x.JobId);
            e.HasOne<Company>().WithMany().HasForeignKey(x => x.CompanyId);
            e.HasOne<TechnicianPayable>().WithMany().HasForeignKey(x => x.PayableId);
            e.HasOne<PaymentRecord>().WithMany().HasForeignKey(x => x.PaymentId);
        });

        // Phase 5
        b.Entity<NotificationPreference>(e =>
        {
            e.ToTable("NotificationPreferences"); e.HasKey(x => new { x.UserId, x.Channel }); e.Property(x => x.Channel).HasMaxLength(10);
            e.HasOne<User>().WithMany().HasForeignKey(x => x.UserId);
        });
        b.Entity<NotificationDelivery>(e =>
        {
            e.ToTable("NotificationDeliveries");
            e.Property(x => x.Channel).HasMaxLength(10); e.Property(x => x.Status).HasMaxLength(10); e.Property(x => x.LastError).HasMaxLength(500); e.Property(x => x.ProviderMessageId).HasMaxLength(100);
            e.HasIndex(x => new { x.NotificationId, x.Channel }).IsUnique();
            e.HasIndex(x => new { x.Status, x.NextAttemptAt });
            e.HasOne<Notification>().WithMany().HasForeignKey(x => x.NotificationId);
            e.HasOne<User>().WithMany().HasForeignKey(x => x.UserId);
        });
        b.Entity<Notification>(e =>
        {
            e.Property(x => x.DedupeKey).HasMaxLength(120);
            e.HasIndex(x => x.DedupeKey).IsUnique().HasFilter("\"DedupeKey\" IS NOT NULL").HasDatabaseName("UX_Notifications_Dedupe");
            e.HasIndex(x => x.FannedOutAt);
        });
    }
}
